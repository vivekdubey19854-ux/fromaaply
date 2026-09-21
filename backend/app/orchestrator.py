from __future__ import annotations
import re,time,uuid
from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.approval_engine import consume,create_approval
from app.browser_agent import fill_control,get_session,inspect_session,screenshot_session
from app.db_models import AuditLogRecord,DocumentRecord,ProfileRecord
from app.form_execution import execute_form,plan_form
from app.universal_research import discover_target
from app.storage import PrivateStorage
WORKFLOW_KEY="workflows/{workflow_id}.json"
def _key(workflow_id:str)->str:return WORKFLOW_KEY.format(workflow_id=workflow_id)
def _save(storage:PrivateStorage,user_id:str,workflow:dict[str,Any])->None:storage.save_json(user_id,_key(workflow["workflow_id"]),workflow)
def load_workflow(storage:PrivateStorage,user_id:str,workflow_id:str)->dict[str,Any]:return storage.read_json(user_id,_key(workflow_id))
def _audit(db:Session,user_id:str,action:str,workflow_id:str)->None:db.add(AuditLogRecord(user_id=user_id,action=action,resource_type="workflow",resource_id=workflow_id));db.commit()
def _doc_kind(filename:str)->str:
    name=filename.lower()
    if any(x in name for x in ("10th","matric","class10","class 10","highschool")):return "education_10th"
    if any(x in name for x in ("12th","12 marksheet","12th marksheet","class12","class 12","inter","intermediate")):return "education_12th"
    if any(x in name for x in ("aadhaar","aadhar","uid")):return "identity"
    if "pan" in name:return "pan"
    if any(x in name for x in ("caste","sc","st","obc","ews")):return "category_certificate"
    if any(x in name for x in ("photo","passport")):return "photo"
    if any(x in name for x in ("signature","sign")):return "signature"
    return "other"
def _document_checklist(db:Session,user_id:str,storage:PrivateStorage,research:dict[str,Any]|None=None)->dict[str,Any]:
    rows=db.scalars(select(DocumentRecord).where(DocumentRecord.user_id==user_id,DocumentRecord.status!="deleted")).all()
    kinds=set(); extracted=[]
    for row in rows:
        kind=_doc_kind(row.original_filename); kinds.add(kind)
        try:
            data=storage.read_json(user_id,f"{row.storage_key}.extraction.json")
            fields=data.get("fields",[])
            extracted.append({"document_id":row.id,"filename":row.original_filename,"status":data.get("status"),"fields":[f.get("name") for f in fields if f.get("name")],"engine":data.get("engine")})
        except FileNotFoundError:
            extracted.append({"document_id":row.id,"filename":row.original_filename,"status":"not_extracted","fields":[]})
    required_source=(research or {}).get("required_documents") or (research or {}).get("requiredDocuments") or []
    normalized=[];seen_keys=set()
    for item in required_source if isinstance(required_source,list) else []:
        if isinstance(item,str):
            key=_doc_kind(item);label=item.strip()
        elif isinstance(item,dict):
            key=str(item.get("key") or item.get("type") or item.get("name") or "other").strip().lower()
            label=str(item.get("label") or item.get("name") or key)
        else:
            continue
        if not key or key in seen_keys:
            continue
        normalized.append({"key":key,"label":label,"required":True});seen_keys.add(key)
    missing=[x for x in normalized if x["key"] not in kinds]
    not_extracted=[x for x in extracted if x["status"]=="not_extracted"]
    profile=db.get(ProfileRecord,user_id)
    profile_missing=[field for field in ("full_name","date_of_birth","gender","email","phone") if not getattr(profile,field,None)]
    advisory=[] if normalized else ["No research-declared document requirements were available; Formwise will inspect live upload controls instead of imposing a fixed document checklist."]
    return {"documents":[{"key":x["key"],"label":x["label"],"present":x["key"] not in {m["key"] for m in missing}} for x in normalized],"extracted_documents":extracted,"missing_documents":missing,"documents_needing_ocr":not_extracted,"missing_profile_fields":profile_missing,"advisories":advisory,"ready":not missing and not not_extracted and not profile_missing}


def _otp_control(inspection:dict[str,Any])->int|None:
    for c in inspection.get("controls",[]):
        hay=" ".join(str(c.get(k) or "") for k in ("name","id","placeholder","ariaLabel","autocomplete","text")).lower()
        if ("otp" in hay or "one time password" in hay or c.get("autocomplete") in {"one-time-code","one-time-password"}) and not c.get("value"):return int(c["index"])
    return None
def _human_control(inspection:dict[str,Any],kind:str)->int|None:
    for c in inspection.get("controls",[]):
        hay=" ".join(str(c.get(k) or "") for k in ("name","id","placeholder","ariaLabel","autocomplete","text")).lower()
        if kind=="captcha" and not c.get("value") and any(x in hay for x in ("captcha","recaptcha","hcaptcha")):return int(c["index"])
        if kind=="otp" and _otp_control({"controls":[c]}) is not None:return int(c["index"])
    return None
