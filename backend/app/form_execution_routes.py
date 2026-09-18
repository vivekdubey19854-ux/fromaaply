from __future__ import annotations
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from sqlalchemy.orm import Session
from app.auth import require_user_id
from app.approval_engine import ApprovalError
from app.config import settings
from app.database import get_db
from app.form_execution import approval_for_sensitive_fill,execute_form,plan_form
from app.storage import PrivateStorage
router=APIRouter(prefix="/v1/e2e",tags=["end-to-end-form-agent"]);storage=PrivateStorage(settings.storage_root)
class PlanRequest(BaseModel): session_id:str=Field(min_length=1,max_length=128);instruction:str=Field(min_length=1,max_length=1000)
class FillItem(BaseModel): index:int=Field(ge=0,le=199);field:str=Field(min_length=1,max_length=100);value:str=Field(min_length=1,max_length=2000);source_type:str|None=None;source_id:str|None=None;document_id:str|None=None;approval_id:str|None=None
class ExecuteRequest(BaseModel): session_id:str=Field(min_length=1,max_length=128);fills:list[FillItem]=Field(max_length=100)
class ApprovalRequest(BaseModel): session_id:str=Field(min_length=1,max_length=128);item:FillItem;ttl_seconds:int=Field(default=600,ge=30,le=3600)
@router.post("/plan")
async def plan(payload:PlanRequest,user_id:str=Depends(require_user_id),db:Session=Depends(get_db)):
    try:return await plan_form(user_id,payload.session_id,payload.instruction,storage,db)
    except FileNotFoundError:raise HTTPException(409,"knowledge index not found; reindex the knowledge base first")
    except KeyError:raise HTTPException(404,"browser session not found")
    except Exception as exc:raise HTTPException(400,str(exc)) from exc
@router.post("/approvals")
def request_sensitive_approval(payload:ApprovalRequest,user_id:str=Depends(require_user_id)):
    item=payload.item.model_dump();item["ttl_seconds"]=payload.ttl_seconds
    try:approval=approval_for_sensitive_fill(user_id,payload.session_id,item,storage)
    except (ApprovalError,KeyError,ValueError) as exc:raise HTTPException(400,str(exc)) from exc
    return {"approval_id":approval.approval_id,"action":approval.action,"resource_id":approval.resource_id,"status":approval.status,"expires_at":approval.expires_at}
@router.post("/fill")
async def fill(payload:ExecuteRequest,user_id:str=Depends(require_user_id),db:Session=Depends(get_db)):
    try:return await execute_form(user_id,payload.session_id,[x.model_dump() for x in payload.fills],storage,db)
    except KeyError:raise HTTPException(404,"browser session not found")
    except Exception as exc:raise HTTPException(400,str(exc)) from exc
