from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .auth import require_user_id
from .config import settings
from .credential_crypto import encrypt_admin_api_key
from .database import get_db
from .payment_service import PaymentService
from .website_health_service import WebsiteHealthService
from .ai_provider_adapter import PROVIDER_CATALOG

router = APIRouter(prefix="/v1/admin", tags=["super-admin"])


class AdminContext:
    def __init__(self, user_id: str):
        self.user_id = user_id


def require_system_admin(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> AdminContext:
    """Require a verified JWT and an authoritative DB-level system-admin decision."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="authentication required")

    token = authorization[7:].strip()
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "exp"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="invalid authentication token") from exc

    user_id = str(claims.get("sub", ""))
    if not user_id or len(user_id) > 128:
        raise HTTPException(status_code=401, detail="invalid authenticated user")

    if db.bind is None or db.bind.dialect.name != "postgresql":
        raise HTTPException(status_code=403, detail="system admin privileges required")

    claims_json = json.dumps(claims, separators=(",", ":"), ensure_ascii=True)
    try:
        db.execute(
            text("select set_config('request.jwt.claims', :claims, true)"),
            {"claims": claims_json},
        )
        is_admin = bool(db.execute(text("select public.is_system_admin()")).scalar())
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail="system admin privileges required") from exc

    if not is_admin:
        db.rollback()
        raise HTTPException(status_code=403, detail="system admin privileges required")

    return AdminContext(user_id)


class AdminKeyUpdateRequest(BaseModel):
    provider_name: str = Field(min_length=1, max_length=100)
    api_key: str = Field(min_length=1, max_length=8192)

    @field_validator("provider_name")
    @classmethod
    def normalize_provider_name(cls, value: str) -> str:
        value = value.strip().lower()
        if not value:
            raise ValueError("provider_name is required")
        return value

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("api_key is required")
        return value


@router.post("/keys/update")
def update_admin_api_key(
    body: AdminKeyUpdateRequest,
    db: Session = Depends(get_db),
    admin: AdminContext = Depends(require_system_admin),
) -> dict[str, Any]:
    ciphertext = encrypt_admin_api_key(body.api_key)

    try:
        with db.begin():
            existing = db.execute(
                text(
                    "select provider_name from admin_api_keys "
                    "where provider_name = :provider_name "
                    "for update"
                ),
                {"provider_name": body.provider_name},
            ).first()
            if existing:
                db.execute(
                    text(
                        "update admin_api_keys "
                        "set api_key_encrypted = :ciphertext, is_active = true, updated_at = now() "
                        "where provider_name = :provider_name"
                    ),
                    {"ciphertext": ciphertext, "provider_name": body.provider_name},
                )
            else:
                db.execute(
                    text(
                        "insert into admin_api_keys "
                        "(provider_name, api_key_encrypted, is_active, updated_at) "
                        "values (:provider_name, :ciphertext, true, now())"
                    ),
                    {"provider_name": body.provider_name, "ciphertext": ciphertext},
                )

            db.execute(
                text(
                    "insert into audit_logs "
                    "(id, user_id, action, resource_type, resource_id, created_at, details) "
                    "values (gen_random_uuid()::text, :user_id, :action, :resource_type, "
                    ":resource_id, now(), :details)"
                ),
                {
                    "user_id": admin.user_id,
                    "action": "ADMIN_API_KEY_UPDATED",
                    "resource_type": "admin_api_key",
                    "resource_id": body.provider_name,
                    "details": json.dumps({"provider_name": body.provider_name, "secret_written": True}),
                },
            )
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="administrative key update failed") from exc

    return {"status": "updated", "provider_name": body.provider_name}


class PricingConfigRequest(BaseModel):
    credits_per_currency_unit: Decimal = Field(gt=Decimal("0"), max_digits=20, decimal_places=6)
    default_form_fill_cost_credits: Decimal = Field(gt=Decimal("0"), max_digits=20, decimal_places=6)
    currency_credit_ratios: dict[str, Decimal] = Field(min_length=1)

    @field_validator("currency_credit_ratios")
    @classmethod
    def validate_ratios(cls, value: dict[str, Decimal]) -> dict[str, Decimal]:
        normalized: dict[str, Decimal] = {}
        for currency, ratio in value.items():
            code = currency.strip().upper()
            if len(code) != 3 or not code.isalpha():
                raise ValueError("currency codes must be three-letter ISO-style values")
            if ratio <= 0:
                raise ValueError("currency credit ratios must be positive")
            normalized[code] = ratio
        if not normalized:
            raise ValueError("currency_credit_ratios is required")
        return normalized


@router.post("/pricing/config")
def update_pricing_config(
    body: PricingConfigRequest,
    db: Session = Depends(get_db),
    admin: AdminContext = Depends(require_system_admin),
) -> dict[str, Any]:
    ratios_json = json.dumps(
        {key: str(value) for key, value in body.currency_credit_ratios.items()},
        sort_keys=True,
        separators=(",", ":"),
    )

    try:
        with db.begin():
            db.execute(
                text(
                    "insert into admin_pricing_config "
                    "(config_id, credits_per_currency_unit, default_form_fill_cost_credits, "
                    "currency_credit_ratios, updated_by, updated_at) "
                    "values (1, :credits_per_currency_unit, :default_form_fill_cost_credits, "
                    ":currency_credit_ratios, :updated_by, now()) "
                    "on conflict (config_id) do update set "
                    "credits_per_currency_unit = excluded.credits_per_currency_unit, "
                    "default_form_fill_cost_credits = excluded.default_form_fill_cost_credits, "
                    "currency_credit_ratios = excluded.currency_credit_ratios, "
                    "updated_by = excluded.updated_by, updated_at = now()"
                ),
                {
                    "credits_per_currency_unit": body.credits_per_currency_unit,
                    "default_form_fill_cost_credits": body.default_form_fill_cost_credits,
                    "currency_credit_ratios": ratios_json,
                    "updated_by": admin.user_id,
                },
            )
            db.execute(
                text(
                    "insert into audit_logs "
                    "(id, user_id, action, resource_type, resource_id, created_at, details) "
                    "values (gen_random_uuid()::text, :user_id, :action, :resource_type, "
                    ":resource_id, now(), :details)"
                ),
                {
                    "user_id": admin.user_id,
                    "action": "ADMIN_PRICING_CONFIG_UPDATED",
                    "resource_type": "pricing_config",
                    "resource_id": "1",
                    "details": json.dumps(
                        {
                            "credits_per_currency_unit": str(body.credits_per_currency_unit),
                            "default_form_fill_cost_credits": str(body.default_form_fill_cost_credits),
                            "currency_credit_ratios": {k: str(v) for k, v in body.currency_credit_ratios.items()},
                        },
                        sort_keys=True,
                    ),
                },
            )
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="pricing configuration update failed") from exc

    return {
        "status": "updated",
        "credits_per_currency_unit": str(body.credits_per_currency_unit),
        "default_form_fill_cost_credits": str(body.default_form_fill_cost_credits),
        "currency_credit_ratios": {k: str(v) for k, v in body.currency_credit_ratios.items()},
    }


class CouponConfigRequest(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    discount_type: str = Field(pattern="^(fixed_amount|percentage|free_credits)$")
    discount_value: Decimal = Field(ge=Decimal("0"), max_digits=20, decimal_places=6)
    max_uses: int | None = Field(default=None, gt=0)
    expiry_date: str | None = None
    is_active: bool = True

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        value = value.strip().upper()
        if not value:
            raise ValueError("code is required")
        return value


@router.post("/coupons")
def upsert_admin_coupon(
    body: CouponConfigRequest,
    db: Session = Depends(get_db),
    admin: AdminContext = Depends(require_system_admin),
) -> dict[str, Any]:
    try:
        with db.begin():
            existing = db.execute(
                text("select coupon_id from coupons where code = :code for update"),
                {"code": body.code},
            ).scalar()
            params = {
                "code": body.code,
                "discount_type": body.discount_type,
                "discount_value": body.discount_value,
                "max_uses": body.max_uses,
                "expiry_date": body.expiry_date,
                "is_active": body.is_active,
            }
            if existing:
                db.execute(
                    text(
                        "update coupons set discount_type=:discount_type, discount_value=:discount_value, "
                        "max_uses=:max_uses, expiry_date=:expiry_date, is_active=:is_active "
                        "where code=:code"
                    ),
                    params,
                )
                coupon_id = str(existing)
                action = "ADMIN_COUPON_UPDATED"
            else:
                coupon_id = str(
                    db.execute(
                        text(
                            "insert into coupons "
                            "(code, discount_type, discount_value, max_uses, expiry_date, is_active) "
                            "values (:code, :discount_type, :discount_value, :max_uses, :expiry_date, :is_active) "
                            "returning coupon_id"
                        ),
                        params,
                    ).scalar()
                )
                action = "ADMIN_COUPON_CREATED"

            db.execute(
                text(
                    "insert into audit_logs "
                    "(id, user_id, action, resource_type, resource_id, created_at, details) "
                    "values (gen_random_uuid()::text, :user_id, :action, :resource_type, "
                    ":resource_id, now(), :details)"
                ),
                {
                    "user_id": admin.user_id,
                    "action": action,
                    "resource_type": "coupon",
                    "resource_id": coupon_id,
                    "details": json.dumps({"code": body.code, "is_active": body.is_active}, sort_keys=True),
                },
            )
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="coupon configuration update failed") from exc

    return {"status": "updated", "coupon_id": coupon_id, "code": body.code, "is_active": body.is_active}


# Kept for compatibility with future admin-only endpoints that need authenticated identity
# in addition to the system-admin gate.
admin_user_dependency = require_user_id


class WebsiteRegistryRequest(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    category: str = Field(min_length=2, max_length=50)
    base_url: str = Field(min_length=8, max_length=500)
    allowed_domains: list[str] = Field(default_factory=list, max_length=20)
    enabled: bool = False
    config: dict[str, Any] = Field(default_factory=dict)


@router.get("/summary")
def admin_summary(db: Session = Depends(get_db), admin: AdminContext = Depends(require_system_admin)) -> dict[str, Any]:
    """Return database-backed counts only; no synthetic dashboard metrics."""
    from sqlalchemy import func
    from .db_models import AIUsageLedgerRecord, AuthUserRecord, AuditLogRecord, BrowserSessionRecord, FormTaskRecord, WebsiteRegistryRecord
    return {
        "users": int(db.scalar(select(func.count()).select_from(AuthUserRecord)) or 0),
        "websites": int(db.scalar(select(func.count()).select_from(WebsiteRegistryRecord)) or 0),
        "enabled_websites": int(db.scalar(select(func.count()).select_from(WebsiteRegistryRecord).where(WebsiteRegistryRecord.enabled.is_(True))) or 0),
        "audit_events": int(db.scalar(select(func.count()).select_from(AuditLogRecord)) or 0),
        "tasks": int(db.scalar(select(func.count()).select_from(FormTaskRecord)) or 0),
        "browser_sessions": int(db.scalar(select(func.count()).select_from(BrowserSessionRecord)) or 0),
        "ai_usage": int(db.scalar(select(func.count()).select_from(AIUsageLedgerRecord)) or 0),
    }


@router.get("/users")
def admin_users(db: Session = Depends(get_db), admin: AdminContext = Depends(require_system_admin)) -> list[dict[str, Any]]:
    from .db_models import AuthUserRecord
    return [{"user_id": row.user_id, "email": row.email, "status": row.status, "role": row.role, "created_at": row.created_at.isoformat() if row.created_at else None, "last_login_at": row.last_login_at.isoformat() if row.last_login_at else None} for row in db.scalars(select(AuthUserRecord).order_by(AuthUserRecord.created_at.desc()).limit(500)).all()]


@router.get("/ai-usage")
def admin_ai_usage(db: Session = Depends(get_db), admin: AdminContext = Depends(require_system_admin)) -> dict[str, Any]:
    from .db_models import AIUsageLedgerRecord
    rows = db.scalars(select(AIUsageLedgerRecord).order_by(AIUsageLedgerRecord.created_at.desc()).limit(500)).all()
    return {"records": [{"usage_id": row.usage_id, "provider": row.provider, "model": row.model, "task": row.task_name, "user_id": row.user_id, "input_tokens": row.input_tokens, "output_tokens": row.output_tokens, "total_tokens": row.total_tokens, "latency_ms": row.latency_ms, "status": row.status, "estimated_cost": str(row.estimated_cost), "created_at": row.created_at.isoformat() if row.created_at else None} for row in rows], "total_tokens": sum(row.total_tokens for row in rows), "total_cost": str(sum(Decimal(str(row.estimated_cost or 0)) for row in rows))}


@router.get("/tasks")
def admin_tasks(db: Session = Depends(get_db), admin: AdminContext = Depends(require_system_admin)) -> list[dict[str, Any]]:
    from .db_models import FormTaskRecord
    return [{"task_id": row.task_id, "user_id": row.user_id, "state": row.state, "current_step": row.current_step, "retry_count": row.retry_count, "updated_at": row.updated_at.isoformat() if row.updated_at else None} for row in db.scalars(select(FormTaskRecord).order_by(FormTaskRecord.updated_at.desc()).limit(500)).all()]


@router.get("/browser-sessions")
def admin_browser_sessions(db: Session = Depends(get_db), admin: AdminContext = Depends(require_system_admin)) -> list[dict[str, Any]]:
    from .db_models import BrowserSessionRecord
    return [{"browser_session_id": row.browser_session_id, "task_id": row.task_id, "user_id": row.user_id, "state": row.state, "target_url": row.target_url, "updated_at": row.updated_at.isoformat() if row.updated_at else None} for row in db.scalars(select(BrowserSessionRecord).order_by(BrowserSessionRecord.updated_at.desc()).limit(500)).all()]


@router.get("/audit-logs")
def admin_audit_logs(db: Session = Depends(get_db), admin: AdminContext = Depends(require_system_admin)) -> list[dict[str, Any]]:
    from .db_models import AuditLogRecord
    return [{"id": row.id, "user_id": row.user_id, "action": row.action, "resource_type": row.resource_type, "resource_id": row.resource_id, "created_at": row.created_at.isoformat() if row.created_at else None} for row in db.scalars(select(AuditLogRecord).order_by(AuditLogRecord.created_at.desc()).limit(500)).all()]


@router.get("/payments")
def admin_payments(db: Session = Depends(get_db), admin: AdminContext = Depends(require_system_admin)) -> list[dict[str, Any]]:
    rows = db.execute(text("SELECT transaction_id, user_id, amount_paid, credits_added, status, payment_gateway, created_at FROM transactions ORDER BY created_at DESC LIMIT 500")).mappings().all()
    return [dict(row) for row in rows]


@router.post("/payments/reconcile")
def reconcile_payments(db: Session = Depends(get_db), admin: AdminContext = Depends(require_system_admin)) -> dict[str, Any]:
    matched = PaymentService(db).reconcile_unmatched()
    expired = PaymentService(db).mark_expired_orders()
    return {"status": "completed", "matched": matched, "expired": expired, "executed_by": admin.user_id}


@router.get("/storage")
def admin_storage(db: Session = Depends(get_db), admin: AdminContext = Depends(require_system_admin)) -> list[dict[str, Any]]:
    rows = db.execute(text("SELECT id, provider_name, priority, status FROM multi_cloud_storage_nodes ORDER BY priority")).mappings().all()
    return [dict(row) for row in rows]


@router.get("/health")
def admin_health(db: Session = Depends(get_db), admin: AdminContext = Depends(require_system_admin)) -> dict[str, Any]:
    return {"database": "ok", "checked_at": __import__("datetime").datetime.utcnow().isoformat()}


@router.get("/provider-policy")
def provider_policy(db: Session = Depends(get_db), admin: AdminContext = Depends(require_system_admin)) -> list[dict[str, Any]]:
    rows = db.execute(text("SELECT p.provider,p.priority,p.enabled,p.daily_tokens,p.monthly_tokens,p.daily_cost,p.monthly_cost,p.requests_per_minute,p.cooldown_seconds,h.status,h.error_rate,h.last_success_at,h.last_failure_at FROM ai_provider_policy p LEFT JOIN ai_provider_health h USING(provider) ORDER BY p.priority,p.provider")).mappings().all()
    return [dict(row) for row in rows]


class ProviderPolicyRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=80)
    priority: int = Field(ge=1, le=10000)
    enabled: bool = True
    daily_tokens: int | None = Field(default=None, ge=1)
    monthly_tokens: int | None = Field(default=None, ge=1)
    daily_cost: Decimal | None = Field(default=None, ge=0)
    monthly_cost: Decimal | None = Field(default=None, ge=0)
    requests_per_minute: int | None = Field(default=None, ge=1)
    cooldown_seconds: int = Field(default=30, ge=1, le=3600)


@router.put("/provider-policy")
def update_provider_policy(body: ProviderPolicyRequest, db: Session = Depends(get_db), admin: AdminContext = Depends(require_system_admin)) -> dict[str, Any]:
    db.execute(text("""INSERT INTO ai_provider_policy(provider,priority,enabled,daily_tokens,monthly_tokens,daily_cost,monthly_cost,requests_per_minute,cooldown_seconds,updated_by,updated_at) VALUES (:provider,:priority,:enabled,:daily_tokens,:monthly_tokens,:daily_cost,:monthly_cost,:rpm,:cooldown,:admin,CURRENT_TIMESTAMP) ON CONFLICT(provider) DO UPDATE SET priority=EXCLUDED.priority,enabled=EXCLUDED.enabled,daily_tokens=EXCLUDED.daily_tokens,monthly_tokens=EXCLUDED.monthly_tokens,daily_cost=EXCLUDED.daily_cost,monthly_cost=EXCLUDED.monthly_cost,requests_per_minute=EXCLUDED.requests_per_minute,cooldown_seconds=EXCLUDED.cooldown_seconds,updated_by=EXCLUDED.updated_by,updated_at=CURRENT_TIMESTAMP"""), {**body.model_dump(), "provider": body.provider.strip().lower(), "rpm": body.requests_per_minute, "cooldown": body.cooldown_seconds, "admin": admin.user_id})
    db.commit()
    return {"status": "updated", **body.model_dump()}


@router.post("/websites/{website_id}/health-check")
def website_health_check(website_id: str, db: Session = Depends(get_db), admin: AdminContext = Depends(require_system_admin)) -> dict[str, Any]:
    return WebsiteHealthService(db).check(website_id)


@router.put("/websites/{website_id}/enable")
def enable_website(website_id: str, db: Session = Depends(get_db), admin: AdminContext = Depends(require_system_admin)) -> dict[str, Any]:
    row = db.execute(text("SELECT verified, health_status, version FROM website_registry WHERE website_id=:website_id FOR UPDATE"), {"website_id": website_id}).mappings().first()
    if not row or not row["verified"] or row["health_status"] != "healthy":
        raise HTTPException(status_code=409, detail="website must be verified and healthy before enablement")
    db.execute(text("UPDATE website_registry SET enabled=true, updated_at=CURRENT_TIMESTAMP WHERE website_id=:website_id"), {"website_id": website_id})
    db.commit()
    return {"website_id": website_id, "enabled": True, "version": row["version"]}


@router.put("/websites/{website_id}/disable")
def disable_website(website_id: str, db: Session = Depends(get_db), admin: AdminContext = Depends(require_system_admin)) -> dict[str, Any]:
    db.execute(text("UPDATE website_registry SET enabled=false, updated_at=CURRENT_TIMESTAMP WHERE website_id=:website_id"), {"website_id": website_id})
    db.commit()
    return {"website_id": website_id, "enabled": False}


@router.get("/websites/{website_id}/health-history")
def website_health_history(website_id: str, db: Session = Depends(get_db), admin: AdminContext = Depends(require_system_admin)) -> list[dict[str, Any]]:
    return [dict(row) for row in db.execute(text("SELECT status,http_status,latency_ms,error_message,checked_at FROM website_health_history WHERE website_id=:website_id ORDER BY checked_at DESC LIMIT 100"), {"website_id": website_id}).mappings().all()]


class AdminAssistantRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)


@router.post("/assistant/query")
def admin_assistant_query(body: AdminAssistantRequest, db: Session = Depends(get_db), admin: AdminContext = Depends(require_system_admin)) -> dict[str, Any]:
    """Deterministic read-only operational assistant; it cannot authorize mutations."""
    from .db_models import AIUsageLedgerRecord, AuthUserRecord, BrowserSessionRecord, FormTaskRecord
    q = body.query.lower()
    summary = {"users": int(db.scalar(select(func.count()).select_from(AuthUserRecord)) or 0), "tasks": int(db.scalar(select(func.count()).select_from(FormTaskRecord)) or 0), "browser_sessions": int(db.scalar(select(func.count()).select_from(BrowserSessionRecord)) or 0), "ai_calls": int(db.scalar(select(func.count()).select_from(AIUsageLedgerRecord)) or 0)}
    if "failure" in q or "failed" in q:
        summary["failed_tasks"] = int(db.scalar(select(func.count()).select_from(FormTaskRecord).where(FormTaskRecord.state == "failed")) or 0)
    return {"mode": "read_only", "answer": "Operational data was queried from the database; no action was executed.", "summary": summary, "requested_by": admin.user_id}


class AdminActionPreviewRequest(BaseModel):
    action: str = Field(pattern="^(refund|delete|disable_provider|disable_website|pricing_change|credential_change|mass_communication|destructive_maintenance)$")
    payload: dict[str, Any] = Field(default_factory=dict)


@router.post("/assistant/preview")
def admin_action_preview(body: AdminActionPreviewRequest, db: Session = Depends(get_db), admin: AdminContext = Depends(require_system_admin)) -> dict[str, Any]:
    preview_id = str(uuid4())
    db.execute(text("INSERT INTO admin_action_previews(preview_id,admin_user_id,action,payload_json,status,expires_at,created_at) VALUES (:id,:admin,:action,:payload,'PENDING',:expires,CURRENT_TIMESTAMP)"), {"id": preview_id, "admin": admin.user_id, "action": body.action, "payload": json.dumps(body.payload, sort_keys=True), "expires": datetime.utcnow() + timedelta(minutes=5)})
    db.commit()
    return {"preview_id": preview_id, "action": body.action, "status": "PENDING", "expires_in_seconds": 300, "requires_explicit_confirmation": True}


@router.post("/assistant/confirm/{preview_id}")
def confirm_admin_action(preview_id: str, db: Session = Depends(get_db), admin: AdminContext = Depends(require_system_admin)) -> dict[str, Any]:
    row = db.execute(text("SELECT action,payload_json,status,expires_at FROM admin_action_previews WHERE preview_id=:id AND admin_user_id=:admin FOR UPDATE"), {"id": preview_id, "admin": admin.user_id}).mappings().first()
    if not row or row["status"] != "PENDING" or row["expires_at"] < datetime.utcnow():
        raise HTTPException(status_code=409, detail="action preview is missing, expired, or already used")
    payload = json.loads(row["payload_json"])
    if row["action"] == "refund":
        result = PaymentService(db).request_refund(transaction_id=str(payload.get("transaction_id", "")), admin_user_id=admin.user_id, reason=str(payload.get("reason", "admin-approved refund")))
    else:
        # Destructive actions are intentionally preview-only until a dedicated policy service exists.
        raise HTTPException(status_code=409, detail="this high-risk action has no executable policy handler")
    db.execute(text("UPDATE admin_action_previews SET status='EXECUTED',confirmed_at=CURRENT_TIMESTAMP WHERE preview_id=:id"), {"id": preview_id})
    db.commit()
    return {"status": "EXECUTED", "action": row["action"], "result": result}


@router.get("/websites")
def list_websites(db: Session = Depends(get_db), admin: AdminContext = Depends(require_system_admin)) -> list[dict[str, Any]]:
    from .db_models import WebsiteRegistryRecord
    rows = db.scalars(select(WebsiteRegistryRecord).order_by(WebsiteRegistryRecord.name)).all()
    return [{"website_id": row.website_id, "name": row.name, "category": row.category, "base_url": row.base_url, "allowed_domains": json.loads(row.allowed_domains_json), "enabled": row.enabled, "verified": row.verified, "version": row.version, "health_status": row.health_status, "last_health_check": row.last_health_check.isoformat() if row.last_health_check else None, "allowed_paths": json.loads(row.allowed_paths_json), "supported_fields": json.loads(row.supported_fields_json), "config": json.loads(row.config_json)} for row in rows]


@router.post("/websites", status_code=201)
def create_website(payload: WebsiteRegistryRequest, db: Session = Depends(get_db), admin: AdminContext = Depends(require_system_admin)) -> dict[str, Any]:
    from urllib.parse import urlparse
    from .db_models import WebsiteRegistryRecord
    parsed = urlparse(payload.base_url)
    if parsed.scheme not in {"https"} or not parsed.hostname:
        raise HTTPException(status_code=422, detail="website base_url must be an HTTPS URL")
    domains = [domain.strip().lower().rstrip(".") for domain in payload.allowed_domains if domain.strip()]
    if any("/" in domain or ":" in domain or " " in domain for domain in domains):
        raise HTTPException(status_code=422, detail="allowed_domains must contain hostnames only")
    if parsed.hostname.lower() not in domains:
        domains.append(parsed.hostname.lower())
    row = WebsiteRegistryRecord(name=payload.name.strip(), category=payload.category.strip().lower(), base_url=payload.base_url, allowed_domains_json=json.dumps(sorted(set(domains))), enabled=False, verified=False, health_status="unknown", config_json=json.dumps(payload.config, separators=(",", ":")))
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"website_id": row.website_id, "name": row.name, "category": row.category, "base_url": row.base_url, "allowed_domains": domains, "enabled": row.enabled, "verified": row.verified, "config": payload.config}


class ProviderConfigRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=160)
    endpoint: str | None = Field(default=None, max_length=500)
    capabilities: list[str] = Field(default_factory=lambda: ["general"])
    reasoning: bool = False
    free_tier: bool = False
    enabled: bool = True
    priority: int = Field(default=100, ge=1, le=10000)
    fallback_order: int = Field(default=100, ge=1, le=10000)


@router.get("/providers")
def list_ai_providers(db: Session = Depends(get_db), admin: AdminContext = Depends(require_system_admin)) -> list[dict[str, Any]]:
    rows = db.execute(text("SELECT r.provider,r.display_name,r.adapter_type,r.capabilities_json,r.reasoning,r.free_tier,r.enabled,r.priority,r.fallback_order,r.endpoint,r.last_error,r.last_success_at,r.last_test_at,h.status,h.error_rate FROM ai_provider_registry r LEFT JOIN ai_provider_health h USING(provider) ORDER BY r.priority,r.fallback_order,r.provider")).mappings().all()
    known = {str(row["provider"]) for row in rows}
    result = [dict(row) | {"capabilities": json.loads(row["capabilities_json"] or "[]"), "configured": bool(db.execute(text("SELECT 1 FROM admin_api_keys WHERE provider_name=:provider AND is_active=true"), {"provider": row["provider"]}).scalar())} for row in rows]
    result.extend({**item, "capabilities": ["general"], "enabled": False, "configured": False, "status": "unconfigured", "priority": 100, "fallback_order": 100} for item in PROVIDER_CATALOG if item["provider"] not in known)
    return result


@router.put("/providers/{provider}")
def update_ai_provider(provider: str, body: ProviderConfigRequest, db: Session = Depends(get_db), admin: AdminContext = Depends(require_system_admin)) -> dict[str, Any]:
    provider = provider.strip().lower()
    db.execute(text("""INSERT INTO ai_provider_registry(provider,display_name,adapter_type,capabilities_json,reasoning,free_tier,enabled,priority,fallback_order,endpoint,updated_at) VALUES (:provider,:name,'openai_compatible',:capabilities,:reasoning,:free,:enabled,:priority,:fallback,:endpoint,now()) ON CONFLICT(provider) DO UPDATE SET display_name=COALESCE(:name,ai_provider_registry.display_name),capabilities_json=:capabilities,reasoning=:reasoning,free_tier=:free,enabled=:enabled,priority=:priority,fallback_order=:fallback,endpoint=:endpoint,updated_at=now()"""), {"provider": provider, "name": body.display_name or provider, "capabilities": json.dumps(body.capabilities), "reasoning": body.reasoning, "free": body.free_tier, "enabled": body.enabled, "priority": body.priority, "fallback": body.fallback_order, "endpoint": body.endpoint})
    db.commit()
    return {"provider": provider, "status": "updated", **body.model_dump()}


class ProviderCredentialRequest(BaseModel):
    credential: dict[str, Any] = Field(min_length=1)


@router.put("/providers/{provider}/credential")
def rotate_provider_credential(provider: str, body: ProviderCredentialRequest, db: Session = Depends(get_db), admin: AdminContext = Depends(require_system_admin)) -> dict[str, Any]:
    provider = provider.strip().lower()
    ciphertext = encrypt_admin_api_key(json.dumps(body.credential, separators=(",", ":")))
    db.execute(text("INSERT INTO admin_api_keys(provider_name,api_key_encrypted,is_active,updated_at) VALUES (:provider,:secret,true,now()) ON CONFLICT(provider_name) DO UPDATE SET api_key_encrypted=:secret,is_active=true,updated_at=now()"), {"provider": provider, "secret": ciphertext})
    db.commit()
    return {"provider": provider, "configured": True, "secret": "masked"}


@router.get("/storage/providers")
def list_storage_providers(db: Session = Depends(get_db), admin: AdminContext = Depends(require_system_admin)) -> list[dict[str, Any]]:
    rows = db.execute(text("SELECT provider,display_name,adapter_type,endpoint,bucket,region,capacity_bytes,free_quota_bytes,usage_bytes,priority,enabled,health,last_test_at FROM storage_provider_registry ORDER BY priority,provider")).mappings().all()
    return [dict(row) for row in rows]


class StorageProviderRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=160)
    endpoint: str | None = None
    bucket: str | None = None
    region: str | None = None
    capacity_bytes: int | None = Field(default=None, ge=0)
    free_quota_bytes: int | None = Field(default=None, ge=0)
    priority: int = Field(default=100, ge=1)
    enabled: bool = True


@router.put("/storage/providers/{provider}")
def update_storage_provider(provider: str, body: StorageProviderRequest, db: Session = Depends(get_db), admin: AdminContext = Depends(require_system_admin)) -> dict[str, Any]:
    db.execute(text("""INSERT INTO storage_provider_registry(provider,display_name,endpoint,bucket,region,capacity_bytes,free_quota_bytes,priority,enabled,updated_at) VALUES (:provider,:name,:endpoint,:bucket,:region,:capacity,:free,:priority,:enabled,now()) ON CONFLICT(provider) DO UPDATE SET display_name=:name,endpoint=:endpoint,bucket=:bucket,region=:region,capacity_bytes=:capacity,free_quota_bytes=:free,priority=:priority,enabled=:enabled,updated_at=now()"""), {"provider": provider.strip().lower(), "name": body.display_name, "endpoint": body.endpoint, "bucket": body.bucket, "region": body.region, "capacity": body.capacity_bytes, "free": body.free_quota_bytes, "priority": body.priority, "enabled": body.enabled})
    db.commit()
    return {"provider": provider.strip().lower(), "status": "updated", **body.model_dump()}


@router.get("/auth/providers")
def list_auth_providers(db: Session = Depends(get_db), admin: AdminContext = Depends(require_system_admin)) -> list[dict[str, Any]]:
    rows = db.execute(text("SELECT provider,display_name,priority,enabled,methods_json,health,last_test_at FROM auth_provider_registry ORDER BY priority,provider")).mappings().all()
    return [dict(row) | {"methods": json.loads(row["methods_json"] or "[]")} for row in rows]


class AuthProviderRequest(BaseModel):
    priority: int = Field(default=100, ge=1)
    enabled: bool = True
    methods: list[str] = Field(default_factory=lambda: ["password"])


@router.put("/auth/providers/{provider}")
def update_auth_provider(provider: str, body: AuthProviderRequest, db: Session = Depends(get_db), admin: AdminContext = Depends(require_system_admin)) -> dict[str, Any]:
    db.execute(text("UPDATE auth_provider_registry SET priority=:priority,enabled=:enabled,methods_json=:methods,updated_at=now() WHERE provider=:provider"), {"provider": provider.strip().lower(), "priority": body.priority, "enabled": body.enabled, "methods": json.dumps(body.methods)})
    db.commit()
    return {"provider": provider.strip().lower(), "status": "updated", **body.model_dump()}


class StorageCredentialRequest(BaseModel):
    credential: dict[str, Any] = Field(min_length=1)


@router.put("/storage/providers/{provider}/credential")
def rotate_storage_credential(provider: str, body: StorageCredentialRequest, db: Session = Depends(get_db), admin: AdminContext = Depends(require_system_admin)) -> dict[str, Any]:
    provider = provider.strip().lower()
    ciphertext = encrypt_admin_api_key(json.dumps(body.credential, separators=(",", ":")))
    db.execute(text("UPDATE storage_provider_registry SET credentials_encrypted=:secret,updated_at=now() WHERE provider=:provider"), {"provider": provider, "secret": ciphertext})
    db.commit()
    return {"provider": provider, "configured": True, "secret": "masked"}


@router.post("/providers/{provider}/test")
def test_provider_connection(provider: str, db: Session = Depends(get_db), admin: AdminContext = Depends(require_system_admin)) -> dict[str, Any]:
    """Return connection metadata only; credentials and provider responses are never exposed."""
    provider = provider.strip().lower()
    try:
        row = db.execute(text("SELECT provider,enabled,endpoint FROM ai_provider_registry WHERE provider=:provider"), {"provider": provider}).mappings().first()
        key = db.execute(text("SELECT 1 FROM admin_api_keys WHERE provider_name=:provider AND is_active=true"), {"provider": provider}).scalar()
        if not row or not row["enabled"] or not key:
            return {"provider": provider, "configured": bool(key), "reachable": False, "authenticated": False, "health": "configuration_error"}
        from .ai_provider_adapter import MultiAIProviderAdapter
        started = __import__("time").monotonic()
        models = MultiAIProviderAdapter(db, credential_decryptor=__import__("app.credential_crypto", fromlist=["decrypt_admin_api_key"]).decrypt_admin_api_key).discover_models(provider)
        return {"provider": provider, "configured": True, "reachable": True, "authenticated": True, "capabilities": models[0].get("capabilities", []) if models else [], "model_count": len(models), "latency_ms": int((__import__("time").monotonic() - started) * 1000), "health": "healthy"}
    except Exception:
        db.rollback()
        return {"provider": provider, "configured": False, "reachable": False, "authenticated": False, "health": "unavailable"}


@router.post("/providers/{provider}/models/discover")
def discover_provider_models(provider: str, db: Session = Depends(get_db), admin: AdminContext = Depends(require_system_admin)) -> dict[str, Any]:
    from .ai_provider_adapter import MultiAIProviderAdapter
    try:
        models = MultiAIProviderAdapter(db, credential_decryptor=__import__("app.credential_crypto", fromlist=["decrypt_admin_api_key"]).decrypt_admin_api_key).discover_models(provider)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="provider model discovery failed") from exc
    return {"provider": provider.strip().lower(), "models": models, "count": len(models)}
