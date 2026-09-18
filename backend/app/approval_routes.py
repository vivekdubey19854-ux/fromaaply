from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.approval_api import ApprovalCreateRequest, ApprovalExecuteRequest, ApprovalResponse
from app.approval_engine import ApprovalError, approve, create_approval, read_approval
from app.auth import require_user_id
from app.config import settings
from app.database import get_db
from app.db_models import AuditLogRecord
from app.storage import PrivateStorage

router = APIRouter(prefix="/v1/approvals", tags=["approval-safety"])
storage = PrivateStorage(settings.storage_root)


def audit(db: Session, user_id: str, action: str, resource_id: str) -> None:
    db.add(AuditLogRecord(user_id=user_id, action=action, resource_type="approval", resource_id=resource_id))
    db.commit()


def response(a):
    return ApprovalResponse(
        approval_id=a.approval_id,
        action=a.action,
        resource_id=a.resource_id,
        status=a.status,
        created_at=a.created_at,
        expires_at=a.expires_at,
    )


@router.post("", response_model=ApprovalResponse, status_code=201)
def request_approval(payload: ApprovalCreateRequest, user_id: str = Depends(require_user_id), db: Session = Depends(get_db)):
    try:
        approval = create_approval(storage, user_id, payload.action, payload.resource_id, payload.payload, payload.ttl_seconds)
    except ApprovalError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit(db, user_id, "approval.requested", approval.approval_id)
    return response(approval)


@router.get("/{approval_id}", response_model=ApprovalResponse)
def get_approval(approval_id: str, user_id: str = Depends(require_user_id)):
    try:
        return response(read_approval(storage, user_id, approval_id))
    except (KeyError, FileNotFoundError):
        raise HTTPException(status_code=404, detail="approval not found")


@router.post("/{approval_id}/approve", response_model=ApprovalResponse)
def approve_request(approval_id: str, payload: ApprovalExecuteRequest, user_id: str = Depends(require_user_id), db: Session = Depends(get_db)):
    try:
        approval = approve(storage, user_id, approval_id, payload.action, payload.resource_id, payload.payload)
    except (KeyError, FileNotFoundError):
        raise HTTPException(status_code=404, detail="approval not found")
    except ApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit(db, user_id, "approval.approved", approval_id)
    return response(approval)
