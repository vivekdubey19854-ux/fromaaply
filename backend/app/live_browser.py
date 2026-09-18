from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from app.browser_agent import BrowserSafetyError, get_session
from app.config import settings
from app.database import SessionLocal
from app.operational_policy import PauseReason, classify_page_text
from app.verified_data_repository import VerifiedDataRepository
from app.verified_data_service import VerifiedDataResult, VerifiedDataService, VerifiedDataStatus


@dataclass(frozen=True)
class LiveToken:
    token_hash: str
    session_id: str
    user_id: str
    expires_at: float


@dataclass
class LiveControl:
    control: str = "locked"
    mode: str = "ai"
    paused: bool = False
    reason: str | None = None
    resume_allowed: bool = False


class LiveBrowserManager:
    """Owns authenticated live browser channels and enforces server-side control."""

    def __init__(self) -> None:
        self._tokens: dict[str, LiveToken] = {}
        self._channels: dict[str, WebSocket] = {}
        self._controls: dict[str, LiveControl] = {}
        self._send_locks: dict[str, asyncio.Lock] = {}
        self._channel_users: dict[str, str] = {}
        self._pending_verified_fields: dict[str, str] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    async def issue_token(self, user_id: str, session_id: str) -> tuple[str, int]:
        get_session(session_id, user_id)
        token = secrets.token_urlsafe(32)
        now = time.time()
        ttl = settings.live_token_ttl_seconds
        record = LiveToken(self._hash_token(token), session_id, user_id, now + ttl)
        async with self._lock:
            self._tokens[record.token_hash] = record
        return token, ttl

    async def consume_token(self, session_id: str, token: str) -> LiveToken:
        token_hash = self._hash_token(token)
        async with self._lock:
            record = self._tokens.pop(token_hash, None)
        if record is None or record.session_id != session_id or record.expires_at <= time.time():
            raise PermissionError("invalid or expired live session token")
        get_session(session_id, record.user_id)
        return record

    async def _send(self, session_id: str, message: dict[str, Any]) -> None:
        websocket = self._channels.get(session_id)
        if websocket is None:
            return
        lock = self._send_locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            try:
                await websocket.send_json(message)
            except Exception:
                await self.detach(session_id, websocket)

    async def _broadcast_control(self, session_id: str) -> None:
        control = self._controls.setdefault(session_id, LiveControl())
        await self._send(
            session_id,
            {
                "type": "control.changed",
                "control": control.control,
                "mode": control.mode,
                "paused": control.paused,
                "reason": control.reason,
                "resume_allowed": control.resume_allowed,
            },
        )

    async def set_ai_state(self, session_id: str, step: str, message: str) -> None:
        control = self._controls.setdefault(session_id, LiveControl())
        if not control.paused:
            control.control = "locked"
            control.mode = "ai"
        await self._send(
            session_id,
            {
                "type": "agent.state",
                "state": "paused" if control.paused else "running",
                "step": step,
                "message": message,
                "control": control.control,
            },
        )
        await self._broadcast_control(session_id)

    async def require_human_for_verified_data(
        self,
        session_id: str,
        field_key: str,
        result: VerifiedDataResult,
    ) -> None:
        """Fail closed and unlock human control when verification is unavailable."""
        if result.status == VerifiedDataStatus.VERIFIED:
            return
        control = self._controls.setdefault(session_id, LiveControl())
        self._pending_verified_fields[session_id] = field_key
        control.control = "unlocked"
        control.mode = "human"
        control.paused = True
        control.reason = f"verified_data_{result.status.lower()}"
        control.resume_allowed = True
        await self._send(
            session_id,
            {
                "type": "human.required",
                "state": "paused",
                "reason": control.reason,
                "control": "unlocked",
                "message": result.message or f"Human verification required for {field_key}.",
                "resume_allowed": True,
                "field_key": field_key,
            },
        )
        await self._broadcast_control(session_id)

    async def evaluate_policy(self, session_id: str) -> None:
        session = get_session(session_id, self._controls_user(session_id))
        page = session.page
        try:
            body = await page.locator("body").inner_text(timeout=1000)
        except Exception:
            body = ""
        try:
            title = await page.title()
        except Exception:
            title = ""
        decision = classify_page_text(f"{title}\n{body[:12000]}")
        control = self._controls.setdefault(session_id, LiveControl())
        if decision.pause:
            reason = decision.reason.value if decision.reason else "unknown"
            human_reasons = {PauseReason.CAPTCHA, PauseReason.OTP, PauseReason.LEGAL_DECLARATION, PauseReason.PAYMENT}
            desired_control = "unlocked" if decision.reason in human_reasons else "locked"
            desired_mode = "human" if desired_control == "unlocked" else "ai"
            desired_resume = decision.reason in {PauseReason.CAPTCHA, PauseReason.OTP}
            if control.paused and control.reason == reason and control.control == desired_control:
                return
            control.control = desired_control
            control.mode = desired_mode
            control.paused = True
            control.reason = reason
            control.resume_allowed = desired_resume
            await self._send(
                session_id,
                {
                    "type": "human.required",
                    "state": "paused",
                    "reason": reason,
                    "control": control.control,
                    "message": decision.message,
                    "resume_allowed": control.resume_allowed,
                },
            )
            await self._broadcast_control(session_id)

    def _controls_user(self, session_id: str) -> str:
        channel_user = self._channel_users.get(session_id)
        if channel_user:
            return channel_user
        for token in self._tokens.values():
            if token.session_id == session_id and token.expires_at > time.time():
                return token.user_id
        raise PermissionError("live session user context unavailable")

    async def attach(self, record: LiveToken, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            previous = self._channels.get(record.session_id)
            self._channels[record.session_id] = websocket
            self._channel_users[record.session_id] = record.user_id
            self._controls.setdefault(record.session_id, LiveControl())
            self._send_locks.setdefault(record.session_id, asyncio.Lock())
        if previous is not None and previous is not websocket:
            try:
                await previous.close(code=4001, reason="live session taken over")
            except Exception:
                pass
        await self._send(
            record.session_id,
            {
                "type": "session.ready",
                "version": 1,
                "session_id": record.session_id,
                "control": "locked",
                "mode": "ai",
                "state": "ai_running",
            },
        )

    async def detach(self, session_id: str, websocket: WebSocket | None = None) -> None:
        async with self._lock:
            current = self._channels.get(session_id)
            if websocket is not None and current is not websocket:
                return
            self._channels.pop(session_id, None)
            self._send_locks.pop(session_id, None)
            self._channel_users.pop(session_id, None)
            self._pending_verified_fields.pop(session_id, None)

    async def _handle_input(self, session_id: str, payload: dict[str, Any]) -> None:
        control = self._controls.setdefault(session_id, LiveControl())
        if control.control != "unlocked" or control.mode != "human":
            await self._send(session_id, {"type": "input.rejected", "reason": "control_locked"})
            return
        session = get_session(session_id, self._controls_user(session_id))
        page = session.page
        kind = payload.get("type")
        if kind == "input.mouse":
            event = str(payload.get("event", ""))
            x = float(payload.get("x", 0))
            y = float(payload.get("y", 0))
            if not (0 <= x <= 10000 and 0 <= y <= 10000):
                raise ValueError("mouse coordinates out of range")
            if event == "move":
                await page.mouse.move(x, y)
            elif event in {"down", "up"}:
                button = str(payload.get("button", "left"))
                if button not in {"left", "middle", "right"}:
                    raise ValueError("unsupported mouse button")
                if event == "down":
                    await page.mouse.down(button=button)
                else:
                    await page.mouse.up(button=button)
            else:
                raise ValueError("unsupported mouse event")
        elif kind == "input.wheel":
            dx = max(-5000, min(5000, float(payload.get("delta_x", 0))))
            dy = max(-5000, min(5000, float(payload.get("delta_y", 0))))
            await page.mouse.wheel(dx, dy)
        elif kind == "input.key":
            event = str(payload.get("event", ""))
            key = str(payload.get("key", ""))
            if not key or len(key) > 64:
                raise ValueError("invalid keyboard key")
            if event == "down":
                await page.keyboard.down(key)
            elif event == "up":
                await page.keyboard.up(key)
            elif event == "press":
                await page.keyboard.press(key)
            else:
                raise ValueError("unsupported keyboard event")
        else:
            raise ValueError("unsupported input message")

    async def _verified_data_ready(self, session_id: str) -> bool:
        field_key = self._pending_verified_fields.get(session_id)
        if not field_key:
            return False
        db = SessionLocal()
        try:
            gateway = VerifiedDataService(VerifiedDataRepository(db))
            result = gateway.get_requested_field(user_id=self._controls_user(session_id), requested_field=field_key)
            return result.status == "verified" and result.value is not None
        finally:
            db.close()

    async def resume_human(self, session_id: str) -> None:
        control = self._controls.setdefault(session_id, LiveControl())
        if not control.paused or not control.resume_allowed:
            await self._send(session_id, {"type": "resume.rejected", "reason": "resume_not_allowed"})
            return
        user_id = self._controls_user(session_id)
        session = get_session(session_id, user_id)
        page = session.page
        reason = str(control.reason)
        if reason.startswith("verified_data_"):
            satisfied = await self._verified_data_ready(session_id)
            message = "Verified data is still unavailable. Resolve it and retry." if not satisfied else "Verified data is ready. AI resumed."
        else:
            satisfied = bool(
                await page.locator("input, textarea").evaluate_all(
                    """(els,needle)=>els.some(el=>{const hay=[el.name,el.id,el.placeholder,el.getAttribute('aria-label'),el.autocomplete].filter(Boolean).join(' ').toLowerCase();return hay.includes(needle)&&String(el.value||'').trim().length>0})""",
                    "captcha" if reason == PauseReason.CAPTCHA.value else "otp",
                )
            )
            message = "Please complete the CAPTCHA/OTP in the live browser before resuming." if not satisfied else "Human verification completed. AI resumed."
        if not satisfied:
            await self._send(session_id, {"type": "resume.rejected", "reason": "human_gate_not_satisfied", "message": message})
            return
        control.control = "locked"
        control.mode = "ai"
        control.paused = False
        control.reason = None
        control.resume_allowed = False
        self._pending_verified_fields.pop(session_id, None)
        await self._send(session_id, {"type": "agent.state", "state": "running", "step": "resuming", "message": message, "control": "locked"})
        await self._broadcast_control(session_id)

    async def run(self, websocket: WebSocket, record: LiveToken) -> None:
        await self.attach(record, websocket)
        frame_task = asyncio.create_task(self._frame_loop(record.session_id))
        try:
            while True:
                raw = await websocket.receive_text()
                if len(raw.encode("utf-8")) > settings.live_max_message_bytes:
                    await self._send(record.session_id, {"type": "error", "code": "message_too_large"})
                    continue
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    await self._send(record.session_id, {"type": "error", "code": "invalid_json"})
                    continue
                message_type = payload.get("type")
                if message_type == "ping":
                    await self._send(record.session_id, {"type": "pong", "timestamp": int(time.time() * 1000)})
                elif message_type == "human.resume":
                    await self.resume_human(record.session_id)
                elif message_type in {"input.mouse", "input.wheel", "input.key"}:
                    try:
                        await self._handle_input(record.session_id, payload)
                    except (BrowserSafetyError, ValueError) as exc:
                        await self._send(record.session_id, {"type": "input.rejected", "reason": str(exc)})
                else:
                    await self._send(record.session_id, {"type": "error", "code": "unsupported_message"})
        except (WebSocketDisconnect, PermissionError):
            pass
        finally:
            frame_task.cancel()
            await asyncio.gather(frame_task, return_exceptions=True)
            await self.detach(record.session_id, websocket)

    async def _frame_loop(self, session_id: str) -> None:
        policy_interval = max(250, settings.live_policy_check_interval_ms) / 1000
        frame_interval = max(50, settings.live_frame_interval_ms) / 1000
        next_policy = 0.0
        seq = 0
        while session_id in self._channels:
            user_id = self._controls_user(session_id)
            session = get_session(session_id, user_id)
            now = time.monotonic()
            if now >= next_policy:
                try:
                    await self.evaluate_policy(session_id)
                except Exception:
                    pass
                next_policy = now + policy_interval
            image = await session.page.screenshot(type="jpeg", quality=settings.live_jpeg_quality, full_page=False)
            seq += 1
            control = self._controls.setdefault(session_id, LiveControl())
            await self._send(
                session_id,
                {
                    "type": "browser.frame",
                    "seq": seq,
                    "timestamp": int(time.time() * 1000),
                    "width": session.page.viewport_size["width"] if session.page.viewport_size else None,
                    "height": session.page.viewport_size["height"] if session.page.viewport_size else None,
                    "encoding": "jpeg",
                    "quality": settings.live_jpeg_quality,
                    "data": base64.b64encode(image).decode("ascii"),
                    "control": control.control,
                },
            )
            await asyncio.sleep(frame_interval)


live_manager = LiveBrowserManager()
