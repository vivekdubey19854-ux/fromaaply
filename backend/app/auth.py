from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timezone

import jwt
from fastapi import Header, HTTPException

from app.config import settings


def _password_hash(password: str, salt: bytes | None = None) -> str:
    if not isinstance(password, str) or len(password) < 12 or len(password) > 256:
        raise ValueError("password must contain 12-256 characters")
    salt = salt or secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$16384$8$1${salt}${digest}".format(
        salt=base64.urlsafe_b64encode(salt).decode("ascii"),
        digest=base64.urlsafe_b64encode(derived).decode("ascii"),
    )


def hash_password(password: str) -> str:
    return _password_hash(password)


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n, r, p, salt_text, digest_text = encoded.split("$", 5)
        if scheme != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, UnicodeError):
        return False


def issue_access_token(user_id: str, *, ttl_seconds: int = 900, role: str = "user") -> str:
    if not user_id or len(user_id) > 128:
        raise ValueError("invalid user id")
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": user_id, "role": role, "iat": int(now.timestamp()), "exp": int(now.timestamp()) + ttl_seconds, "jti": secrets.token_urlsafe(16)},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def issue_refresh_token(user_id: str, *, ttl_seconds: int = 30 * 24 * 3600) -> str:
    return issue_access_token(user_id, ttl_seconds=ttl_seconds, role="refresh")


def require_user_id(authorization: str | None = Header(default=None), x_user_id: str | None = Header(default=None)) -> str:
    """Authenticate from a verified JWT; legacy identity headers are development-only."""
    if authorization and authorization.lower().startswith("bearer "):
        try:
            claims = jwt.decode(authorization[7:].strip(), settings.jwt_secret, algorithms=[settings.jwt_algorithm], options={"require": ["sub", "exp"]})
        except jwt.PyJWTError as exc:
            raise HTTPException(status_code=401, detail="invalid authentication token") from exc
        user_id = str(claims.get("sub", ""))
        if not user_id or len(user_id) > 128 or claims.get("role") == "refresh":
            raise HTTPException(status_code=401, detail="invalid authenticated user")
        return user_id
    if settings.allow_legacy_user_header and settings.environment != "production" and x_user_id and len(x_user_id) <= 64:
        return x_user_id
    raise HTTPException(status_code=401, detail="authentication required")


def issue_dev_token(user_id: str, ttl_seconds: int = 3600) -> str:
    if settings.environment == "production":
        raise RuntimeError("development token issuance is disabled in production")
    return issue_access_token(user_id, ttl_seconds=ttl_seconds)



def generate_one_time_token() -> str:
    return secrets.token_urlsafe(32)


def hash_one_time_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
