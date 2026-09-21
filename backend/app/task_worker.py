from __future__ import annotations

import json
import asyncio
import concurrent.futures
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
from .db_models import FormTaskRecord
from .orchestrator import fill_form, load_workflow, open_application, prepare_form
from .browser_agent import BrowserSessionNotFound, close_all_sessions, get_session
from .config import settings
from .storage import PrivateStorage
from .task_service import TaskStateError, bind_browser_session, claim_task, checkpoint_task, recover_expired_leases, release_task_lock, transition_task
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


class TaskPaused(RuntimeError):
    """Safe pause: no retry and no automated bypass of a human gate."""


class DurableTaskWorker:
    """Redis-driven task lifecycle worker; browser execution is injected by a safe handler."""

    def __init__(self, *, queue: RedisTaskQueue, session_factory: Callable[[], Session] = SessionLocal, owner_id: str = "worker-1", handler: Callable[[Session, dict[str, Any], Callable[..., dict[str, Any]]], None] | None = None, stop_event: threading.Event | None = None) -> None:
        self.queue = queue
        self.session_factory = session_factory
        self.owner_id = owner_id
        self.handler = handler or self._orchestrator_handler
        self.stop_event = stop_event or threading.Event()
        self._browser_loop: asyncio.AbstractEventLoop | None = None
        self._browser_thread: threading.Thread | None = None

    @staticmethod
    def _checkpoint_only_handler(db: Session, payload: dict[str, Any], checkpoint: Callable[..., dict[str, Any]]) -> None:
        # The orchestrator/browser adapter is deliberately injected. A generic worker
        # never guesses a target action and never bypasses human gates.
        checkpoint(step="claimed", resume_reference="orchestrator_handler_required")

    def _ensure_browser_runtime(self) -> asyncio.AbstractEventLoop:
        if self._browser_loop and self._browser_thread and self._browser_thread.is_alive():
            return self._browser_loop
        loop = asyncio.new_event_loop()
        ready = threading.Event()
        def run_loop() -> None:
            asyncio.set_event_loop(loop)
            ready.set()
            loop.run_forever()
        thread = threading.Thread(target=run_loop, name=f"browser-worker-loop-{self.owner_id}", daemon=True)
        thread.start()
        ready.wait(timeout=5)
        self._browser_loop, self._browser_thread = loop, thread
        return loop

    def _orchestrator_handler(self, db: Session, payload: dict[str, Any], checkpoint: Callable[..., dict[str, Any]]) -> None:
        loop = self._ensure_browser_runtime()
        future = asyncio.run_coroutine_threadsafe(self._orchestrator_handler_async(db, payload, checkpoint), loop)
        try:
            future.result(timeout=300)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise TaskPaused("browser step timed out and requires recovery") from exc

    @staticmethod
    async def _orchestrator_handler_async(db: Session, payload: dict[str, Any], checkpoint: Callable[..., dict[str, Any]]) -> None:
        task = db.get(FormTaskRecord, str(payload["task_id"]))
        if task is None or task.user_id != str(payload["user_id"]):
            raise TaskStateError("task ownership changed")
        if not task.workflow_id:
            checkpoint(step="awaiting_workflow", resume_reference="workflow_id_required")
            return
        storage = PrivateStorage(settings.storage_root)
        workflow = load_workflow(storage, task.user_id, task.workflow_id)
        state = str(workflow.get("state", ""))
        if state in {"awaiting_url", "research_ready", "documents_missing", "cancelled"}:
            checkpoint(step="awaiting_user", resume_reference=f"workflow_state:{state}")
            raise TaskPaused(f"workflow requires user action: {state}")
        if state not in {"documents_ready", "browser_ready", "form_review", "otp_required", "captcha_required", "final_review"}:
            checkpoint(step="workflow_checkpoint", resume_reference=f"workflow_state:{state}")
            raise TaskPaused(f"workflow is not executable from state: {state}")
        session_id = workflow.get("session_id")
        session = None
        if session_id:
            try:
                session = get_session(str(session_id), task.user_id)
            except BrowserSessionNotFound:
                session = None
        if session is None:
            if state != "documents_ready":
                checkpoint(step="browser_recovery", resume_reference="browser_session_recreate")
            workflow = await open_application(db, storage, task.user_id, task.workflow_id, resume=state != "documents_ready")
            session_id = str(workflow["session_id"])
            payload["browser_session_id"] = session_id
            bind_browser_session(db, task_id=task.task_id, user_id=task.user_id, owner_id=payload.get("owner_id") or "worker", browser_session_id=session_id)
            checkpoint(step="browser_opened", resume_reference=f"workflow:{task.workflow_id}:browser:{session_id}")
        if state == "final_review":
            checkpoint(step="final_review", resume_reference=f"workflow:{task.workflow_id}:manual_submit_only")
            raise TaskPaused("final review requires manual user submission")
        if state in {"documents_ready", "browser_ready"}:
            planned = await prepare_form(db, storage, task.user_id, task.workflow_id)
            payload["workflow_state"] = planned.get("state")
            checkpoint(step="form_inspected", resume_reference=f"workflow:{task.workflow_id}:plan")
            human_required = (planned.get("plan") or {}).get("human_required") or []
            if human_required:
                raise TaskPaused(f"human gate required: {','.join(map(str, human_required))}")
            safe_fills = [item for item in (planned.get("plan") or {}).get("fills", []) if not item.get("requires_approval")]
            if safe_fills:
                result = await fill_form(db, storage, task.user_id, task.workflow_id, safe_fills)
                checkpoint(step="form_filled", resume_reference=f"workflow:{task.workflow_id}:final_review")
                if result.get("human_required"):
                    raise TaskPaused("human verification is required before continuing")
                raise TaskPaused("final review requires manual user submission")
            raise TaskPaused("explicit sensitive-field approval is required before filling")
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
            payload["owner_id"] = self.owner_id
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
                    if isinstance(exc, TaskPaused):
                        transition_task(db, task_id=task_id, user_id=user_id, owner_id=self.owner_id, to_state="paused", error_code="human_gate", error_message=str(exc), resume_reference=payload.get("workflow_state") or "human_action_required")
                        release_task_lock(db, task_id=task_id, owner_id=self.owner_id)
                        return False
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
        try:
            while not self.stop_event.is_set():
                self.process_once()
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        if not self._browser_loop:
            return
        loop = self._browser_loop
        try:
            asyncio.run_coroutine_threadsafe(close_all_sessions(), loop).result(timeout=10)
        except Exception:
            log.exception("browser worker shutdown failed")
        loop.call_soon_threadsafe(loop.stop)
        if self._browser_thread:
            self._browser_thread.join(timeout=10)
        loop.close()
        self._browser_loop = None
        self._browser_thread = None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    DurableTaskWorker(queue=RedisTaskQueue(), owner_id=f"worker-{__import__('socket').gethostname()}").run_forever()
