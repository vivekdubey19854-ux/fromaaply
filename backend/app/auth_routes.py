from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import generate_one_time_token, hash_one_time_token, hash_password, issue_access_token, issue_dev_token, issue_refresh_token, require_user_id, verify_password
from app.ai_provider_adapter import MultiAIProviderAdapter
from app.config import settings
from app.database import get_db
from app.db_models import AuthActionTokenRecord, AuthUserRecord, ProfileRecord, RevokedTokenRecord
from app.notification_service import BrevoNotificationService
from app.auth_provider_service import (InvalidProviderCredential, ProviderUnavailable, exchange_oauth_code, issue_session, provider_configs, request_otp, resolve_identity, revoke_session, rotate_session, verify_otp, verify_provider_token)
from app.credential_crypto import decrypt_admin_api_key

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


def _session_response(db: Session, user_id: str, request: Request) -> dict[str, str | int]:
    user = db.get(AuthUserRecord, user_id)
    if user is None or user.status != "active":
        raise HTTPException(status_code=401, detail="account is unavailable")
    return {"user_id": user.user_id, "email": user.email, **issue_session(db, user.user_id, user_agent=request.headers.get("user-agent"), ip_address=request.client.host if request.client else None)}


@router.post("/signup", status_code=201)
def signup(payload: SignupRequest, request: Request, db: Session = Depends(get_db)) -> dict[str, str | int]:
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
    return {"user_id": user.user_id, "email": user.email, "email_verification_required": True, **issue_session(db, user.user_id, user_agent=request.headers.get("user-agent"), ip_address=request.client.host if request.client else None)}


@router.post("/login")
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> dict[str, str | int]:
    user = db.scalar(select(AuthUserRecord).where(AuthUserRecord.email == payload.email))
    if user is None or user.status != "active" or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid email or password")
    user.last_login_at = datetime.utcnow()
    db.commit()
    return {"user_id": user.user_id, "email": user.email, **issue_session(db, user.user_id, user_agent=request.headers.get("user-agent"), ip_address=request.client.host if request.client else None)}


@router.post("/refresh")
def refresh(payload: RefreshRequest, request: Request, db: Session = Depends(get_db)) -> dict[str, str | int]:
    try:
        user_id, tokens = rotate_session(db, payload.refresh_token, user_agent=request.headers.get("user-agent"), ip_address=request.client.host if request.client else None)
    except InvalidProviderCredential as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    user = db.get(AuthUserRecord, user_id)
    return {"user_id": user_id, "email": user.email if user else None, **tokens}


@router.post("/dev-token")
def dev_token(payload: DevTokenRequest) -> dict[str, str | int]:
    if settings.environment == "production":
        raise HTTPException(status_code=404, detail="development token issuance is disabled")
    return {"access_token": issue_dev_token(payload.user_id, payload.ttl_seconds), "token_type": "bearer", "expires_in": payload.ttl_seconds}


@router.post("/logout")
def logout(payload: LogoutRequest | None = None, user_id: str = Depends(require_user_id), db: Session = Depends(get_db)) -> dict[str, str]:
    revoke_session(db, payload.refresh_token if payload else None, user_id)
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
        rows = db.execute(__import__("sqlalchemy").text("SELECT provider,display_name,methods_json,health,credentials_encrypted FROM auth_provider_registry WHERE enabled=true ORDER BY priority,provider")).mappings().all()
    except Exception:
        rows = []
    methods: set[str] = {"password"}
    providers: list[dict[str, object]] = []
    for row in rows:
        configured = __import__("json").loads(row["methods_json"] or "[]")
        methods.update(configured)
        providers.append({"provider": row["provider"], "display_name": row["display_name"], "methods": configured, "health": row["health"], "configured": bool(row["credentials_encrypted"])})
    return {"methods": sorted(methods), "providers": providers}


class OAuthExchangeRequest(BaseModel):
    code: str = Field(min_length=20, max_length=512)


class ProviderTokenRequest(BaseModel):
    provider: str = Field(default="auto", min_length=2, max_length=80)
    token: str = Field(min_length=20, max_length=20000)


