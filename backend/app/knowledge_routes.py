from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import require_user_id
from app.config import settings
from app.database import get_db
from app.db_models import AuditLogRecord
from app.knowledge_api import KnowledgeContextResponse, KnowledgeReindexResponse, KnowledgeResult, KnowledgeSearchRequest, KnowledgeSearchResponse
from app.knowledge_base import build_user_index, load_user_index, rank_chunks, save_user_index
from app.storage import PrivateStorage

router = APIRouter(prefix="/v1/knowledge", tags=["knowledge-base"])
storage = PrivateStorage(settings.storage_root)


def _audit(db: Session, user_id: str, action: str) -> None:
    db.add(AuditLogRecord(user_id=user_id, action=action, resource_type="knowledge_index", resource_id=None))


def _load_or_empty(user_id: str) -> dict:
    try:
        return load_user_index(storage, user_id)
    except FileNotFoundError:
        return {"schema_version": "1", "user_id": user_id, "chunks": []}


def _results(query: str, top_k: int, user_id: str) -> list[KnowledgeResult]:
    index = _load_or_empty(user_id)
    ranked = rank_chunks(query, index.get("chunks", []), top_k)
    return [KnowledgeResult(**item) for item in ranked]


@router.post("/reindex", response_model=KnowledgeReindexResponse)
def reindex_knowledge(user_id: str = Depends(require_user_id), db: Session = Depends(get_db)):
    index = build_user_index(db, user_id, storage)
    save_user_index(storage, user_id, index)
    _audit(db, user_id, "knowledge.reindexed")
    db.commit()
    return {"schema_version": index["schema_version"], "indexed_chunks": len(index["chunks"])}


@router.post("/search", response_model=KnowledgeSearchResponse)
def search_knowledge(payload: KnowledgeSearchRequest, user_id: str = Depends(require_user_id), db: Session = Depends(get_db)):
    results = _results(payload.query, payload.top_k, user_id)
    _audit(db, user_id, "knowledge.searched")
    db.commit()
    return {"schema_version": "1", "query": payload.query, "results": results}


@router.post("/context", response_model=KnowledgeContextResponse)
def get_knowledge_context(payload: KnowledgeSearchRequest, user_id: str = Depends(require_user_id), db: Session = Depends(get_db)):
    results = _results(payload.query, payload.top_k, user_id)
    max_chars = 6000
    selected: list[KnowledgeResult] = []
    used = 0
    parts: list[str] = []
    for result in results:
        prefix = f"[{result.source_type}:{result.source_id}]\n"
        remaining = max_chars - used - len(prefix)
        if remaining <= 0:
            break
        text = result.text[:remaining]
        selected.append(result.model_copy(update={"text": text}))
        parts.append(prefix + text)
        used += len(prefix) + len(text)
    _audit(db, user_id, "knowledge.context_retrieved")
    db.commit()
    return {"schema_version": "1", "query": payload.query, "context": "\n\n".join(parts), "sources": selected}
