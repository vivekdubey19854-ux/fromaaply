from __future__ import annotations
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field
from sqlalchemy.orm import Session
from app.auth import require_user_id
from app.config import settings
from app.database import get_db
from app.orchestrator import confirm_research,fill_form,final_submit,load_workflow,open_application,prepare_form,request_final_approval,set_target_url,start_workflow,submit_human_gate
from app.storage import PrivateStorage
router=APIRouter(prefix="/v1/workflows",tags=["orchestrator"]);storage=PrivateStorage(settings.storage_root)
class StartRequest(BaseModel): instruction:str=Field(min_length=3,max_length=1000);provided_url:str|None=Field(default=None,max_length=2048)
class ConfirmRequest(BaseModel): confirmed:bool
class OtpRequest(BaseModel): otp:str=Field(min_length=4,max_length=8)
class HumanGateRequest(BaseModel): kind:str=Field(pattern="^(otp|captcha)$"); value:str=Field(min_length=1,max_length=32)
class FillRequest(BaseModel): fills:list[dict]=Field(max_length=100)
class FinalSubmitRequest(BaseModel): approval_id:str=Field(min_length=10,max_length=200)
class UrlRequest(BaseModel): url:str=Field(min_length=8,max_length=2048)
def _error(exc:Exception): raise HTTPException(status_code=409,detail=str(exc)) from exc
@router.post("",status_code=201)
async def start(payload:StartRequest,user_id:str=Depends(require_user_id),db:Session=Depends(get_db)):
    try:return await start_workflow(db,storage,user_id,payload.instruction,payload.provided_url)
    except Exception as exc:_error(exc)
@router.get("/{workflow_id}")
def get(workflow_id:str,user_id:str=Depends(require_user_id)):
    try:return load_workflow(storage,user_id,workflow_id)
    except FileNotFoundError:raise HTTPException(404,"workflow not found")
@router.post("/{workflow_id}/url")
async def provide_url(workflow_id:str,payload:UrlRequest,user_id:str=Depends(require_user_id),db:Session=Depends(get_db)):
    try:return await set_target_url(db,storage,user_id,workflow_id,payload.url)
    except Exception as exc:_error(exc)
@router.post("/{workflow_id}/confirm")
def confirm(workflow_id:str,payload:ConfirmRequest,user_id:str=Depends(require_user_id),db:Session=Depends(get_db)):
    try:return confirm_research(db,storage,user_id,workflow_id,payload.confirmed)
    except Exception as exc:_error(exc)
@router.post("/{workflow_id}/open")
async def open_app(workflow_id:str,user_id:str=Depends(require_user_id),db:Session=Depends(get_db)):
    try:return await open_application(db,storage,user_id,workflow_id)
    except Exception as exc:_error(exc)
@router.post("/{workflow_id}/human")
async def human(workflow_id:str,payload:HumanGateRequest,user_id:str=Depends(require_user_id),db:Session=Depends(get_db)):
    try:return await submit_human_gate(db,storage,user_id,workflow_id,payload.kind,payload.value)
    except Exception as exc:_error(exc)
@router.post("/{workflow_id}/otp")
async def otp(workflow_id:str,payload:OtpRequest,user_id:str=Depends(require_user_id),db:Session=Depends(get_db)):
    try:return await submit_human_gate(db,storage,user_id,workflow_id,"otp",payload.otp)
    except Exception as exc:_error(exc)
@router.post("/{workflow_id}/plan")
async def plan(workflow_id:str,user_id:str=Depends(require_user_id),db:Session=Depends(get_db)):
    try:return await prepare_form(db,storage,user_id,workflow_id)
    except Exception as exc:_error(exc)
@router.post("/{workflow_id}/fill")
async def fill(workflow_id:str,payload:FillRequest,user_id:str=Depends(require_user_id),db:Session=Depends(get_db)):
    try:return await fill_form(db,storage,user_id,workflow_id,payload.fills)
    except Exception as exc:_error(exc)
@router.post("/{workflow_id}/final-approval")
def final_approval(workflow_id:str,user_id:str=Depends(require_user_id)):
    try:return request_final_approval(storage,user_id,workflow_id)
    except Exception as exc:_error(exc)
@router.post("/{workflow_id}/submit")
async def submit(workflow_id:str,payload:FinalSubmitRequest,user_id:str=Depends(require_user_id),db:Session=Depends(get_db)):
    try:return await final_submit(db,storage,user_id,workflow_id,payload.approval_id)
    except Exception as exc:_error(exc)
