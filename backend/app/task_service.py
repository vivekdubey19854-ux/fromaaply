from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db_models import FormTaskRecord, TaskLockRecord, TaskStepRecord, WorkflowEventRecord

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "queued": {"running", "cancelled", "failed"},
    "running": {"paused", "completed", "failed", "cancelled"},
    "paused": {"running", "cancelled", "failed"},
    "failed": {"queued", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}


class TaskStateError(RuntimeError):
    pass


class TaskNotFound(TaskStateError):
    pass


def _serialize(task: FormTaskRecord) -> dict[str, Any]:
    return {"task_id": task.task_id, "user_id": task.user_id, "workflow_id": task.workflow_id, "website_id": task.website_id, "state": task.state, "current_step": task.current_step, "target_url": task.target_url, "browser_session_id": task.browser_session_id, "error_code": task.error_code, "error_message": task.error_message, "retry_count": task.retry_count, "resume_reference": task.resume_reference, "created_at": task.created_at.isoformat() if task.created_at else None, "updated_at": task.updated_at.isoformat() if task.updated_at else None, "started_at": task.started_at.isoformat() if task.started_at else None, "completed_at": task.completed_at.isoformat() if task.completed_at else None, "paused_at": task.paused_at.isoformat() if task.paused_at else None}


def create_task(db: Session, *, user_id: str, target_url: str | None = None, website_id: str | None = None, workflow_id: str | None = None, idempotency_key: str | None = None) -> dict[str, Any]:
    persisted_key = f"{user_id}:{idempotency_key}" if idempotency_key else None
    if idempotency_key:
        existing = db.scalar(select(FormTaskRecord).where(FormTaskRecord.idempotency_key == persisted_key, FormTaskRecord.user_id == user_id))
        if existing:
            return _serialize(existing)
    task = FormTaskRecord(task_id=str(uuid4()), user_id=user_id, target_url=target_url, website_id=website_id, workflow_id=workflow_id, idempotency_key=persisted_key, state="queued")
    db.add(task)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if idempotency_key:
            existing = db.scalar(select(FormTaskRecord).where(FormTaskRecord.idempotency_key == persisted_key, FormTaskRecord.user_id == user_id))
            if existing:
                return _serialize(existing)
        raise
    db.refresh(task)
    return _serialize(task)


def get_task(db: Session, task_id: str, user_id: str) -> FormTaskRecord:
    task = db.scalar(select(FormTaskRecord).where(FormTaskRecord.task_id == task_id, FormTaskRecord.user_id == user_id))
    if not task:
        raise TaskNotFound("task not found")
    return task


def list_tasks(db: Session, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
    tasks = db.scalars(select(FormTaskRecord).where(FormTaskRecord.user_id == user_id).order_by(FormTaskRecord.created_at.desc()).limit(limit)).all()
    return [_serialize(task) for task in tasks]


def transition_task(db: Session, *, task_id: str, user_id: str, to_state: str, step: str | None = None, error_code: str | None = None, error_message: str | None = None, resume_reference: str | None = None) -> dict[str, Any]:
    task = get_task(db, task_id, user_id)
    if to_state not in ALLOWED_TRANSITIONS.get(task.state, set()):
        raise TaskStateError(f"illegal task transition: {task.state} -> {to_state}")
    old_state = task.state
    now = datetime.utcnow()
    task.state = to_state
    task.current_step = step or task.current_step
    task.error_code = error_code
    task.error_message = error_message
    task.resume_reference = resume_reference or task.resume_reference
    task.updated_at = now
    if to_state == "running" and task.started_at is None:
        task.started_at = now
    if to_state == "paused":
        task.paused_at = now
    if to_state in {"completed", "cancelled"}:
        task.completed_at = now
    if to_state == "queued" and old_state == "failed":
        task.retry_count += 1
    db.add(WorkflowEventRecord(task_id=task.task_id, workflow_id=task.workflow_id, user_id=user_id, event_type="task.transition", from_state=old_state, to_state=to_state, details=error_message))
    db.commit()
    db.refresh(task)
    return _serialize(task)


def claim_task(db: Session, *, task_id: str, user_id: str, owner_id: str, lease_seconds: int = 60) -> dict[str, Any]:
    task = get_task(db, task_id, user_id)
    if task.state not in {"queued", "failed"}:
        raise TaskStateError(f"task cannot be claimed from {task.state}")
    now = datetime.utcnow()
    existing = db.scalar(select(TaskLockRecord).where(TaskLockRecord.task_id == task_id))
    if existing and existing.locked_until > now and existing.owner_id != owner_id:
        raise TaskStateError("task is already locked")
    if existing:
        existing.owner_id = owner_id
        existing.locked_until = now + timedelta(seconds=lease_seconds)
    else:
        db.add(TaskLockRecord(task_id=task_id, owner_id=owner_id, locked_until=now + timedelta(seconds=lease_seconds)))
    db.commit()
    return transition_task(db, task_id=task_id, user_id=user_id, to_state="running", step=task.current_step or "start")


def release_task_lock(db: Session, *, task_id: str, owner_id: str) -> None:
    lock = db.scalar(select(TaskLockRecord).where(TaskLockRecord.task_id == task_id, TaskLockRecord.owner_id == owner_id))
    if lock:
        db.delete(lock)
        db.commit()
