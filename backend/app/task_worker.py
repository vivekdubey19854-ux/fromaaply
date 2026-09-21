from __future__ import annotations

import json
import logging
import signal
import threading
import time
from collections.abc import Callable
from typing import Any

from redis import Redis
from sqlalchemy.orm import Session

from .config import settings
from .database import SessionLocal
from .task_service import TaskStateError, claim_task, checkpoint_task, recover_expired_leases, transition_task
from .task_service import heartbeat_task

log = logging.getLogger(__name__)


class RedisTaskQueue:
    def __init__(self, client: Redis | None = None, *, queue_name: str | None = None, dead_letter_name: str | None = None) -> None:
        self.client = client or Redis.from_url(settings.redis_url, decode_responses=True)
        self.queue_name = queue_name or settings.task_queue_name
        self.dead_letter_name = dead_letter_name or settings.task_dead_letter_queue_name

    def enqueue(self, task_id: str, *, user_id: str) -> None:
        self.client.lpush(self.queue_name, json.dumps({"task_id": task_id, "user_id": user_id}))

    def pop(self, timeout: int = 1) -> dict[str, Any] | None:
        item = self.client.brpop(self.queue_name, timeout=timeout)
        if not item:
            return None
        _, raw = item
        payload = json.loads(raw)
        if not isinstance(payload, dict) or not payload.get("task_id") or not payload.get("user_id"):
            raise ValueError("invalid task queue payload")
        return payload

    def dead_letter(self, payload: dict[str, Any], reason: str) -> None:
        self.client.lpush(self.dead_letter_name, json.dumps({**payload, "reason": reason}))


class DurableTaskWorker:
    """Redis-driven task lifecycle worker; browser execution is injected by a safe handler."""

    def __init__(self, *, queue: RedisTaskQueue, session_factory: Callable[[], Session] = SessionLocal, owner_id: str = "worker-1", handler: Callable[[Session, dict[str, Any], Callable[..., dict[str, Any]]], None] | None = None, stop_event: threading.Event | None = None) -> None:
        self.queue = queue
        self.session_factory = session_factory
        self.owner_id = owner_id
        self.handler = handler or self._checkpoint_only_handler
        self.stop_event = stop_event or threading.Event()

    @staticmethod
    def _checkpoint_only_handler(db: Session, payload: dict[str, Any], checkpoint: Callable[..., dict[str, Any]]) -> None:
        # The orchestrator/browser adapter is deliberately injected. A generic worker
        # never guesses a target action and never bypasses human gates.
        checkpoint(step="claimed", resume_reference="orchestrator_handler_required")

    def process_once(self) -> bool:
        db = self.session_factory()
        payload: dict[str, Any] | None = None
        try:
            recovered = recover_expired_leases(db, max_retries=settings.task_max_retries)
            for item in recovered:
                if item["state"] == "queued":
                    self.queue.enqueue(str(item["task_id"]), user_id=str(item["user_id"]))
            payload = self.queue.pop(timeout=1)
            if payload is None:
                return False
            task_id, user_id = str(payload["task_id"]), str(payload["user_id"])
            claimed = claim_task(db, task_id=task_id, user_id=user_id, owner_id=self.owner_id, lease_seconds=settings.task_worker_lease_seconds)
            if claimed["state"] != "running":
                return False
            heartbeat_stop = threading.Event()
            def heartbeat_loop() -> None:
                while not heartbeat_stop.wait(max(1, settings.task_worker_lease_seconds // 3)):
                    heartbeat_db = self.session_factory()
                    try:
                        heartbeat_task(heartbeat_db, task_id=task_id, user_id=user_id, owner_id=self.owner_id, lease_seconds=settings.task_worker_lease_seconds)
                    except Exception:
                        log.exception("task lease heartbeat failed")
                        heartbeat_stop.set()
                    finally:
                        heartbeat_db.close()
            heartbeat_thread = threading.Thread(target=heartbeat_loop, name=f"task-heartbeat-{task_id[:8]}", daemon=True)
            heartbeat_thread.start()
            checkpoint = lambda *, step, resume_reference=None: checkpoint_task(db, task_id=task_id, user_id=user_id, owner_id=self.owner_id, step=step, resume_reference=resume_reference)
            try:
                self.handler(db, payload, checkpoint)
                transition_task(db, task_id=task_id, user_id=user_id, owner_id=self.owner_id, to_state="completed", step=claimed.get("current_step") or "complete")
            finally:
                heartbeat_stop.set()
                heartbeat_thread.join(timeout=2)
            return True
        except Exception as exc:
            if payload:
                try:
                    db.rollback()
                    task_id, user_id = str(payload["task_id"]), str(payload["user_id"])
                    task = transition_task(db, task_id=task_id, user_id=user_id, owner_id=self.owner_id, to_state="failed", error_code="worker_error", error_message=str(exc)[:1000])
                    if task["retry_count"] >= settings.task_max_retries:
                        self.queue.dead_letter(payload, str(exc)[:500])
                    else:
                        queued = transition_task(db, task_id=task_id, user_id=user_id, owner_id=self.owner_id, to_state="queued", error_code="retry_scheduled", error_message=str(exc)[:1000])
                        self.queue.enqueue(task_id, user_id=user_id)
                except Exception:
                    db.rollback()
            log.exception("task worker failed")
            return False
        finally:
            db.close()

    def run_forever(self) -> None:
        def stop_handler(_signum: int, _frame: Any) -> None:
            self.stop_event.set()
        signal.signal(signal.SIGTERM, stop_handler)
        signal.signal(signal.SIGINT, stop_handler)
        while not self.stop_event.is_set():
            self.process_once()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    DurableTaskWorker(queue=RedisTaskQueue(), owner_id=f"worker-{__import__('socket').gethostname()}").run_forever()
