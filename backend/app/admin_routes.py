from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from .auth import require_user_id
from .config import settings
from .credential_crypto import encrypt_admin_api_key
from .database import get_db

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
