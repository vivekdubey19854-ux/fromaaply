from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import hash_password, issue_access_token, issue_dev_token, issue_refresh_token, verify_password
from app.config import settings
from app.database import get_db
from app.db_models import AuthUserRecord, ProfileRecord

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
    return {"user_id": user.user_id, "email": user.email, **_tokens(user)}


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
    user = db.get(AuthUserRecord, str(claims.get("sub", "")))
    if user is None or user.status != "active":
        raise HTTPException(status_code=401, detail="account is unavailable")
    return {"user_id": user.user_id, "email": user.email, **_tokens(user)}


@router.post("/dev-token")
def dev_token(payload: DevTokenRequest) -> dict[str, str | int]:
    if settings.environment == "production":
        raise HTTPException(status_code=404, detail="development token issuance is disabled")
    return {"access_token": issue_dev_token(payload.user_id, payload.ttl_seconds), "token_type": "bearer", "expires_in": payload.ttl_seconds}
