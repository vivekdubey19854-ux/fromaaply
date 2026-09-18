from __future__ import annotations
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from app.auth import require_user_id
from app.universal_research import discover_target

router=APIRouter(prefix="/v1/universal",tags=["universal-form-agent"])
class ResearchRequest(BaseModel):
    command:str=Field(min_length=2,max_length=1000)
    provided_url:str|None=Field(default=None,max_length=2048)

@router.post("/research")
async def research(payload:ResearchRequest,user_id:str=Depends(require_user_id)):
    return await discover_target(payload.command,payload.provided_url)
