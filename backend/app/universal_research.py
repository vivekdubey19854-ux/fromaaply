from __future__ import annotations
from typing import Any
from urllib.parse import urlparse
import re
import httpx
from app.config import settings


def _url_ok(url: str) -> bool:
    try:
        p=urlparse(url.strip())
        return p.scheme in {"http","https"} and bool(p.hostname) and not p.username and not p.password
    except ValueError:
        return False


def _clean(x: dict[str, Any]) -> dict[str, str]:
    return {"title":str(x.get("title") or "")[:500],"url":str(x.get("link") or x.get("url") or "")[:2048],"snippet":str(x.get("snippet") or x.get("description") or "")[:1500]}


def _domain(url: str) -> str:
    return (urlparse(url).hostname or "").lower().rstrip(".")

async def discover_target(command: str, provided_url: str | None = None) -> dict[str, Any]:
    """Universal target discovery. No site is hardcoded; a user-supplied URL wins."""
    if provided_url:
        if not _url_ok(provided_url):
            return {"status":"needs_clarification","needs_user_url":True,"message":"Please provide a valid http(s) form URL without embedded credentials."}
        return {"status":"ready","needs_user_url":False,"query":command,"official_url":provided_url.strip(),"application_form_url":provided_url.strip(),"results":[],"verification_required":True,"message":"User supplied the target URL. Formwise will inspect the live page before filling."}
    query=f'"{command.strip()}" application form official apply online'
    results: list[dict[str,str]]=[]
    provider="none"
    if settings.serper_api_key:
        try:
            async with httpx.AsyncClient(timeout=settings.research_timeout_seconds,follow_redirects=True) as client:
                r=await client.post(settings.serper_url,headers={"X-API-KEY":settings.serper_api_key,"Content-Type":"application/json"},json={"q":query,"num":10});r.raise_for_status();data=r.json()
            results=[_clean(x) for x in data.get("organic",[]) if _url_ok(str(x.get("link") or x.get("url") or ""))][:10];provider="serper"
        except httpx.HTTPError:
            results=[]
    if not results:
        try:
            from urllib.parse import quote_plus
            async with httpx.AsyncClient(timeout=settings.research_timeout_seconds,follow_redirects=True,headers={"User-Agent":"FormwiseAgent/1.0"}) as client:
                r=await client.get("https://html.duckduckgo.com/html/?q="+quote_plus(query));r.raise_for_status()
            pattern=re.compile(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',re.I|re.S)
            for url,title in pattern.findall(r.text):
                title=re.sub(r"<[^>]+>","",title).strip()
                if _url_ok(url): results.append({"title":title[:500],"url":url[:2048],"snippet":""})
                if len(results)>=10: break
            provider="duckduckgo"
        except httpx.HTTPError:
            return {"status":"needs_clarification","needs_user_url":True,"query":command,"results":[],"provider":"unavailable","verification_required":True,"message":"I could not confidently find the exact form. Please paste the form URL so I can verify it."}
    # Prefer application-looking results but never claim that a search result is official merely by its title.
    ranked=sorted(results,key=lambda x:(0 if any(k in (x["title"]+" "+x["snippet"]).lower() for k in ("apply","application","registration","admission","careers","form")) else 1))
    target=ranked[0] if ranked else None
    if not target:
        return {"status":"needs_clarification","needs_user_url":True,"query":command,"results":[],"provider":provider,"verification_required":True,"message":"Exact form link not found. Please paste the URL."}
    return {"status":"needs_verification","needs_user_url":False,"query":command,"official_url":target["url"],"application_form_url":target["url"],"results":ranked,"provider":provider,"domain":_domain(target["url"]),"verification_required":True,"message":"I found a likely target. Please verify the site/form before Formwise continues."}
