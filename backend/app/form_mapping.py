from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

FIELD_ALIASES={
"full_name":("full name","fullname","applicant name","candidate name","name","नाम"),
"first_name":("first name","firstname","given name","प्रथम नाम"),
"last_name":("last name","lastname","surname","family name","उपनाम"),
"father_name":("father name","father's name","fathername","पिता का नाम"),
"mother_name":("mother name","mother's name","mothername","माता का नाम"),
"date_of_birth":("date of birth","dob","birth date","birthdate","जन्म तिथि"),
"gender":("gender","sex","लिंग"),
"nationality":("nationality","citizenship","राष्ट्रीयता"),
"category":("category","reservation category","social category","वर्ग","श्रेणी"),
"marital_status":("marital status","marital","वैवाहिक स्थिति"),
"email":("email","email address","e-mail"),
"phone":("phone","mobile","mobile number","telephone","contact number","मोबाइल"),
"aadhaar_number":("aadhaar","aadhaar number","aadhar","uid","uidai"),
"pan_number":("pan","pan number","permanent account number"),
"address":("address","permanent address","current address","mailing address","पता"),
"city":("city","town","शहर"),
"district":("district","जिला"),
"state":("state","province","राज्य"),
"country":("country","देश"),
"postal_code":("pin","pincode","pin code","postal code","zip","zip code"),
"qualification":("qualification","highest qualification","educational qualification","शैक्षिक योग्यता"),
"institution":("institution","school","college","university","board","संस्थान","विद्यालय","महाविद्यालय"),
"roll_number":("roll number","roll no","rollno","रोल नंबर"),
"registration_number":("registration number","registration no","application number","पंजीकरण संख्या"),
"passing_year":("passing year","year of passing","पासिंग ईयर"),
"experience":("experience","work experience","years of experience","अनुभव"),
"designation":("designation","job title","position","पद"),
"photo":("photo","photograph","passport photo","profile photo","फोटो"),
"signature":("signature","sign","signature image","हस्ताक्षर"),
}
SENSITIVE_FIELDS={"aadhaar_number","pan_number","date_of_birth","address","phone","email","gender","father_name","mother_name","nationality","category","marital_status","registration_number","roll_number"}
SELF_HEAL_EXECUTION_THRESHOLD=.86

@dataclass(frozen=True)
class FieldCandidate:
    field:str; score:float; reason:str; self_healed:bool=False

def normalize(value:str|None)->str:return re.sub(r"[^a-z0-9]+"," ",(value or "").lower()).strip()
def _deterministic_text(c:dict)->str:return " ".join(str(c.get(k) or "") for k in ("name","id","autocomplete","placeholder","type"))
def infer_field(control:dict)->FieldCandidate|None:
    text=normalize(_deterministic_text(control));typ=normalize(control.get("type"));ac=normalize(control.get("autocomplete"));matches=[]
    for field,aliases in FIELD_ALIASES.items():
        for alias in aliases:
            a=normalize(alias)
            if a and re.search(rf"(?<![a-z0-9]){re.escape(a)}(?![a-z0-9])",text):matches.append((len(a),field,alias))
    if matches:
        _,field,alias=max(matches,key=lambda x:x[0]);return FieldCandidate(field,.98,f"matched deterministic form metadata: {alias}")
    if ac in {"name","given-name","family-name"}:return FieldCandidate({"name":"full_name","given-name":"first_name","family-name":"last_name"}[ac],.90,f"autocomplete={ac}")
    if ac=="email" or typ=="email":return FieldCandidate("email",.88,"email control metadata")
    if ac in {"tel","tel-national"} or typ=="tel":return FieldCandidate("phone",.86,"telephone control metadata")
    if typ=="date":return FieldCandidate("date_of_birth",.72,"date input; confirmation required")
    return None

def _tokens(value:str)->set[str]:return {x for x in normalize(value).split() if len(x)>1}
def _semantic_score(field:str,control:dict)->tuple[float,str]:
    aliases=[normalize(x) for x in FIELD_ALIASES.get(field,())];raw_sources=(("ariaLabel",5.0),("label",5.0),("nearbyText",4.0),("placeholder",3.5),("text",2.0),("name",1.5),("id",1.0),("type",1.0));best=0.0;best_source="semantic cues"
    for key,weight in raw_sources:
        raw=normalize(str(control.get(key) or ""))
        if not raw:continue
        for alias in aliases:
            if alias and (raw==alias or re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])",raw)):
                score=min(.99,.94*(weight/5.0))
                if score>best:best=score;best_source=key
                continue
            tokens=_tokens(raw);alias_tokens=_tokens(alias)
            if not tokens or not alias_tokens:continue
            overlap=len(tokens & alias_tokens)/max(1,len(tokens | alias_tokens));fuzzy=SequenceMatcher(None,raw,alias).ratio();score=min(.93,(.70*overlap+.30*fuzzy)*(weight/5.0))
            if score>best:best=score;best_source=key
    return best,best_source

def resolve_field_mapping(field:str,controls:list[dict],preferred_index:int|None=None)->FieldCandidate|None:
    if preferred_index is not None and 0<=preferred_index<len(controls):
        direct=infer_field(controls[preferred_index])
        if direct and direct.field==field:return FieldCandidate(field,direct.score,f"{direct.reason}; control index={preferred_index}",False)
    ranked=[]
    for index,control in enumerate(controls):
        candidate=infer_field(control)
        if candidate and candidate.field==field:
            ranked.append((candidate.score,index,f"{candidate.reason}; control index={index}",False));continue
        score,source=_semantic_score(field,control)
        if score>=.82:ranked.append((score,index,f"self-healed from semantic {source} context; control index={index}",True))
    ranked.sort(reverse=True)
    if not ranked:return None
    winner=ranked[0];runner=ranked[1][0] if len(ranked)>1 else 0.0
    if winner[0]>=SELF_HEAL_EXECUTION_THRESHOLD and winner[0]-runner>=.10:return FieldCandidate(field,winner[0],winner[2],winner[3])
    return None

def map_controls(controls:list[dict])->list[dict]:
    out=[]
    for i,c in enumerate(controls):
        x=infer_field(c)
        if x is None:
            candidates=[]
            for field in FIELD_ALIASES:
                score,source=_semantic_score(field,c)
                if score>=SELF_HEAL_EXECUTION_THRESHOLD:candidates.append((score,field,source))
            candidates.sort(reverse=True)
            if candidates and (len(candidates)==1 or candidates[0][0]-candidates[1][0]>=.10):
                score,field,source=candidates[0];x=FieldCandidate(field,score,f"self-healed semantic match: {source}",True)
        out.append({"index":i,"field":x.field if x else None,"confidence":x.score if x else 0.0,"reason":x.reason if x else "no deterministic or semantic match","requires_approval":bool(x and x.field in SENSITIVE_FIELDS),"self_healed":bool(x and x.self_healed),"requires_verified_gateway":bool(x and x.self_healed and x.score>=SELF_HEAL_EXECUTION_THRESHOLD)})
    return out

def is_high_confidence_self_heal(candidate:dict|FieldCandidate|None)->bool:
    """Return whether a recovered field must fetch its value through the gateway."""
    if candidate is None:return False
    if isinstance(candidate,FieldCandidate):
        return candidate.self_healed and candidate.score>=SELF_HEAL_EXECUTION_THRESHOLD
    return bool(candidate.get("self_healed")) and float(candidate.get("confidence",0.0))>=SELF_HEAL_EXECUTION_THRESHOLD
