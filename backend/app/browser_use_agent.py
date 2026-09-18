from __future__ import annotations

import asyncio
import os
from typing import Any
from urllib.parse import urlparse

from app.database import SessionLocal
from app.form_mapping import FIELD_ALIASES
from app.operational_policy import classify_page_text
from app.verified_data_repository import VerifiedDataRepository
from app.verified_data_service import DataGatewayResult, VerifiedDataResult, VerifiedDataService


class BrowserUseUnavailable(RuntimeError):
    pass


class BrowserUseSafetyError(RuntimeError):
    pass


def normalize_agent_field_request(requested_field: str) -> str:
    """Validate a single canonical field request; no profile/wildcard access."""
    if not isinstance(requested_field, str):
        raise BrowserUseSafetyError("requested field must be a string")
    field = requested_field.strip().lower()
    if field not in FIELD_ALIASES or field in {"profile", "all", "*"}:
        raise BrowserUseSafetyError("browser agent requested an unsupported field")
    return field


async def request_verified_field(
    user_id: str,
    field_key: str,
    *,
    session_id: str | None = None,
) -> VerifiedDataResult:
    """Read exactly one approved field from provenance-backed verified data."""
    field_key = normalize_agent_field_request(field_key)
    db = SessionLocal()
    try:
        gateway = VerifiedDataService(VerifiedDataRepository(db))
        result: DataGatewayResult = gateway.get_requested_field(
            user_id=user_id,
            requested_field=field_key,
        )
    finally:
        db.close()

    if result.status == "verified":
        legacy_result = VerifiedDataResult(
            status="VERIFIED",
            field_key=field_key,
            value=result.value,
            source=result.source_type,
            message=None,
        )
    elif result.status == "conflict":
        legacy_result = VerifiedDataResult(
            status="CONFLICT",
            field_key=field_key,
            value=None,
            source=None,
            message=result.reason or "verified data conflict; human confirmation required",
        )
    elif result.status == "invalid_field":
        legacy_result = VerifiedDataResult(
            status="INVALID_FIELD",
            field_key=field_key,
            value=None,
            source=None,
            message=result.reason or "field is not approved",
        )
    else:
        legacy_result = VerifiedDataResult(
            status="NOT_FOUND",
            field_key=field_key,
            value=None,
            source=None,
            message=result.reason or "no verified value available",
        )

    if not legacy_result.usable and session_id:
        from app.live_browser import live_manager
        await live_manager.require_human_for_verified_data(
            session_id,
            field_key,
            legacy_result,
        )
    return legacy_result


def _validate_allowed_url(allowed_url: str) -> str:
    parsed = urlparse(allowed_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise BrowserUseSafetyError("approved URL must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise BrowserUseSafetyError("approved URL cannot contain embedded credentials")
    return allowed_url.strip()


async def run_browser_use_task(
    task: str,
    *,
    allowed_url: str | None = None,
    mode: str = "inspect",
    user_id: str | None = None,
    session_id: str | None = None,
    requested_field: str | None = None,
) -> dict[str, Any]:
    """Semantic Browser Use observer behind Formwise safety controls."""
    if not task or len(task) > 4000:
        raise ValueError("task must be non-empty and <= 4000 characters")
    if mode != "inspect":
        raise BrowserUseSafetyError("only semantic inspection mode is enabled")
    if not allowed_url:
        raise ValueError("allowed_url is required for Browser Use tasks")

    canonical_field = None
    if requested_field:
        if not user_id:
            raise ValueError("user_id is required when requested_field is supplied")
        canonical_field = normalize_agent_field_request(requested_field)
        verified = await request_verified_field(
            user_id,
            canonical_field,
            session_id=session_id,
        )
        if not verified.usable:
            return {
                "status": "paused",
                "reason": verified.status.lower(),
                "message": verified.message,
                "requested_field": canonical_field,
            }

    safe_url = _validate_allowed_url(allowed_url)
    approved_host = urlparse(safe_url).hostname.lower()

    if os.getenv("FORMWISE_BROWSER_USE_ENABLED", "false").lower() != "true":
        raise BrowserUseUnavailable("Browser Use adapter is disabled")

    try:
        from browser_use import Agent, ChatOpenAI
    except ImportError as exc:  # pragma: no cover
        raise BrowserUseUnavailable("browser-use is not installed") from exc

    model = os.getenv("FORMWISE_BROWSER_USE_MODEL", "gpt-5.6-luna")
    llm = ChatOpenAI(model=model)
    constrained_task = (
        f"Inspect only this approved website: {safe_url}. Stay on the same hostname ({approved_host}). "
        "Semantic inspection only: do NOT fill, click, upload, submit, or modify data. "
        "Do NOT solve or bypass CAPTCHA/reCAPTCHA/hCaptcha or anti-bot controls. "
        "Do NOT enter or handle OTP/verification codes. Do NOT accept legal declarations. "
        "Do NOT make payments. Do NOT click final submission or confirmation buttons. "
        "Report page title, current URL, visible form sections, field labels/names/types, "
        "required fields, verification gates, and obvious intermediate navigation steps. "
        "Stop immediately when a restricted gate appears. Do not follow advertisements "
        "or unrelated external links.\n\nTask:\n" + task
    )
    agent = Agent(task=constrained_task, llm=llm)
    history = await agent.run()
    result = history.final_result()
    decision = classify_page_text(result)
    response: dict[str, Any] = {
        "status": "paused" if not decision.allowed else "completed",
        "mode": "inspect",
        "result": result,
        "model": model,
    }
    if canonical_field:
        response["requested_field"] = canonical_field
        response["data_gateway"] = "VerifiedDataService"
    if not decision.allowed:
        response["reason"] = decision.reason.value if decision.reason else None
        response["message"] = decision.message
    return response


def run_browser_use_task_sync(
    task: str,
    *,
    allowed_url: str | None = None,
    mode: str = "inspect",
    user_id: str | None = None,
    session_id: str | None = None,
    requested_field: str | None = None,
) -> dict[str, Any]:
    return asyncio.run(
        run_browser_use_task(
            task,
            allowed_url=allowed_url,
            mode=mode,
            user_id=user_id,
            session_id=session_id,
            requested_field=requested_field,
        )
    )