class OTPRequest(BaseModel):
    phone: str = Field(min_length=8, max_length=20)


class OTPVerifyRequest(BaseModel):
    challenge_id: str = Field(min_length=20, max_length=80)
    code: str = Field(min_length=4, max_length=12)


class LinkIdentityRequest(BaseModel):
    provider: str = Field(min_length=2, max_length=80)
    token: str = Field(min_length=20, max_length=20000)


def _oauth_provider(db: Session, provider: str):
    configs = provider_configs(db, "oauth")
    return next((item for item in configs if item.provider == provider.strip().lower()), None)


@router.get("/oauth/{provider}/start")
def oauth_start(provider: str, request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    config = _oauth_provider(db, provider)
    if not config:
        raise HTTPException(status_code=503, detail="OAuth provider is disabled or not configured")
    authorize_url = str(config.config.get("authorize_url", ""))
    client_id = str(config.config.get("client_id", ""))
    if not authorize_url or not client_id:
        raise HTTPException(status_code=503, detail="OAuth provider credentials are not configured")
    from urllib.parse import urlencode
    state = generate_one_time_token()
    nonce = generate_one_time_token()
    redirect_uri = f"{str(request.base_url).rstrip('/')}/v1/auth/oauth/{config.provider}/callback"
    db.execute(__import__("sqlalchemy").text("INSERT INTO auth_oauth_states(state_hash,provider,nonce,redirect_uri,expires_at) VALUES (:hash,:provider,:nonce,:redirect,:expires)"), {"hash": hash_one_time_token(state), "provider": config.provider, "nonce": nonce, "redirect": redirect_uri, "expires": datetime.utcnow() + timedelta(minutes=10)})
    db.commit()
    query = urlencode({"client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code", "scope": "openid email profile", "state": state, "nonce": nonce, "access_type": "offline", "prompt": "select_account"})
    return RedirectResponse(f"{authorize_url}?{query}", status_code=307)


@router.get("/oauth/{provider}/callback")
def oauth_callback(provider: str, code: str, state: str, db: Session = Depends(get_db)) -> RedirectResponse:
    row = db.execute(__import__("sqlalchemy").text("SELECT provider,redirect_uri,expires_at,used_at FROM auth_oauth_states WHERE state_hash=:hash"), {"hash": hash_one_time_token(state)}).mappings().first()
    if not row or row["provider"] != provider.strip().lower() or row["used_at"] or row["expires_at"] <= datetime.utcnow():
        raise HTTPException(status_code=400, detail="invalid or expired OAuth state")
    config = _oauth_provider(db, provider)
    if not config:
        raise HTTPException(status_code=503, detail="OAuth provider is disabled")
    try:
        identity = exchange_oauth_code(config, code, str(row["redirect_uri"]), state)
    except InvalidProviderCredential as exc:
        raise HTTPException(status_code=401, detail="OAuth credentials were rejected") from exc
    except ProviderUnavailable as exc:
        raise HTTPException(status_code=503, detail="OAuth provider is unavailable") from exc
    db.execute(__import__("sqlalchemy").text("UPDATE auth_oauth_states SET used_at=:now WHERE state_hash=:hash"), {"now": datetime.utcnow(), "hash": hash_one_time_token(state)})
    user_id = resolve_identity(db, identity)
    handoff = generate_one_time_token()
    db.add(AuthActionTokenRecord(token_hash=hash_one_time_token(handoff), user_id=user_id, purpose="oauth_handoff", expires_at=datetime.utcnow() + timedelta(minutes=2)))
    db.commit()
    return RedirectResponse(f"{settings.frontend_base_url.rstrip('/')}/?auth_code={handoff}", status_code=303)


@router.post("/oauth/exchange")
def oauth_exchange(payload: OAuthExchangeRequest, request: Request, db: Session = Depends(get_db)) -> dict[str, str | int]:
    row = db.get(AuthActionTokenRecord, hash_one_time_token(payload.code))
    if not row or row.purpose != "oauth_handoff" or row.used_at or row.expires_at <= datetime.utcnow():
        raise HTTPException(status_code=401, detail="invalid or expired authentication handoff")
    row.used_at = datetime.utcnow()
    db.commit()
    return _session_response(db, row.user_id, request)


@router.post("/provider/token")
def provider_token(payload: ProviderTokenRequest, request: Request, db: Session = Depends(get_db)) -> dict[str, str | int]:
    requested = payload.provider.strip().lower()
    all_configs = provider_configs(db, "token")
    configs = all_configs if requested == "auto" else [item for item in all_configs if item.provider == requested]
    if not configs:
        raise HTTPException(status_code=503, detail="provider token authentication is disabled")
    failures: list[Exception] = []
    for config in configs:
        try:
            identity = verify_provider_token(config, payload.token)
            user_id = resolve_identity(db, identity)
            return _session_response(db, user_id, request)
        except InvalidProviderCredential as exc:
            # Never try a different provider after an invalid user credential.
            raise HTTPException(status_code=401, detail="provider identity token is invalid") from exc
        except ProviderUnavailable as exc:
            failures.append(exc)
    raise HTTPException(status_code=503, detail="all identity providers are unavailable") from (failures[-1] if failures else None)


@router.post("/otp/request")
def otp_request(payload: OTPRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        return request_otp(db, payload.phone)
    except InvalidProviderCredential as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ProviderUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/otp/verify")
def otp_verify(payload: OTPVerifyRequest, request: Request, db: Session = Depends(get_db)) -> dict[str, str | int]:
    try:
        user_id, tokens = verify_otp(db, payload.challenge_id, payload.code)
    except InvalidProviderCredential as exc:
        raise HTTPException(status_code=401, detail="invalid or expired OTP") from exc
    except ProviderUnavailable as exc:
        raise HTTPException(status_code=503, detail="OTP provider is unavailable") from exc
    user = db.get(AuthUserRecord, user_id)
    return {"user_id": user_id, "email": user.email if user else None, **tokens}


@router.post("/link")
def link_identity(payload: LinkIdentityRequest, request: Request, user_id: str = Depends(require_user_id), db: Session = Depends(get_db)) -> dict[str, Any]:
    configs = [item for item in provider_configs(db, "token") if item.provider == payload.provider.strip().lower()]
    if not configs:
        raise HTTPException(status_code=503, detail="identity provider is disabled")
    try:
        identity = verify_provider_token(configs[0], payload.token)
    except InvalidProviderCredential as exc:
        raise HTTPException(status_code=401, detail="provider identity token is invalid") from exc
    except ProviderUnavailable as exc:
        raise HTTPException(status_code=503, detail="identity provider is unavailable") from exc
    existing = db.execute(__import__("sqlalchemy").text("SELECT user_id FROM auth_identity_mappings WHERE provider=:provider AND subject=:subject"), {"provider": identity["provider"], "subject": identity["subject"]}).scalar()
    if existing and str(existing) != user_id:
        raise HTTPException(status_code=409, detail="identity is already linked to another account")
    email_owner = db.execute(__import__("sqlalchemy").text("SELECT user_id FROM auth_users WHERE email=:email"), {"email": identity.get("email")}).scalar() if identity.get("email") else None
    if email_owner and str(email_owner) != user_id:
        raise HTTPException(status_code=409, detail="provider email belongs to another account")
    if not existing:
        db.execute(__import__("sqlalchemy").text("INSERT INTO auth_identity_mappings(mapping_id,user_id,provider,subject) VALUES (:mapping,:user,:provider,:subject)"), {"mapping": str(uuid4()), "user": user_id, "provider": identity["provider"], "subject": identity["subject"]})
        db.commit()
    return {"status": "linked", "user_id": user_id, "provider": identity["provider"], "subject": identity["subject"]}


@router.get("/linked")
def linked_identities(user_id: str = Depends(require_user_id), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.execute(__import__("sqlalchemy").text("SELECT provider,subject,created_at FROM auth_identity_mappings WHERE user_id=:user_id ORDER BY provider"), {"user_id": user_id}).mappings().all()
    return [{"provider": row["provider"], "subject": row["subject"], "created_at": row["created_at"].isoformat() if row["created_at"] else None} for row in rows]
