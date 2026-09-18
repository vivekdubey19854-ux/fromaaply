from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from app.auth import require_user_id
from app.config import settings
from app.orchestrator import load_workflow
from app.storage import PrivateStorage

router=APIRouter(prefix="/v1/workflows",tags=["orchestrator-screenshots"])
storage=PrivateStorage(settings.storage_root)

@router.get("/{workflow_id}/screenshot")
def screenshot(workflow_id:str,user_id:str=Depends(require_user_id)):
    try: workflow=load_workflow(storage,user_id,workflow_id)
    except FileNotFoundError: raise HTTPException(404,"workflow not found")
    key=workflow.get("last_screenshot_key")
    if not key: raise HTTPException(404,"no workflow screenshot available")
    try: data=storage.read(user_id,key)
    except FileNotFoundError: raise HTTPException(404,"workflow screenshot not found")
    return Response(content=data,media_type="image/png",headers={"Cache-Control":"no-store"})
