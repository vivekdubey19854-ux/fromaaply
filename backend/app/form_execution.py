from __future__ import annotations
from typing import Any
import re
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.agent_reasoning import _extract_value
from app.approval_engine import SENSITIVE_FIELDS, ApprovalError, consume, create_approval
from app.browser_agent import BrowserSafetyError, get_session, inspect_session, upload_control
from app.db_models import DocumentRecord
from app.form_mapping import is_high_confidence_self_heal, map_controls, resolve_field_mapping
from app.knowledge_base import load_user_index
from app.storage import PrivateStorage
from app.user_data import get_user_data
from app.verified_data_repository import VerifiedDataRepository
from app.verified_data_service import VerifiedDataService

BLOCKED_PAGE_TERMS={"payment","pay now","final submission","legal declaration","i agree","anti-bot","anti bot","bot verification"}

def _control_text(control:dict[str,Any])->str:return " ".join(str(control.get(k, "")) for k in ("text","ariaLabel","placeholder","name","id","autocomplete","label","nearbyText")).lower()
def _page_signals(inspection:dict[str,Any])->dict[str,list[str]]:
    blocked=set();human=set()
    for control in inspection.get("controls",[]):
        text=_control_text(control);typ=str(control.get("type","")).lower();value=str(control.get("value") or "")
        if any(term in text for term in ("captcha","recaptcha","hcaptcha")) and not value:human.add("captcha")
        if ("otp" in text or "one time password" in text or control.get("autocomplete") in {"one-time-code","one-time-password"}) and not value:human.add("otp")
        if "payment" in text or "pay now" in text or "banking" in text:blocked.add("payment")
        if "declaration" in text or "i agree" in text or "self attestation" in text:blocked.add("legal declaration")
        if "anti-bot" in text or "anti bot" in text or "bot verification" in text:blocked.add("anti-bot")
        if typ=="submit" and any(term in text for term in ("final submission","final submit","submit application","confirm and submit","complete application")):blocked.add("final submission")
    page_text=(inspection.get("title","")+" "+inspection.get("url","")).lower()
    if "payment" in page_text or "pay now" in page_text or "banking" in page_text:blocked.add("payment")
    if "anti-bot" in page_text or "anti bot" in page_text or "bot verification" in page_text:blocked.add("anti-bot")
    return {"blocked":sorted(blocked),"human":sorted(human)}
def _blocked_page(inspection:dict[str,Any])->list[str]:return _page_signals(inspection)["blocked"]
def _resolve_value(field:str,chunks:list[dict[str,Any]])->dict[str,Any]|None:
    candidates=[];seen=set()
    for chunk in chunks:
        value=_extract_value(field,str(chunk.get("text","")))
        if value and value not in seen:
            seen.add(value);candidates.append({"field":field,"value":value,"source_type":chunk.get("source_type","unknown"),"source_id":chunk.get("source_id","unknown"),"confidence":float(chunk.get("score",0.0))})
    if len(candidates)==1:return candidates[0]
    if len(candidates)>1:
        exact=[x for x in candidates if x["confidence"]>=0.5]
        if len(exact)==1:return exact[0]
    return None

def _document_proposal(field:str,db:Session,user_id:str)->dict[str,Any]|None:
    if field not in {"photo","signature"}:return None
    rows=db.scalars(select(DocumentRecord).where(DocumentRecord.user_id==user_id,DocumentRecord.status!="deleted")).all()
    matches=[r for r in rows if (field=="photo" and ("photo" in r.original_filename.lower() or "passport" in r.original_filename.lower())) or (field=="signature" and ("signature" in r.original_filename.lower() or "sign" in r.original_filename.lower()))]
    if len(matches)==1:
        r=matches[0];return {"field":field,"value":r.original_filename,"source_type":"document","source_id":r.id,"document_id":r.id,"confidence":1.0}
    return None

def _gateway(db:Session|None)->VerifiedDataService|None:
    return VerifiedDataService(VerifiedDataRepository(db)) if db is not None else None

