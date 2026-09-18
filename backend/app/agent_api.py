from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class AgentPlanRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=8, ge=1, le=20)


class AgentFieldCandidate(BaseModel):
    field: str
    value: str
    source_type: str
    source_id: str
    confidence: float = Field(ge=0, le=1)
    reason: str


class AgentPlanResponse(BaseModel):
    schema_version: str
    instruction: str
    status: str
    action: str
    requires_approval: bool
    candidates: list[AgentFieldCandidate]
    warnings: list[str]


class AgentDecisionRequest(BaseModel):
    field: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=1000)
    source_type: str = Field(min_length=1, max_length=50)
    source_id: str = Field(min_length=1, max_length=100)
    confidence: float = Field(ge=0, le=1)
