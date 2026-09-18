from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from app.auth import require_user_id
from app.browser_agent import BrowserSafetyError, BrowserSessionNotFound, get_session, inspect_session, fill_control
from app.form_mapping import map_controls, SENSITIVE_FIELDS

router=APIRouter(prefix='/v1/forms',tags=['form-agent'])

@router.post('/map')
async def map_form(session_id:str, user_id:str=Depends(require_user_id)):
    try: session=get_session(session_id,user_id); inspection=await inspect_session(session)
    except BrowserSessionNotFound as exc: raise HTTPException(404,'browser session not found') from exc
    mapped=map_controls(inspection['controls'])
    return {'status':'ok','session_id':session_id,'url':inspection['url'],'title':inspection['title'],'controls':inspection['controls'],'mappings':mapped,'submission_allowed':False}

@router.post('/fill')
async def fill_form(session_id:str,mappings:list[dict],confirm_sensitive:bool=False,user_id:str=Depends(require_user_id)):
    try: session=get_session(session_id,user_id)
    except BrowserSessionNotFound as exc: raise HTTPException(404,'browser session not found') from exc
    if len(mappings)>100: raise HTTPException(400,'too many mappings')
    results=[]; blocked=[]
    for item in mappings:
        try: index=int(item.get('index')); field=str(item.get('field') or ''); value=item.get('value')
        except (TypeError,ValueError): blocked.append({'reason':'invalid mapping'}); continue
        if not field or not isinstance(value,str): blocked.append({'index':index,'reason':'field and string value required'}); continue
        if field in SENSITIVE_FIELDS and not confirm_sensitive:
            blocked.append({'index':index,'field':field,'reason':'explicit sensitive-field approval required'}); continue
        try: results.append(await fill_control(session,index,value))
        except (BrowserSafetyError,ValueError) as exc: blocked.append({'index':index,'field':field,'reason':str(exc)})
    return {'status':'ok','filled':results,'blocked':blocked,'submission_allowed':False,'warning':'This endpoint only fills controls. It never clicks submit and never bypasses CAPTCHA, OTP, payment or legal declarations.'}
