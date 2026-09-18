from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import AddressRecord, DocumentRecord, EducationRecord, ProfileRecord
from app.storage import PrivateStorage

INDEX_VERSION = "1"
DEFAULT_CHUNK_SIZE = 1200
DEFAULT_OVERLAP = 150


def split_chunks(text: str, size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_OVERLAP) -> list[str]:
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError("invalid chunk settings")
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return chunks


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower(), flags=re.UNICODE))


def rank_chunks(query: str, chunks: list[dict[str, Any]], top_k: int = 8) -> list[dict[str, Any]]:
    query_tokens = _tokens(query)
    if not query_tokens:
        return []
    ranked: list[dict[str, Any]] = []
    for chunk in chunks:
        chunk_tokens = _tokens(str(chunk.get("text", "")))
        if not chunk_tokens:
            continue
        overlap = len(query_tokens & chunk_tokens)
        if overlap == 0:
            continue
        item = dict(chunk)
        item["score"] = round(overlap / len(query_tokens), 6)
        ranked.append(item)
    ranked.sort(key=lambda item: (-item["score"], item.get("chunk_index", 0)))
    return ranked[:top_k]


def _profile_chunks(profile: ProfileRecord) -> list[dict[str, Any]]:
    values = {
        "full_name": profile.full_name,
        "date_of_birth": profile.date_of_birth.isoformat() if profile.date_of_birth else None,
        "gender": profile.gender,
        "email": profile.email,
        "phone": profile.phone,
    }
    text = "Profile: " + "; ".join(f"{key}: {value}" for key, value in values.items() if value)
    return _make_source_chunks(text, "profile", profile.user_id, {"fields": [k for k, v in values.items() if v]})


def _make_source_chunks(text: str, source_type: str, source_id: str, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"source_type": source_type, "source_id": source_id, "chunk_index": i, "text": chunk, "metadata": metadata}
        for i, chunk in enumerate(split_chunks(text))
    ]


def build_user_index(db: Session, user_id: str, storage: PrivateStorage) -> dict[str, Any]:
    chunks: list[dict[str, Any]] = []
    profile = db.get(ProfileRecord, user_id)
    if profile:
        chunks.extend(_profile_chunks(profile))
    for row in db.scalars(select(AddressRecord).where(AddressRecord.user_id == user_id)).all():
        text = f"Address ({row.label}): {row.line1}; {row.line2 or ''}; {row.city or ''}; {row.state or ''}; {row.postal_code or ''}; {row.country}"
        chunks.extend(_make_source_chunks(text, "address", row.id, {"label": row.label}))
    for row in db.scalars(select(EducationRecord).where(EducationRecord.user_id == user_id)).all():
        text = f"Education: qualification: {row.qualification}; institution: {row.institution or ''}; board/university: {row.board_university or ''}; passing year: {row.passing_year or ''}; percentage/CGPA: {row.percentage_or_cgpa or ''}"
        chunks.extend(_make_source_chunks(text, "education", row.id, {"qualification": row.qualification}))
    for doc in db.scalars(select(DocumentRecord).where(DocumentRecord.user_id == user_id, DocumentRecord.status != "deleted")).all():
        try:
            extraction = storage.read_json(user_id, f"{doc.storage_key}.extraction.json")
        except (FileNotFoundError, ValueError):
            continue
        fields = extraction.get("fields", [])
        field_text = "; ".join(f"{f.get('name')}: {f.get('value')}" for f in fields if f.get("name") and f.get("value"))
        if field_text:
            chunks.extend(_make_source_chunks(f"Document {doc.original_filename}: {field_text}", "document_field", doc.id, {"filename": doc.original_filename, "document_sha256": doc.sha256}))
        raw_text = str(extraction.get("text") or "")
        if raw_text:
            chunks.extend(_make_source_chunks(raw_text, "document_text", doc.id, {"filename": doc.original_filename, "document_sha256": doc.sha256, "engine": extraction.get("engine", "unknown")}))
    return {"schema_version": INDEX_VERSION, "user_id": user_id, "chunks": chunks}


def index_key() -> str:
    return "knowledge/index.json"


def save_user_index(storage: PrivateStorage, user_id: str, index: dict[str, Any]) -> None:
    storage.save_json(user_id, index_key(), index)


def load_user_index(storage: PrivateStorage, user_id: str) -> dict[str, Any]:
    return storage.read_json(user_id, index_key())
