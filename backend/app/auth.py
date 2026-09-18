from __future__ import annotations
from datetime import datetime, timezone
import jwt
from fastapi import Header, HTTPException
from app.config import settings

def require_user_id(authorization: str | None = Header(default=None), x_user_id: str | None = Header(default=None)) -> str:
    """Authenticate from a verified JWT; legacy identity headers are development-only."""
    if authorization and authorization.lower().startswith("bearer "):
        try:
            claims = jwt.decode(authorization[7:].strip(), settings.jwt_secret, algorithms=[settings.jwt_algorithm], options={"require": ["sub", "exp"]})
        except jwt.PyJWTError as exc:
            raise HTTPException(status_code=401, detail="invalid authentication token") from exc
        user_id = str(claims.get("sub", ""))
        if not user_id or len(user_id) > 128:
            raise HTTPException(status_code=401, detail="invalid authenticated user")
        return user_id
    if settings.allow_legacy_user_header and settings.environment != "production" and x_user_id and len(x_user_id) <= 64:
        return x_user_id
    raise HTTPException(status_code=401, detail="authentication required")

def issue_dev_token(user_id: str, ttl_seconds: int = 3600) -> str:
    if settings.environment == "production":
        raise RuntimeError("development token issuance is disabled in production")
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": user_id, "iat": int(now.timestamp()), "exp": int(now.timestamp()) + ttl_seconds}, settings.jwt_secret, algorithm=settings.jwt_algorithm)
