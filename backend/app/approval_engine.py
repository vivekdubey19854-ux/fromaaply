from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass

from app.storage import PrivateStorage


SENSITIVE_FIELDS = {
    "aadhaar_number", "pan_number", "date_of_birth", "address",
    "phone", "email", "gender", "full_name", "first_name", "last_name",
}
BLOCKED_ACTIONS = {
    "captcha", "anti_bot_bypass", "otp", "payment", "legal_declaration",
    "final_submission",
}


class ApprovalError(ValueError):
    pass


@dataclass(frozen=True)
class Approval:
    approval_id: str
    user_id: str
    action: str
    resource_id: str
    fingerprint: str
    status: str
    created_at: float
    expires_at: float


def _key(approval_id: str) -> str:
    return f"approvals/{approval_id}.json"


def _fingerprint(action: str, resource_id: str, payload: dict) -> str:
    canonical = json.dumps({"action": action, "resource_id": resource_id, "payload": payload}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def requires_approval(action: str, field: str | None = None) -> bool:
    return action in BLOCKED_ACTIONS or action in {"fill_sensitive", "fill_form"} or (field or "") in SENSITIVE_FIELDS


def create_approval(storage: PrivateStorage, user_id: str, action: str, resource_id: str, payload: dict, ttl_seconds: int = 600) -> Approval:
    if action in BLOCKED_ACTIONS:
        raise ApprovalError(f"{action} cannot be approved for automatic execution")
    if ttl_seconds < 30 or ttl_seconds > 3600:
        raise ApprovalError("invalid approval expiry")
    now = time.time()
    approval = Approval(secrets.token_urlsafe(18), user_id, action, resource_id, _fingerprint(action, resource_id, payload), "pending", now, now + ttl_seconds)
    storage.save_json(user_id, _key(approval.approval_id), approval.__dict__)
    return approval


def read_approval(storage: PrivateStorage, user_id: str, approval_id: str) -> Approval:
    data = storage.read_json(user_id, _key(approval_id))
    return Approval(**data)


def approve(storage: PrivateStorage, user_id: str, approval_id: str, action: str, resource_id: str, payload: dict) -> Approval:
    current = read_approval(storage, user_id, approval_id)
    if current.status != "pending":
        raise ApprovalError("approval is no longer pending")
    if current.expires_at < time.time():
        raise ApprovalError("approval has expired")
    if current.action != action or current.resource_id != resource_id:
        raise ApprovalError("approval target mismatch")
    if current.fingerprint != _fingerprint(action, resource_id, payload):
        raise ApprovalError("approval payload mismatch")
    updated = Approval(**{**current.__dict__, "status": "approved"})
    storage.save_json(user_id, _key(approval_id), updated.__dict__)
    return updated


def consume(storage: PrivateStorage, user_id: str, approval_id: str, action: str, resource_id: str, payload: dict) -> None:
    current = approve(storage, user_id, approval_id, action, resource_id, payload)
    consumed = Approval(**{**current.__dict__, "status": "consumed"})
    storage.save_json(user_id, _key(approval_id), consumed.__dict__)
