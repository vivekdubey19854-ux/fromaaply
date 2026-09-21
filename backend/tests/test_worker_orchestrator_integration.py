import asyncio
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.browser_agent import close_all_sessions
from app.config import settings
from app.db_models import EducationRecord, FormTaskRecord, ProfileRecord
from app.storage import PrivateStorage
from app.task_service import create_task, requeue_paused_task
from app.task_worker import DurableTaskWorker, RedisTaskQueue


class DemoFormHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'<html><head><title>Demo Application</title></head><body><form><label>Qualification<input name="qualification"></label><button type="button">Continue</button></form></body></html>'
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


class FakeRedis:
    def __init__(self):
        self.queues = {}

    def lpush(self, name, value):
        self.queues.setdefault(name, []).insert(0, value)

    def brpop(self, name, timeout=1):
        values = self.queues.get(name, [])
        return (name, values.pop()) if values else None


def test_worker_orchestrator_real_browser_pause_checkpoint(db_session, tmp_path, monkeypatch):
    asyncio.run(close_all_sessions())
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    server = ThreadingHTTPServer(("127.0.0.1", port), DemoFormHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "browser_allow_local_demo_target", True)
    monkeypatch.setattr(settings, "browser_demo_target_port", port)
    storage = PrivateStorage(str(tmp_path))
    storage.save_json("user-1", "knowledge/index.json", {"chunks": []})
    db_session.add(ProfileRecord(user_id="user-1", full_name="Verified Applicant", email="applicant@example.com"))
    db_session.add(EducationRecord(user_id="user-1", qualification="Graduate", institution="Example University"))
    db_session.commit()
    workflow_id = "wf-real-browser"
    target_url = f"http://127.0.0.1:{port}"
    storage.save_json("user-1", f"workflows/{workflow_id}.json", {"workflow_id": workflow_id, "user_id": "user-1", "instruction": "Formwise demo form", "state": "documents_ready", "research": {"apply_url": target_url}, "session_id": None, "history": []})
    task = create_task(db_session, user_id="user-1", workflow_id=workflow_id, target_url=target_url)
    client = FakeRedis()
    queue = RedisTaskQueue(client=client, queue_name="q", dead_letter_name="dead")
    queue.enqueue(task["task_id"], user_id="user-1")
    worker = DurableTaskWorker(queue=queue, session_factory=lambda: db_session, owner_id="browser-worker-1")
    try:
        assert worker.process_once() is False  # safe pause at inspection/approval boundary
        db_session.expire_all()
        saved = db_session.get(FormTaskRecord, task["task_id"])
        assert saved.state == "paused"
        assert saved.current_step in {"browser_opened", "form_inspected", "form_filled"}
        assert saved.browser_session_id
        assert saved.resume_reference
        assert client.queues.get("q", []) == []
        workflow = storage.read_json("user-1", f"workflows/{workflow_id}.json")
        assert workflow["state"] == "final_review"
        worker.shutdown()  # simulate browser-worker crash; persisted workflow remains
        requeue_paused_task(db_session, task_id=task["task_id"], user_id="user-1")
        queue.enqueue(task["task_id"], user_id="user-1")
        restarted_worker = DurableTaskWorker(queue=queue, session_factory=lambda: db_session, owner_id="browser-worker-2")
        assert restarted_worker.process_once() is False
        db_session.expire_all()
        resumed = db_session.get(FormTaskRecord, task["task_id"])
        assert resumed.state == "paused"
        assert resumed.current_step == "final_review"
        restarted_worker.shutdown()
    finally:
        worker.shutdown()
        server.shutdown()
        server.server_close()
