from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class KnowledgeReindexResponse(BaseModel):
    schema_version: str
    indexed_chunks: int = Field(ge=0)


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=8, ge=1, le=20)


class KnowledgeResult(BaseModel):
    score: float = Field(ge=0)
    source_type: str
    source_id: str
    chunk_index: int = Field(ge=0)
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeSearchResponse(BaseModel):
    schema_version: str
    query: str
    results: list[KnowledgeResult]


class KnowledgeContextResponse(BaseModel):
    schema_version: str
    query: str
    context: str
    sources: list[KnowledgeResult]
