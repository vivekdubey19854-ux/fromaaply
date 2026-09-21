import pytest

from app.task_service import TaskStateError, claim_task, create_task, transition_task


def test_task_creation_is_idempotent_and_owner_scoped(db_session):
    db = db_session
    first = create_task(db, user_id="u1", target_url="https://example.gov", idempotency_key="same")
    second = create_task(db, user_id="u1", target_url="https://example.gov", idempotency_key="same")
    assert first["task_id"] == second["task_id"]
    other = create_task(db, user_id="u2", target_url="https://example.gov", idempotency_key="same")
    assert other["task_id"] != first["task_id"]


def test_task_state_machine_rejects_illegal_transition(db_session):
    db = db_session
    task = create_task(db, user_id="u1")
    claimed = claim_task(db, task_id=task["task_id"], user_id="u1", owner_id="worker-1")
    assert claimed["state"] == "running"
    with pytest.raises(TaskStateError):
        transition_task(db, task_id=task["task_id"], user_id="u1", to_state="queued")


def test_task_transition_requires_owner_identity(db_session):
    db = db_session
    task = create_task(db, user_id="u1")
    with pytest.raises(Exception):
        transition_task(db, task_id=task["task_id"], user_id="u2", to_state="running")
