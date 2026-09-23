from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import generate_one_time_token, hash_one_time_token, hash_password, issue_access_token, issue_dev_token, issue_refresh_token, require_user_id, verify_password
from app.ai_provider_adapter import MultiAIProviderAdapter
from app.config import settings
from app.credential_crypto import decrypt_admin_api_key
from app.database import get_db
from app.db_models import AuthActionTokenRecord, AuthUserRecord, ProfileRecord, RevokedTokenRecord
from app.notification_service import BrevoNotificationService

router = APIRouter(prefix="/v1/auth", tags=["auth"])


class DevTokenRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=64)
    ttl_seconds: int = Field(default=3600, ge=300, le=3600)


class SignupRequest(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=12, max_length=256)
    full_name: str | None = Field(default=None, max_length=200)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("valid email is required")
        return value


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=4096)


class LogoutRequest(BaseModel):
    refresh_token: str | None = Field(default=None, min_length=20, max_length=4096)


class EmailActionRequest(BaseModel):
    email: str = Field(min_length=5, max_length=320)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class PasswordResetRequest(BaseModel):
    token: str = Field(min_length=20, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


def _tokens(user: AuthUserRecord) -> dict[str, str | int]:
    return {
        "access_token": issue_access_token(user.user_id, role=user.role),
        "refresh_token": issue_refresh_token(user.user_id),
        "token_type": "bearer",
        "expires_in": 900,
    }


@router.post("/signup", status_code=201)
def signup(payload: SignupRequest, db: Session = Depends(get_db)) -> dict[str, str | int]:
    user_id = str(uuid4())
    user = AuthUserRecord(user_id=user_id, email=payload.email, password_hash=hash_password(payload.password))
    profile = ProfileRecord(user_id=user_id, full_name=payload.full_name, email=payload.email)
    db.add(user)
    db.add(profile)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="an account with this email already exists") from exc
    db.refresh(user)
    return {"user_id": user.user_id, "email": user.email, "email_verification_required": True, **_tokens(user)}


@router.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> dict[str, str | int]:
    user = db.scalar(select(AuthUserRecord).where(AuthUserRecord.email == payload.email))
    if user is None or user.status != "active" or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid email or password")
    user.last_login_at = datetime.utcnow()
    db.commit()
    return {"user_id": user.user_id, "email": user.email, **_tokens(user)}


@router.post("/refresh")
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)) -> dict[str, str | int]:
    import jwt
    try:
        claims = jwt.decode(payload.refresh_token, settings.jwt_secret, algorithms=[settings.jwt_algorithm], options={"require": ["sub", "exp"]})
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="invalid refresh token") from exc
    if claims.get("role") != "refresh":
        raise HTTPException(status_code=401, detail="invalid refresh token")
    jti = str(claims.get("jti", ""))
    if not jti or db.get(RevokedTokenRecord, jti) is not None:
        raise HTTPException(status_code=401, detail="refresh token has been revoked")
    user = db.get(AuthUserRecord, str(claims.get("sub", "")))
    if user is None or user.status != "active":
        raise HTTPException(status_code=401, detail="account is unavailable")
    return {"user_id": user.user_id, "email": user.email, **_tokens(user)}


@router.post("/dev-token")
def dev_token(payload: DevTokenRequest) -> dict[str, str | int]:
    if settings.environment == "production":
        raise HTTPException(status_code=404, detail="development token issuance is disabled")
    return {"access_token": issue_dev_token(payload.user_id, payload.ttl_seconds), "token_type": "bearer", "expires_in": payload.ttl_seconds}


@router.post("/logout")
def logout(payload: LogoutRequest | None = None, user_id: str = Depends(require_user_id), db: Session = Depends(get_db)) -> dict[str, str]:
    if payload and payload.refresh_token:
        import jwt
        try:
            claims = jwt.decode(payload.refresh_token, settings.jwt_secret, algorithms=[settings.jwt_algorithm], options={"require": ["sub", "exp", "jti"]})
            if claims.get("role") == "refresh" and str(claims.get("sub")) == user_id:
                db.merge(RevokedTokenRecord(jti=str(claims["jti"]), user_id=user_id, expires_at=datetime.fromtimestamp(claims["exp"])))
                db.commit()
        except jwt.PyJWTError:
            pass
    return {"status": "logged_out", "user_id": user_id}


