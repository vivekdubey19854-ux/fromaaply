from pydantic import BaseModel, Field

class FormMapRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)

class FormFillRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=64)
    mappings: list[dict] = Field(default_factory=list, max_length=100)
    dry_run: bool = True
