from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.auth import issue_dev_token
from app.config import settings

router = APIRouter(prefix="/v1/auth", tags=["auth"])


class DevTokenRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=64)
    ttl_seconds: int = Field(default=3600, ge=300, le=3600)


@router.post("/dev-token")
def dev_token(payload: DevTokenRequest) -> dict[str, str | int]:
    if settings.environment == "production":
        raise HTTPException(status_code=404, detail="development token issuance is disabled")
    return {
        "access_token": issue_dev_token(payload.user_id, payload.ttl_seconds),
        "token_type": "bearer",
        "expires_in": payload.ttl_seconds,
    }