def _verified_gateway_value(service:VerifiedDataService,user_id:str,field:str)->dict[str,Any]:
    result=service.get_requested_field(user_id=user_id,requested_field=field)
    if result.status == "conflict":
        return {"status":"paused","reason":result.reason or "verified data conflict; human confirmation required"}
    if result.status != "verified" or result.value is None:
        return {"status":"paused","reason":result.reason or "verified data not found; no value may be filled"}
    return {"status":"verified","field":result.field,"value":result.value,"confidence":result.confidence,"source_type":result.source_type,"source_id":result.source_id,"provenance_id":result.provenance_id}

async def plan_form(user_id:str,session_id:str,instruction:str,storage:PrivateStorage,db:Session|None=None)->dict[str,Any]:
    session=get_session(session_id,user_id);inspection=await inspect_session(session);signals=_page_signals(inspection);mappings=map_controls(inspection["controls"]);proposals=[];knowledge_chunks=None;gateway=_gateway(db)
    for mapping in mappings:
        field=mapping.get("field")
        if not field or mapping.get("confidence",0)<0.70 or inspection["controls"][mapping["index"]].get("disabled"):continue
        value=None
        # A high-confidence self-healed target is never populated from the
        # knowledge index. It must make a single-field request to the verified
        # gateway, and any conflict/missing value pauses the plan.
        if is_high_confidence_self_heal(mapping):
            if gateway is None:
                return {"status":"paused","reason":"verified data gateway requires database context","session_id":session_id,"url":inspection["url"],"title":inspection["title"],"mappings":mappings,"proposals":[],"fills":[],"blocked_signals":signals["blocked"],"human_required":signals["human"],"submission_allowed":False}
            verified=_verified_gateway_value(gateway,user_id,field)
            if verified["status"] != "verified":
                return {"status":"paused","reason":verified["reason"],"field":field,"session_id":session_id,"url":inspection["url"],"title":inspection["title"],"mappings":mappings,"proposals":[],"fills":[],"blocked_signals":signals["blocked"],"human_required":signals["human"],"submission_allowed":False}
            value=verified
        elif db:value=get_user_data(db,storage,user_id,field)
        if value is None and db and field in {"photo","signature"}:value=_document_proposal(field,db,user_id)
        if value is None:
            if knowledge_chunks is None:knowledge_chunks=load_user_index(storage,user_id).get("chunks",[])
            value=_resolve_value(field,knowledge_chunks)
        if value:proposals.append({**value,"index":mapping["index"],"requires_approval":field in SENSITIVE_FIELDS,"reason":mapping.get("reason"),"self_healed":bool(mapping.get("self_healed")),"verified_gateway":is_high_confidence_self_heal(mapping)})
    fills=[dict(item) for item in proposals]
    status="blocked" if signals["blocked"] else ("ready" if proposals else "needs_clarification")
    return {"status":status,"instruction":instruction,"session_id":session_id,"url":inspection["url"],"title":inspection["title"],"mappings":mappings,"proposals":proposals,"fills":fills,"blocked_signals":signals["blocked"],"human_required":signals["human"],"submission_allowed":False,"warnings":["User data is fetched on-demand only for a mapped field.","High-confidence self-healed fields are resolved only through VerifiedDataService.","CONFLICT or NOT_FOUND from the verified gateway pauses the workflow; no fallback value is used.","Only stored values with provenance are proposed.","No value is invented.","Sensitive fields require explicit approval.","CAPTCHA and OTP are human gates; they are never solved by Formwise.","Payment, anti-bot bypass, legal declarations and final submission are never automated.","Semantic self-healing may remap a changed DOM target only when confidence is high and ambiguity is low."]}

