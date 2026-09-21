import json

from app.task_service import create_task
from app.task_worker import DurableTaskWorker, RedisTaskQueue


class FakeRedis:
    def __init__(self):
        self.queues = {}

    def lpush(self, name, value):
        self.queues.setdefault(name, []).insert(0, value)

    def brpop(self, name, timeout=1):
        values = self.queues.get(name, [])
        if not values:
            return None
        return name, values.pop()


def test_redis_queue_round_trip():
    client = FakeRedis()
    queue = RedisTaskQueue(client=client, queue_name="q", dead_letter_name="dead")
    queue.enqueue("t1", user_id="u1")
    assert queue.pop() == {"task_id": "t1", "user_id": "u1"}


def test_worker_checkpoint_and_success(db_session):
    task = create_task(db_session, user_id="u1")
    client = FakeRedis()
    queue = RedisTaskQueue(client=client, queue_name="q", dead_letter_name="dead")
    queue.enqueue(task["task_id"], user_id="u1")
    worker = DurableTaskWorker(queue=queue, session_factory=lambda: db_session, owner_id="worker-1")
    assert worker.process_once() is True
    db_session.expire_all()
    assert db_session.get(__import__("app.db_models", fromlist=["FormTaskRecord"]).FormTaskRecord, task["task_id"]).state == "completed"


def test_worker_failure_requeues_and_dead_letters_after_retry_limit(db_session, monkeypatch):
    task = create_task(db_session, user_id="u1")
    client = FakeRedis()
    queue = RedisTaskQueue(client=client, queue_name="q", dead_letter_name="dead")
    queue.enqueue(task["task_id"], user_id="u1")
    calls = {"count": 0}
    def fail_handler(_db, _payload, _checkpoint):
        calls["count"] += 1
        raise RuntimeError("browser crashed")
    monkeypatch.setattr("app.task_worker.settings.task_max_retries", 1)
    worker = DurableTaskWorker(queue=queue, session_factory=lambda: db_session, owner_id="worker-1", handler=fail_handler)
    assert worker.process_once() is False
    assert worker.process_once() is False
    assert calls["count"] == 2
    assert len(client.queues["dead"]) == 1