def _final_submit_control(inspection:dict[str,Any])->int|None:
    candidates=[]
    for c in inspection.get("controls",[]):
        typ=str(c.get("type") or "").lower()
        if typ not in {"submit","button"}:continue
        text=" ".join(str(c.get(k) or "") for k in ("text","ariaLabel","name","id")).lower()
        if any(x in text for x in ("submit application","final submit","confirm and submit","submit form","complete application")) or (typ=="submit" and text.strip() in {"submit","submit form"}):candidates.append(int(c["index"]))
    return candidates[0] if len(candidates)==1 else None
async def start_workflow(db:Session,storage:PrivateStorage,user_id:str,instruction:str)->dict[str,Any]:
    low=instruction.lower();demo="formwise demo" in low or "demo form" in low
    if demo:exam="Formwise Demo";year=time.gmtime().tm_year
    else:
        match=re.search(r"(?:ssc\s*)?(chsl|combined higher secondary).*?(20\d{2})",low) or re.search(r"chsl.*?(20\d{2})",low);exam="SSC CHSL" if "chsl" in low else instruction.strip()[:120];year=int(match.group(2) if match and match.lastindex and match.lastindex>=2 else (match.group(1) if match else time.gmtime().tm_year))
    research=await __import__('app.research',fromlist=['research_exam']).research_exam(exam,year);workflow={"workflow_id":uuid.uuid4().hex,"user_id":user_id,"instruction":instruction,"exam":exam,"year":year,"state":"research_ready","created_at":time.time(),"research":research,"document_check":None,"session_id":None,"last_screenshot_key":None,"history":[]};_save(storage,user_id,workflow);_audit(db,user_id,"workflow.research_completed",workflow["workflow_id"]);return workflow
def confirm_research(db:Session,storage:PrivateStorage,user_id:str,workflow_id:str,confirmed:bool)->dict[str,Any]:
    workflow=load_workflow(storage,user_id,workflow_id)
    if workflow["state"] not in {"research_ready","documents_missing"}:raise ValueError("workflow is not awaiting document/research confirmation")
    if not confirmed:workflow["state"]="cancelled";_save(storage,user_id,workflow);_audit(db,user_id,"workflow.cancelled",workflow_id);return workflow
    check=_document_checklist(db,user_id,storage);workflow["document_check"]=check;workflow["state"]="documents_ready" if check["ready"] else "documents_missing";workflow["history"].append({"event":"checklist_confirmed","at":time.time()});_save(storage,user_id,workflow);_audit(db,user_id,"workflow.document_check_completed",workflow_id);return workflow
async def open_application(db:Session,storage:PrivateStorage,user_id:str,workflow_id:str,resume:bool=False)->dict[str,Any]:
    workflow=load_workflow(storage,user_id,workflow_id)
    allowed_states={"documents_ready","browser_ready","form_review","otp_required","captcha_required","final_review"}
    if workflow["state"]!="documents_ready" and not (resume and workflow["state"] in allowed_states):raise ValueError("complete the missing profile/document checklist first")
    from app.browser_agent import create_session
    target=workflow["research"].get("apply_url") or workflow["research"].get("application_form_url")
    if not target:raise ValueError("approved application URL is required")
    session=await create_session(user_id,target);inspection=await inspect_session(session);workflow["session_id"]=session.session_id;workflow["state"]="browser_ready";workflow["history"].append({"event":"application_opened","url":inspection["url"],"at":time.time()});_save(storage,user_id,workflow);_audit(db,user_id,"workflow.browser_opened",workflow_id);return {**workflow,"inspection":inspection}
async def submit_human_gate(db:Session,storage:PrivateStorage,user_id:str,workflow_id:str,kind:str,value:str)->dict[str,Any]:
    if kind not in {"otp","captcha"}:raise ValueError("only OTP or CAPTCHA can be supplied as a human gate")
    workflow=load_workflow(storage,user_id,workflow_id);session_id=workflow.get("session_id")
    if not session_id:raise ValueError("browser session not started")
    if kind=="otp" and not re.fullmatch(r"\d{4,8}",value):raise ValueError("OTP must be 4-8 digits")
    if kind=="captcha" and not re.fullmatch(r"[A-Za-z0-9 ]{1,32}",value):raise ValueError("invalid CAPTCHA input")
    session=get_session(session_id,user_id);inspection=await inspect_session(session);idx=_human_control(inspection,kind)
    if idx is None:raise ValueError(f"{kind} field is not awaiting human input")
    await fill_control(session,idx,value);shot=await screenshot_session(session);key=f"workflow/{workflow_id}/{kind}-{uuid.uuid4().hex}.png";storage.save(user_id,key,shot);workflow["last_screenshot_key"]=key;workflow["state"]="browser_ready";workflow["history"].append({"event":f"{kind}_entered_by_user","at":time.time()});_save(storage,user_id,workflow);_audit(db,user_id,f"workflow.{kind}_entered",workflow_id);return {**workflow,"inspection":await inspect_session(session),"human_gate":kind,"field_index":idx}
