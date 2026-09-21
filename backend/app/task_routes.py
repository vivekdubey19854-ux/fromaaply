from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from redis.exceptions import RedisError
from sqlalchemy.orm import Session

from .auth import require_user_id
from .database import get_db
from .task_service import TaskNotFound, TaskStateError, claim_task, create_task, get_task, heartbeat_task, list_tasks, release_task_lock, requeue_paused_task, transition_task
from .task_worker import RedisTaskQueue

router = APIRouter(prefix="/v1/tasks", tags=["durable-tasks"])


class CreateTaskRequest(BaseModel):
    target_url: str | None = Field(default=None, max_length=500)
    website_id: str | None = Field(default=None, max_length=36)
    workflow_id: str | None = Field(default=None, max_length=36)
    idempotency_key: str | None = Field(default=None, max_length=160)


class TransitionTaskRequest(BaseModel):
    owner_id: str = Field(min_length=1, max_length=120)
    state: str = Field(pattern="^(running|paused|completed|failed|cancelled|queued)$")
    step: str | None = Field(default=None, max_length=100)
    error_code: str | None = Field(default=None, max_length=80)
    error_message: str | None = Field(default=None, max_length=1000)
    resume_reference: str | None = Field(default=None, max_length=200)


class ClaimTaskRequest(BaseModel):
    owner_id: str = Field(min_length=1, max_length=120)
    lease_seconds: int = Field(default=60, ge=10, le=900)


@router.post("", status_code=201)
def create_task_route(body: CreateTaskRequest, db: Session = Depends(get_db), user_id: str = Depends(require_user_id)):
    return create_task(db, user_id=user_id, target_url=body.target_url, website_id=body.website_id, workflow_id=body.workflow_id, idempotency_key=body.idempotency_key)


@router.get("")
def list_task_route(limit: int = 50, db: Session = Depends(get_db), user_id: str = Depends(require_user_id)):
    return list_tasks(db, user_id, max(1, min(limit, 100)))


@router.get("/{task_id}")
def get_task_route(task_id: str, db: Session = Depends(get_db), user_id: str = Depends(require_user_id)):
    try:
        task = get_task(db, task_id, user_id)
        return {"task_id": task.task_id, "state": task.state, "user_id": task.user_id, "workflow_id": task.workflow_id, "current_step": task.current_step, "target_url": task.target_url, "browser_session_id": task.browser_session_id, "retry_count": task.retry_count}
    except TaskNotFound as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc


@router.post("/{task_id}/claim")
def claim_task_route(task_id: str, body: ClaimTaskRequest, db: Session = Depends(get_db), user_id: str = Depends(require_user_id)):
    try:
        return claim_task(db, task_id=task_id, user_id=user_id, owner_id=body.owner_id, lease_seconds=body.lease_seconds)
    except TaskNotFound as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    except TaskStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{task_id}/transition")
def transition_task_route(task_id: str, body: TransitionTaskRequest, db: Session = Depends(get_db), user_id: str = Depends(require_user_id)):
    try:
        return transition_task(db, task_id=task_id, user_id=user_id, owner_id=body.owner_id, to_state=body.state, step=body.step, error_code=body.error_code, error_message=body.error_message, resume_reference=body.resume_reference)
    except TaskNotFound as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    except TaskStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{task_id}/enqueue")
def enqueue_task_route(task_id: str, db: Session = Depends(get_db), user_id: str = Depends(require_user_id)):
    try:
        task = get_task(db, task_id, user_id)
        RedisTaskQueue().enqueue(task.task_id, user_id=user_id)
        return {"task_id": task_id, "queued": True}
    except TaskNotFound as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="task queue is unavailable") from exc


@router.post("/{task_id}/human-resume")
def human_resume_task_route(task_id: str, db: Session = Depends(get_db), user_id: str = Depends(require_user_id)):
    try:
        task = requeue_paused_task(db, task_id=task_id, user_id=user_id)
        RedisTaskQueue().enqueue(task_id, user_id=user_id)
        return {"task_id": task_id, "queued": True, "human_action_recorded": True}
    except TaskNotFound as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    except TaskStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="task queue is unavailable") from exc


@router.post("/{task_id}/heartbeat")
def heartbeat_task_route(task_id: str, body: ClaimTaskRequest, db: Session = Depends(get_db), user_id: str = Depends(require_user_id)):
    try:
        return heartbeat_task(db, task_id=task_id, user_id=user_id, owner_id=body.owner_id, lease_seconds=body.lease_seconds)
    except TaskNotFound as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    except TaskStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/{task_id}/lock", status_code=204)
def release_task_lock_route(task_id: str, owner_id: str, db: Session = Depends(get_db), user_id: str = Depends(require_user_id)):
    try:
        get_task(db, task_id, user_id)
        release_task_lock(db, task_id=task_id, owner_id=owner_id)
    except TaskNotFound as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