async def execute_form(user_id:str,session_id:str,fills:list[dict[str,Any]],storage:PrivateStorage,db:Session|None=None)->dict[str,Any]:
    session=get_session(session_id,user_id);inspection=await inspect_session(session);blocked=_blocked_page(inspection)
    if blocked:return {"status":"blocked","filled":[],"blocked":[{"reason":"safety signal detected","signals":blocked}],"submission_allowed":False}
    mappings=map_controls(inspection["controls"]);results=[];blocked_items=[];gateway=_gateway(db)
    for item in fills[:100]:
        try:requested_idx=int(item["index"]);field=str(item["field"]);value=str(item["value"])
        except (KeyError,TypeError,ValueError):blocked_items.append({"reason":"invalid fill request"});continue
        idx=requested_idx;stale=idx<0 or idx>=len(mappings) or mappings[idx].get("field")!=field
        if stale:
            healed=resolve_field_mapping(field,inspection["controls"],preferred_index=requested_idx)
            if healed is None:
                blocked_items.append({"index":requested_idx,"field":field,"reason":"mapping is stale and semantic self-healing was ambiguous"});continue
            if field in SENSITIVE_FIELDS:
                blocked_items.append({"index":requested_idx,"field":field,"reason":"sensitive mapping changed; re-plan and re-approve the healed target"});continue
            match=re.search(r"control index=(\d+)",healed.reason)
            if not match:
                blocked_items.append({"index":requested_idx,"field":field,"reason":"self-healing produced no executable target"});continue
            idx=int(match.group(1))
            if healed.score<.86:
                blocked_items.append({"index":requested_idx,"field":field,"reason":"self-healing confidence below execution threshold"});continue
        # Re-fetch a high-confidence self-healed value immediately before any
        # mutation. The value in the client-supplied fill is never trusted.
        mapping=mappings[idx] if 0<=idx<len(mappings) else {}
        if is_high_confidence_self_heal(mapping):
            if gateway is None:
                blocked_items.append({"index":idx,"field":field,"reason":"verified data gateway requires database context"});continue
            verified=_verified_gateway_value(gateway,user_id,field)
            if verified["status"] != "verified":
                blocked_items.append({"index":idx,"field":field,"reason":verified["reason"],"status":"paused"});continue
            if verified["value"] != value:
                blocked_items.append({"index":idx,"field":field,"reason":"verified value changed since planning; re-plan and re-approve before filling","status":"paused"});continue
            value=verified["value"]
            item_source={"source_type":verified.get("source_type"),"source_id":verified.get("source_id"),"provenance_id":verified.get("provenance_id"),"confidence":verified.get("confidence")}
        else:
            item_source={"source_type":item.get("source_type"),"source_id":item.get("source_id")}
        if field in SENSITIVE_FIELDS:
            approval_id=item.get("approval_id")
            if not approval_id:blocked_items.append({"index":idx,"field":field,"reason":"explicit approval is required"});continue
            payload={"index":idx,"field":field,"value":value,"session_id":session_id}
            try:consume(storage,user_id,str(approval_id),"fill_sensitive",session_id,payload)
            except (ApprovalError,KeyError,FileNotFoundError) as exc:blocked_items.append({"index":idx,"field":field,"reason":str(exc)});continue
        if idx<0 or idx>=len(inspection["controls"]):blocked_items.append({"index":idx,"field":field,"reason":"resolved control is outside current page"});continue
        control=inspection["controls"][idx]
        if control.get("value") and field not in {"photo","signature"}:blocked_items.append({"index":idx,"field":field,"reason":"existing value detected; silent overwrite is blocked"});continue
        try:
            if field in {"photo","signature"}:
                if not db:raise BrowserSafetyError("document upload requires database context")
                doc_id=str(item.get("document_id") or item.get("source_id") or "");row=db.get(DocumentRecord,doc_id)
                if not row or row.user_id!=user_id or row.status=="deleted":raise BrowserSafetyError("document is not available for this user")
                result=await upload_control(session,idx,str(storage.key_path(user_id,row.storage_key)))
            else:
                from app.browser_agent import fill_control
                result=await fill_control(session,idx,value)
            results.append({**result,"field":field,"self_healed":bool(stale or mapping.get("self_healed")),"provenance":item_source})
        except (BrowserSafetyError,ValueError) as exc:blocked_items.append({"index":idx,"field":field,"reason":str(exc)})
    signals=_page_signals(await inspect_session(session))
    return {"status":"ok" if results else "no_change","filled":results,"blocked":blocked_items,"human_required":signals["human"],"submission_allowed":False,"review_required":True,"warning":"Review the page after filling. Formwise never clicks final submit and never bypasses CAPTCHA, OTP, payment or legal declarations."}

def approval_for_sensitive_fill(user_id:str,session_id:str,item:dict[str,Any],storage:PrivateStorage):
    field=str(item.get("field",""))
    if field not in SENSITIVE_FIELDS:raise ApprovalError("approval is only needed for sensitive fields")
    payload={"index":int(item["index"]),"field":field,"value":str(item["value"]),"session_id":session_id}
    return create_approval(storage,user_id,"fill_sensitive",session_id,payload,int(item.get("ttl_seconds",600)))
