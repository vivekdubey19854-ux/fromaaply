from __future__ import annotations

import pytest

import app.live_browser as live
from app.live_browser import LiveBrowserManager, LiveControl
from app.operational_policy import PauseReason


class FakeMouse:
    def __init__(self):
        self.calls = []

    async def move(self, x, y):
        self.calls.append(("move", x, y))

    async def down(self, button="left"):
        self.calls.append(("down", button))

    async def up(self, button="left"):
        self.calls.append(("up", button))

    async def wheel(self, dx, dy):
        self.calls.append(("wheel", dx, dy))


class FakeKeyboard:
    def __init__(self):
        self.calls = []

    async def down(self, key):
        self.calls.append(("down", key))

    async def up(self, key):
        self.calls.append(("up", key))

    async def press(self, key):
        self.calls.append(("press", key))


class FakeLocator:
    def __init__(self, body=""):
        self.body = body

    async def inner_text(self, timeout=1000):
        return self.body

    async def evaluate_all(self, script, needle=None):
        return False


class FakePage:
    def __init__(self, body=""):
        self.body = body
        self.mouse = FakeMouse()
        self.keyboard = FakeKeyboard()
        self.viewport_size = {"width": 1280, "height": 720}

    def locator(self, _selector):
        return FakeLocator(self.body)

    async def title(self):
        return "Demo"


class FakeWebSocket:
    def __init__(self):
        self.messages = []

    async def send_json(self, message):
        self.messages.append(message)


@pytest.mark.asyncio
async def test_live_token_is_one_time(monkeypatch):
    manager = LiveBrowserManager()
    monkeypatch.setattr(live, "get_session", lambda session_id, user_id: object())

    token, ttl = await manager.issue_token("u1", "s1")
    record = await manager.consume_token("s1", token)

    assert record.user_id == "u1"
    assert ttl > 0
    with pytest.raises(PermissionError):
        await manager.consume_token("s1", token)


@pytest.mark.asyncio
async def test_locked_session_rejects_remote_input(monkeypatch):
    manager = LiveBrowserManager()
    websocket = FakeWebSocket()
    manager._channels["s1"] = websocket
    manager._send_locks["s1"] = __import__("asyncio").Lock()
    manager._channel_users["s1"] = "u1"
    manager._controls["s1"] = LiveControl(control="locked", mode="ai")
    monkeypatch.setattr(live, "get_session", lambda session_id, user_id: object())

    await manager._handle_input("s1", {"type": "input.mouse", "event": "down", "x": 10, "y": 10})

    assert websocket.messages[-1] == {"type": "input.rejected", "reason": "control_locked"}


@pytest.mark.asyncio
async def test_human_mode_forwards_mouse_and_keyboard(monkeypatch):
    manager = LiveBrowserManager()
    websocket = FakeWebSocket()
    page = FakePage()
    session = type("Session", (), {"page": page})()
    manager._channels["s1"] = websocket
    manager._send_locks["s1"] = __import__("asyncio").Lock()
    manager._channel_users["s1"] = "u1"
    manager._controls["s1"] = LiveControl(control="unlocked", mode="human", paused=True, reason=PauseReason.CAPTCHA.value, resume_allowed=True)
    monkeypatch.setattr(live, "get_session", lambda session_id, user_id: session)

    await manager._handle_input("s1", {"type": "input.mouse", "event": "move", "x": 20, "y": 30})
    await manager._handle_input("s1", {"type": "input.mouse", "event": "down", "x": 20, "y": 30, "button": "left"})
    await manager._handle_input("s1", {"type": "input.key", "event": "press", "key": "A"})

    assert page.mouse.calls[:2] == [("move", 20.0, 30.0), ("down", "left")]
    assert page.keyboard.calls == [("press", "A")]


@pytest.mark.asyncio
async def test_resume_requires_completed_human_gate(monkeypatch):
    manager = LiveBrowserManager()
    websocket = FakeWebSocket()
    page = FakePage("CAPTCHA")
    session = type("Session", (), {"page": page})()
    manager._channels["s1"] = websocket
    manager._send_locks["s1"] = __import__("asyncio").Lock()
    manager._channel_users["s1"] = "u1"
    manager._controls["s1"] = LiveControl(control="unlocked", mode="human", paused=True, reason="captcha", resume_allowed=True)
    monkeypatch.setattr(live, "get_session", lambda session_id, user_id: session)
    page.locator = lambda _selector: type("Locator", (), {"evaluate_all": staticmethod(lambda *args: __import__("asyncio").sleep(0, result=False))})()

    await manager.resume_human("s1")

    assert websocket.messages[-1]["type"] == "resume.rejected"
    assert websocket.messages[-1]["reason"] == "human_gate_not_satisfied"
