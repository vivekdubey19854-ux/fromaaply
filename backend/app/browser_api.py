from pydantic import BaseModel, Field


class BrowserStartRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2048)


class BrowserNavigateRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2048)


class BrowserSessionResponse(BaseModel):
    session_id: str
    url: str
    title: str
    status: str
    submission_allowed: bool
    warnings: list[str]


class BrowserNavigateResponse(BaseModel):
    status: str
    url: str
    http_status: int | None


class BrowserInspectResponse(BaseModel):
    session_id: str
    url: str
    title: str
    forms: list[dict]
    controls: list[dict]
    submission_allowed: bool
    warnings: list[str]


class BrowserScreenshotResponse(BaseModel):
    session_id: str
    content_type: str
    storage_key: str
    size_bytes: int