async def prepare_form(db:Session,storage:PrivateStorage,user_id:str,workflow_id:str)->dict[str,Any]:
    workflow=load_workflow(storage,user_id,workflow_id);session_id=workflow.get("session_id")
    if not session_id:raise ValueError("browser session not started")
    plan=await plan_form(user_id,session_id,workflow["instruction"],storage,db);workflow["state"]="form_review" if plan["status"]=="ready" else plan["status"];workflow["plan"]=plan;workflow["history"].append({"event":"form_plan_created","at":time.time()});_save(storage,user_id,workflow);_audit(db,user_id,"workflow.form_plan_created",workflow_id);return {**workflow,"plan":plan}
async def fill_form(db:Session,storage:PrivateStorage,user_id:str,workflow_id:str,fills:list[dict[str,Any]])->dict[str,Any]:
    workflow=load_workflow(storage,user_id,workflow_id);session_id=workflow["session_id"];all_results=[];all_blocked=[];screens=[]
    for item in fills:
        result=await execute_form(user_id,session_id,[item],storage,db);all_results.extend(result.get("filled",[]));all_blocked.extend(result.get("blocked",[]))
        try:shot=await screenshot_session(get_session(session_id,user_id));key=f"workflow/{workflow_id}/step-{len(screens)+1}-{uuid.uuid4().hex}.png";storage.save(user_id,key,shot);screens.append(key)
        except Exception:pass
    fresh=await plan_form(user_id,session_id,workflow["instruction"],storage,db);result={"status":"ok" if all_results else "no_change","filled":all_results,"blocked":all_blocked,"submission_allowed":False,"review_required":True,"screenshots":screens,"human_required":fresh.get("human_required",[])};workflow["state"]="final_review" if all_results and not fresh.get("human_required") else ("otp_required" if "otp" in fresh.get("human_required",[]) else "captcha_required" if "captcha" in fresh.get("human_required",[]) else workflow.get("state"));workflow["last_screenshot_key"]=screens[-1] if screens else workflow.get("last_screenshot_key");workflow["result"]=result;workflow["history"].append({"event":"form_filled","filled":len(all_results),"screenshots":len(screens),"at":time.time()});_save(storage,user_id,workflow);_audit(db,user_id,"workflow.form_filled",workflow_id);return {**workflow,"result":result}
def request_final_approval(storage:PrivateStorage,user_id:str,workflow_id:str)->dict[str,Any]:
    workflow=load_workflow(storage,user_id,workflow_id)
    if workflow.get("state")!="final_review":raise ValueError("workflow is not ready for final review")
    return {"approval_id":None,"manual_action_required":True,"message":"PAUSED: Final submission is never clicked automatically. Review the form and click the final Submit/Confirm button yourself.","workflow_id":workflow_id,"screenshot_key":workflow.get("last_screenshot_key")}
async def final_submit(db:Session,storage:PrivateStorage,user_id:str,workflow_id:str,approval_id:str)->dict[str,Any]:
    workflow=load_workflow(storage,user_id,workflow_id)
    if workflow.get("state")!="final_review":raise ValueError("final review is required before manual submission")
    session=get_session(workflow["session_id"],user_id);inspection=await inspect_session(session)
    if _otp_control(inspection) is not None or _human_control(inspection,"captcha") is not None:raise ValueError("human verification is still pending; OTP/CAPTCHA must be completed first")
    idx=_final_submit_control(inspection)
    if idx is None:raise ValueError("final submit control is not uniquely identifiable; no submission action was taken")
    return {"status":"paused","submitted":False,"manual_action_required":True,"message":"PAUSED: Final submission is disabled for automation. Please review the completed form and click the final Submit/Confirm button manually.","field_index":idx,"url":inspection["url"],"screenshot_key":workflow.get("last_screenshot_key")}

# Universal entry point: any government, private, education, district or state portal.
async def start_workflow(db:Session,storage:PrivateStorage,user_id:str,instruction:str,provided_url:str|None=None)->dict[str,Any]:
    research=await discover_target(instruction,provided_url)
    if research.get("application_form_url"): research["apply_url"]=research["application_form_url"]
    workflow={"workflow_id":uuid.uuid4().hex,"user_id":user_id,"instruction":instruction,"state":"awaiting_url" if research.get("needs_user_url") else "research_ready","created_at":time.time(),"research":research,"document_check":None,"session_id":None,"last_screenshot_key":None,"history":[]}
    _save(storage,user_id,workflow);_audit(db,user_id,"workflow.research_completed",workflow["workflow_id"]);return workflow

async def set_target_url(db:Session,storage:PrivateStorage,user_id:str,workflow_id:str,url:str)->dict[str,Any]:
    workflow=load_workflow(storage,user_id,workflow_id);research=await discover_target(workflow["instruction"],url)
    if research.get("application_form_url"): research["apply_url"]=research["application_form_url"]
    workflow["research"]=research;workflow["state"]="research_ready" if research.get("status") in {"ready","needs_verification"} else "awaiting_url";workflow["history"].append({"event":"target_url_provided","at":time.time()});_save(storage,user_id,workflow);_audit(db,user_id,"workflow.target_url_provided",workflow_id);return workflow