def _create_action_token(db: Session, user: AuthUserRecord, purpose: str, ttl_hours: int) -> str:
    raw = generate_one_time_token()
    db.add(AuthActionTokenRecord(token_hash=hash_one_time_token(raw), user_id=user.user_id, purpose=purpose, expires_at=datetime.utcnow() + timedelta(hours=ttl_hours)))
    db.commit()
    return raw


def _deliver_action_email(db: Session, user: AuthUserRecord, token: str, purpose: str) -> bool:
    if not settings.email_delivery_enabled:
        return False
    service = BrevoNotificationService(MultiAIProviderAdapter(db, credential_decryptor=decrypt_admin_api_key))
    try:
        if purpose == "email_verification":
            service.send_verification_email(user.email, token, base_url=settings.frontend_base_url)
        else:
            service.send_password_reset_email(user.email, token, base_url=settings.frontend_base_url)
        return True
    except Exception:
        return False
    finally:
        service.close()


@router.post("/verification/request")
def request_verification(payload: EmailActionRequest, db: Session = Depends(get_db)) -> dict[str, str | bool]:
    user = db.scalar(select(AuthUserRecord).where(AuthUserRecord.email == payload.email))
    response: dict[str, str | bool] = {"status": "accepted", "email_delivery_configured": False}
    if user and user.status == "active":
        raw = _create_action_token(db, user, "email_verification", 24)
        response["email_delivery_configured"] = _deliver_action_email(db, user, raw, "email_verification")
        if settings.environment != "production":
            response["development_token"] = raw
    return response


@router.post("/verification/confirm")
def confirm_verification(payload: RefreshRequest, db: Session = Depends(get_db)) -> dict[str, str]:
    token = db.get(AuthActionTokenRecord, hash_one_time_token(payload.refresh_token))
    if token is None or token.purpose != "email_verification" or token.used_at or token.expires_at <= datetime.utcnow():
        raise HTTPException(status_code=400, detail="invalid or expired verification token")
    user = db.get(AuthUserRecord, token.user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="invalid verification token")
    token.used_at = datetime.utcnow()
    db.commit()
    return {"status": "verified", "user_id": user.user_id}


@router.post("/password-reset/request")
def request_password_reset(payload: EmailActionRequest, db: Session = Depends(get_db)) -> dict[str, str | bool]:
    user = db.scalar(select(AuthUserRecord).where(AuthUserRecord.email == payload.email))
    response: dict[str, str | bool] = {"status": "accepted", "email_delivery_configured": False}
    if user and user.status == "active":
        raw = _create_action_token(db, user, "password_reset", 1)
        response["email_delivery_configured"] = _deliver_action_email(db, user, raw, "password_reset")
        if settings.environment != "production":
            response["development_token"] = raw
    return response


@router.post("/password-reset/confirm")
def confirm_password_reset(payload: PasswordResetRequest, db: Session = Depends(get_db)) -> dict[str, str]:
    token = db.get(AuthActionTokenRecord, hash_one_time_token(payload.token))
    if token is None or token.purpose != "password_reset" or token.used_at or token.expires_at <= datetime.utcnow():
        raise HTTPException(status_code=400, detail="invalid or expired password reset token")
    user = db.get(AuthUserRecord, token.user_id)
    if user is None or user.status != "active":
        raise HTTPException(status_code=400, detail="account is unavailable")
    user.password_hash = hash_password(payload.new_password)
    token.used_at = datetime.utcnow()
    db.commit()
    return {"status": "password_updated"}


@router.get("/providers")
def configured_auth_providers(db: Session = Depends(get_db)) -> dict[str, object]:
    """Expose only enabled login methods; provider credentials never leave the server."""
    try:
        rows = db.execute(__import__("sqlalchemy").text("SELECT provider,display_name,methods_json,health FROM auth_provider_registry WHERE enabled=true ORDER BY priority,provider")).mappings().all()
    except Exception:
        rows = []
    methods: set[str] = {"password"}
    providers: list[dict[str, object]] = []
    for row in rows:
        configured = __import__("json").loads(row["methods_json"] or "[]")
        methods.update(configured)
        providers.append({"provider": row["provider"], "display_name": row["display_name"], "methods": configured, "health": row["health"]})
    return {"methods": sorted(methods), "providers": providers}
