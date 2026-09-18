from __future__ import annotations

import re
import secrets

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_user_id
from app.browser_agent import (
    BrowserSafetyError,
    BrowserSessionNotFound,
    close_session,
    create_session,
    fill_control,
    get_session,
    inspect_session,
    navigate_session,
    screenshot_session,
)
from app.browser_api import (
    BrowserInspectResponse,
    BrowserNavigateRequest,
    BrowserNavigateResponse,
    BrowserScreenshotResponse,
    BrowserSessionResponse,
    BrowserStartRequest,
)
from app.config import settings
from app.database import get_db
from app.db_models import AuditLogRecord
from app.storage import PrivateStorage

router = APIRouter(prefix="/v1/browser", tags=["browser-agent"])
storage = PrivateStorage(settings.storage_root)


class HumanVerificationRequest(BaseModel):
    kind: str = Field(pattern="^(otp|captcha)$")
    value: str = Field(min_length=1, max_length=32)


def audit(db: Session, user_id: str, action: str, resource_id: str | None = None) -> None:
    db.add(AuditLogRecord(user_id=user_id, action=action, resource_type="browser_session", resource_id=resource_id))
    db.commit()


def _human_control(inspection: dict, kind: str) -> int | None:
    for control in inspection.get("controls", []):
        hay = " ".join(str(control.get(k) or "") for k in ("name", "id", "placeholder", "ariaLabel", "autocomplete", "text")).lower()
        if kind == "captcha" and not control.get("value") and any(x in hay for x in ("captcha", "recaptcha", "hcaptcha")):
            return int(control["index"])
        if kind == "otp" and not control.get("value") and ("otp" in hay or "one time password" in hay or control.get("autocomplete") in {"one-time-code", "one-time-password"}):
            return int(control["index"])
    return None


@router.post("/sessions", response_model=BrowserSessionResponse, status_code=201)
async def start_browser(payload: BrowserStartRequest, user_id: str = Depends(require_user_id), db: Session = Depends(get_db)):
    try:
        session = await create_session(user_id, payload.url)
        inspection = await inspect_session(session)
    except BrowserSafetyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"browser could not open target: {exc}") from exc
    audit(db, user_id, "browser.session_started", session.session_id)
    return BrowserSessionResponse(
        session_id=session.session_id,
        url=inspection["url"],
        title=inspection["title"],
        status="active",
        submission_allowed=False,
        warnings=inspection["warnings"],
    )


@router.post("/sessions/{session_id}/navigate", response_model=BrowserNavigateResponse)
async def navigate_browser(session_id: str, payload: BrowserNavigateRequest, user_id: str = Depends(require_user_id), db: Session = Depends(get_db)):
    try:
        session = get_session(session_id, user_id)
        result = await navigate_session(session, payload.url)
    except BrowserSessionNotFound as exc:
        raise HTTPException(status_code=404, detail="browser session not found") from exc
    except BrowserSafetyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"navigation failed: {exc}") from exc
    audit(db, user_id, "browser.navigated", session_id)
    return result


@router.get("/sessions/{session_id}/inspect", response_model=BrowserInspectResponse)
async def inspect_browser(session_id: str, user_id: str = Depends(require_user_id), db: Session = Depends(get_db)):
    try:
        session = get_session(session_id, user_id)
        result = await inspect_session(session)
    except BrowserSessionNotFound as exc:
        raise HTTPException(status_code=404, detail="browser session not found") from exc
    except BrowserSafetyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"inspection failed: {exc}") from exc
    audit(db, user_id, "browser.page_inspected", session_id)
    return BrowserInspectResponse(session_id=session_id, **result)


@router.post("/sessions/{session_id}/human")
async def human_verification(session_id: str, payload: HumanVerificationRequest, user_id: str = Depends(require_user_id), db: Session = Depends(get_db)):
    if payload.kind == "otp" and not re.fullmatch(r"\d{4,8}", payload.value):
        raise HTTPException(status_code=400, detail="OTP must be 4-8 digits")
    if payload.kind == "captcha" and not re.fullmatch(r"[A-Za-z0-9 ]{1,32}", payload.value):
        raise HTTPException(status_code=400, detail="invalid CAPTCHA input")
    try:
        session = get_session(session_id, user_id)
        inspection = await inspect_session(session)
        index = _human_control(inspection, payload.kind)
        if index is None:
            raise HTTPException(status_code=409, detail=f"{payload.kind} field is not awaiting human input")
        await fill_control(session, index, payload.value)
        screenshot = await screenshot_session(session)
        key = f"browser/{session_id}/human-{secrets.token_hex(8)}.png"
        storage.save(user_id, key, screenshot)
        audit(db, user_id, f"browser.{payload.kind}_entered_by_user", session_id)
        return {"status": "accepted", "kind": payload.kind, "field_index": index, "screenshot_key": key, "submission_allowed": False}
    except BrowserSessionNotFound as exc:
        raise HTTPException(status_code=404, detail="browser session not found") from exc
    except BrowserSafetyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/sessions/{session_id}/screenshot", response_model=BrowserScreenshotResponse)
async def screenshot_browser(session_id: str, user_id: str = Depends(require_user_id), db: Session = Depends(get_db)):
    try:
        session = get_session(session_id, user_id)
        data = await screenshot_session(session)
    except BrowserSessionNotFound as exc:
        raise HTTPException(status_code=404, detail="browser session not found") from exc
    except BrowserSafetyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"screenshot failed: {exc}") from exc
    storage_key = f"browser/{session_id}/{secrets.token_hex(8)}.png"
    storage.save(user_id, storage_key, data)
    audit(db, user_id, "browser.screenshot_created", session_id)
    return BrowserScreenshotResponse(session_id=session_id, content_type="image/png", storage_key=storage_key, size_bytes=len(data))


@router.delete("/sessions/{session_id}")
async def stop_browser(session_id: str, user_id: str = Depends(require_user_id), db: Session = Depends(get_db)):
    try:
        await close_session(session_id, user_id)
    except BrowserSessionNotFound as exc:
        raise HTTPException(status_code=404, detail="browser session not found") from exc
    audit(db, user_id, "browser.session_stopped", session_id)
    return {"stopped": True}
