from __future__ import annotations
import re
from html import unescape
from typing import Any
from urllib.parse import quote_plus,parse_qs,urlparse
import httpx
from app.config import settings
OFFICIAL_DOMAINS={"ssc.gov.in","www.ssc.gov.in"}

def _allowed_url(url:str)->bool:
    try:host=(urlparse(url).hostname or "").lower().rstrip(".")
    except ValueError:return False
    return host in OFFICIAL_DOMAINS or host.endswith(".gov.in")

def _clean_result(item:dict[str,Any])->dict[str,Any]:return {"title":str(item.get("title") or "")[:500],"url":str(item.get("link") or item.get("url") or "")[:2048],"snippet":str(item.get("snippet") or item.get("description") or "")[:1200],"source":str(item.get("source") or "web_search")}

def _ddg_results(html:str,max_results:int)->list[dict[str,str]]:
    results=[];pattern=re.compile(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',re.I|re.S)
    for url,title in pattern.findall(html):
        clean_title=re.sub(r"<[^>]+>","",unescape(title)).strip();clean_url=unescape(url)
        if clean_url.startswith("//duckduckgo.com/l/?") and "uddg=" in clean_url:clean_url=parse_qs(urlparse(clean_url).query).get("uddg",[clean_url])[0]
        results.append(_clean_result({"title":clean_title,"url":clean_url,"source":"duckduckgo"}))
        if len(results)>=max_results:break
    return results

async def search_web(query:str,*,official_only:bool=True,max_results:int=8)->dict[str,Any]:
    if settings.serper_api_key:
        async with httpx.AsyncClient(timeout=settings.research_timeout_seconds,follow_redirects=True) as client:response=await client.post(settings.serper_url,headers={"X-API-KEY":settings.serper_api_key,"Content-Type":"application/json"},json={"q":query,"num":max_results});response.raise_for_status();data=response.json()
        results=[_clean_result(x) for x in data.get("organic",[])];results=[x for x in results if _allowed_url(x["url"])] if official_only else results;return {"status":"ok","query":query,"results":results[:max_results],"provider":"serper"}
    try:
        async with httpx.AsyncClient(timeout=settings.research_timeout_seconds,follow_redirects=True,headers={"User-Agent":"FormwiseAgent/1.0"}) as client:response=await client.get("https://html.duckduckgo.com/html/?q="+quote_plus(query));response.raise_for_status()
        results=_ddg_results(response.text,max_results*2);results=[x for x in results if _allowed_url(x["url"])] if official_only else results;return {"status":"ok","query":query,"results":results[:max_results],"provider":"duckduckgo"}
    except httpx.HTTPError as exc:return {"status":"unavailable","query":query,"results":[],"message":f"Web research failed: {exc.__class__.__name__}"}

async def _fetch_text(url:str)->str:
    if not _allowed_url(url):return ""
    try:
        async with httpx.AsyncClient(timeout=settings.research_timeout_seconds,follow_redirects=True,headers={"User-Agent":"FormwiseAgent/1.0"}) as client:r=await client.get(url);r.raise_for_status()
        if "pdf" in r.headers.get("content-type","").lower() or url.lower().endswith(".pdf"):
            try:
                import fitz
                return "\n".join(page.get_text() for page in fitz.open(stream=r.content,filetype="pdf"))
            except Exception:return ""
        return re.sub(r"\s+"," ",re.sub(r"<[^>]+>"," ",r.text))[:100000]
    except httpx.HTTPError:return ""

def _facts(text:str)->dict[str,Any]:
    clean=re.sub(r"\s+"," ",text or "")
    def find(pattern):
        m=re.search(pattern,clean,re.I)
        return m.group(1).strip() if m else None
    fee=find(r"Fee\s+payable\s*[:\-]?\s*(?:Rs\.?\s*)?([0-9]+(?:\.[0-9]+)?)")
    app=find(r"Dates?\s+for\s+submission\s+of\s+online\s+applications?\s*([0-9./-]{8,10}\s+to\s+[0-9./-]{8,10})")
    closing=find(r"Last\s+date.*?receipt.*?applications?.{0,120}?([0-9./-]{8,10})")
    age=find(r"age\s+limit.*?\b(\d{1,2}\s+to\s+\d{1,2})\s+years")
    exam=find(r"Schedule\s+of\s+(?:Computer\s+Based\s+)?Examination.*?([A-Za-z]+\s*[–-]\s*[A-Za-z]+\s*20?\d{2}|[A-Za-z]+\s+20?\d{2})")
    education="Class 12 / 10+2 or equivalent" if re.search(r"12th|10\+2|higher secondary",clean,re.I) else None
    return {"application_window":app,"last_date":closing,"fee_rupees":fee,"age_limit":age,"tentative_exam_schedule":exam,"education_requirement":education}

async def research_exam(exam_name:str,year:int)->dict[str,Any]:
    # The demo target is deliberately explicit and never mixed with real government research.
    if exam_name.strip().lower() in {"formwise demo","demo form","local demo"}:
        return {"status":"ok","exam":"Formwise Demo","year":year,"notification_found":True,"notification":{"title":"Formwise Local Demo Application","url":"http://localhost:5000/","snippet":"Local-only test target; no real application is submitted."},"apply_url":"http://localhost:5000/","sources":[{"title":"Formwise Local Demo Application","url":"http://localhost:5000/","snippet":"Safe local end-to-end test target.","source":"local_demo"}],"facts":{"application_window":"Local test only","last_date":None,"fee_rupees":None,"age_limit":None,"tentative_exam_schedule":None,"education_requirement":"Demo only"},"message":"This is a local safety test target.","provider":"local_demo","must_verify_before_submission":True}
    query=f"site:ssc.gov.in {exam_name} {year} notification eligibility application dates fee";result=await search_web(query,official_only=True,max_results=10);results=result.get("results",[]);notification=next((x for x in results if any(t in x["title"].lower() for t in ("notice","notification","combined higher secondary"))),None)
    apply_candidates=[x for x in results if any(t in (x["title"]+" "+x["snippet"]).lower() for t in ("apply online","application","registration","login")) and "pdf" not in x["url"].lower()];apply_url=apply_candidates[0]["url"] if apply_candidates else "https://ssc.gov.in/"
    source_text=await _fetch_text(notification["url"]) if notification else "";facts=_facts(source_text)
    return {"status":result["status"],"exam":exam_name,"year":year,"notification_found":notification is not None,"notification":notification,"apply_url":apply_url,"sources":results,"facts":facts,"message":result.get("message"),"provider":result.get("provider"),"must_verify_before_submission":True}
