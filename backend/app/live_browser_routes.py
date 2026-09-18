from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from app.auth import require_user_id
from app.browser_agent import get_session
from app.config import settings
from app.live_browser import live_manager

router = APIRouter(prefix="/v1/browser", tags=["live-browser"])


class AgentStateRequest(BaseModel):
    step: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=500)


@router.post("/sessions/{session_id}/live-token")
async def issue_live_token(session_id: str, request: Request, user_id: str = Depends(require_user_id)):
    if not settings.live_browser_enabled:
        raise HTTPException(status_code=404, detail="live browser streaming is disabled")
    try:
        token, ttl = await live_manager.issue_token(user_id, session_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="browser session not found") from exc
    proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip().lower()
    if settings.live_require_secure_transport and proto != "https":
        raise HTTPException(status_code=400, detail="live browser streaming requires HTTPS/WSS in this environment")
    websocket_scheme = "wss" if proto == "https" else "ws"
    host = request.headers.get("x-forwarded-host", request.headers.get("host", "127.0.0.1:8000")).split(",")[0].strip()
    ws_url = f"{websocket_scheme}://{host}/v1/browser/sessions/{session_id}/live?token={token}"
    return {"session_id": session_id, "live_token": token, "ws_url": ws_url, "expires_in": ttl}


@router.post("/sessions/{session_id}/live/agent-state")
async def publish_agent_state(session_id: str, payload: AgentStateRequest, user_id: str = Depends(require_user_id)):
    if not settings.live_browser_enabled:
        raise HTTPException(status_code=404, detail="live browser streaming is disabled")
    try:
        get_session(session_id, user_id)
        await live_manager.set_ai_state(session_id, payload.step, payload.message)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="browser session not found") from exc
    return {"status": "broadcast", "session_id": session_id, "control": "locked"}


@router.websocket("/sessions/{session_id}/live")
async def live_browser_socket(websocket: WebSocket, session_id: str, token: str):
    if not settings.live_browser_enabled:
        await websocket.close(code=1008, reason="live browser streaming is disabled")
        return
    if settings.live_require_secure_transport:
        proto = websocket.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
        if not proto:
            proto = getattr(websocket.url, "scheme", "").lower()
        if proto != "https":
            await websocket.close(code=1008, reason="HTTPS/WSS is required")
            return
    try:
        record = await live_manager.consume_token(session_id, token)
    except Exception:
        await websocket.close(code=1008, reason="invalid or expired live session token")
        return
    try:
        await live_manager.run(websocket, record)
    except WebSocketDisconnect:
        return
