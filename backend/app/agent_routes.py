from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.agent_api import AgentPlanRequest, AgentPlanResponse
from app.agent_reasoning import plan_from_knowledge
from app.auth import require_user_id
from app.config import settings
from app.database import get_db
from app.db_models import AuditLogRecord
from app.knowledge_base import load_user_index
from app.storage import PrivateStorage

router = APIRouter(prefix="/v1/agent", tags=["agent"])
storage = PrivateStorage(settings.storage_root)


def _load_chunks(user_id: str) -> list[dict]:
    try:
        return load_user_index(storage, user_id).get("chunks", [])
    except FileNotFoundError:
        return []


@router.post("/plan", response_model=AgentPlanResponse)
def create_plan(payload: AgentPlanRequest, user_id: str = Depends(require_user_id), db: Session = Depends(get_db)):
    result = plan_from_knowledge(payload.instruction, _load_chunks(user_id), payload.top_k)
    db.add(AuditLogRecord(user_id=user_id, action="agent.plan_created", resource_type="agent_plan", resource_id=None))
    db.commit()
    return {"instruction": payload.instruction, **result}
