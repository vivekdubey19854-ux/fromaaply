from pydantic import BaseModel, Field


class ApprovalCreateRequest(BaseModel):
    action: str = Field(min_length=1, max_length=50)
    resource_id: str = Field(min_length=1, max_length=100)
    payload: dict = Field(default_factory=dict)
    ttl_seconds: int = Field(default=600, ge=30, le=3600)


class ApprovalResponse(BaseModel):
    approval_id: str
    action: str
    resource_id: str
    status: str
    created_at: float
    expires_at: float


class ApprovalExecuteRequest(BaseModel):
    action: str = Field(min_length=1, max_length=50)
    resource_id: str = Field(min_length=1, max_length=100)
    payload: dict = Field(default_factory=dict)
