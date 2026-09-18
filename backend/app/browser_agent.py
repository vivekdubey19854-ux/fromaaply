from __future__ import annotations
import asyncio, ipaddress, socket, time, uuid
from dataclasses import dataclass
from urllib.parse import urlparse
from playwright.async_api import Browser,BrowserContext,Page,Playwright,Route,Request,async_playwright
from app.config import settings
class BrowserSafetyError(ValueError): pass
class BrowserSessionNotFound(KeyError): pass
@dataclass
class BrowserSession:
    session_id:str; user_id:str; browser:Browser; context:BrowserContext; page:Page; created_at:float; last_used_at:float
_SESSIONS={}; _LOCK=asyncio.Lock(); _PLAYWRIGHT=None

def _is_blocked_ip(address):
    ip=ipaddress.ip_address(address); return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified

def _is_local_demo_url(parsed):
    return settings.environment != "production" and settings.browser_allow_local_demo_target and parsed.hostname in {"localhost","127.0.0.1"} and (parsed.port or 80) == settings.browser_demo_target_port

def validate_navigation_url(url):
    parsed=urlparse(url.strip())
    if parsed.scheme not in {'http','https'} or not parsed.hostname: raise BrowserSafetyError('only http(s) URLs with a hostname are allowed')
    if parsed.username or parsed.password: raise BrowserSafetyError('URLs containing embedded credentials are blocked')
    hostname=parsed.hostname.rstrip('.').lower(); local_demo=_is_local_demo_url(parsed)
    if hostname in {'localhost','localhost.localdomain','127.0.0.1','::1'} and not local_demo: raise BrowserSafetyError('local destinations are blocked')
    if settings.browser_block_private_networks and not local_demo:
        try: addresses={x[4][0] for x in socket.getaddrinfo(hostname,parsed.port or (443 if parsed.scheme=='https' else 80),type=socket.SOCK_STREAM)}
        except socket.gaierror as exc: raise BrowserSafetyError('destination hostname could not be resolved') from exc
        if not addresses or any(_is_blocked_ip(a) for a in addresses): raise BrowserSafetyError('private or otherwise unsafe network destinations are blocked')
    return url.strip()
async def _guard_request(route:Route,request:Request):
    try: validate_navigation_url(request.url)
    except BrowserSafetyError: await route.abort('blockedbyclient'); return
    await route.continue_()
async def _get_playwright():
    global _PLAYWRIGHT
    if _PLAYWRIGHT is None: _PLAYWRIGHT=await async_playwright().start()
    return _PLAYWRIGHT
async def _close_session(session):
    await session.context.close(); await session.browser.close(); _SESSIONS.pop(session.session_id,None)
async def create_session(user_id,url):
    safe_url=validate_navigation_url(url)
    async with _LOCK:
        if len([s for s in _SESSIONS.values() if s.user_id==user_id])>=settings.browser_max_sessions_per_user: raise BrowserSafetyError('maximum active browser sessions reached')
        browser=await (await _get_playwright()).chromium.launch(headless=settings.browser_headless)
        context=await browser.new_context(java_script_enabled=True,accept_downloads=False,permissions=[],service_workers='block')
        await context.route('**/*',_guard_request); page=await context.new_page(); page.set_default_timeout(settings.browser_timeout_ms); page.set_default_navigation_timeout(settings.browser_navigation_timeout_ms)
        session=BrowserSession(uuid.uuid4().hex,user_id,browser,context,page,time.time(),time.time()); _SESSIONS[session.session_id]=session
        try: await page.goto(safe_url,wait_until='domcontentloaded'); validate_navigation_url(page.url)
        except Exception: await _close_session(session); raise
        return session
def get_session(session_id,user_id):
    s=_SESSIONS.get(session_id)
    if s is None or s.user_id!=user_id: raise BrowserSessionNotFound(session_id)
    s.last_used_at=time.time(); return s
async def inspect_session(session):
    page=session.page; title=await page.title(); url=validate_navigation_url(page.url)
    controls=await page.locator('input, textarea, select, button').evaluate_all("""els=>els.slice(0,200).map((el,index)=>{const labels=[];if(el.labels) for(const x of el.labels) labels.push((x.innerText||x.textContent||'').trim());const parent=el.closest('label');if(parent) labels.push((parent.innerText||parent.textContent||'').trim());let nearby='';const wrapper=el.closest('div,section,fieldset,td,li');if(wrapper) nearby=(wrapper.innerText||wrapper.textContent||'').replace(/\\s+/g,' ').trim().slice(0,300);return {index,tag:el.tagName.toLowerCase(),type:el.getAttribute('type')||null,name:el.getAttribute('name')||null,id:el.id||null,autocomplete:el.getAttribute('autocomplete')||null,placeholder:el.getAttribute('placeholder')||null,ariaLabel:el.getAttribute('aria-label')||null,label:labels.join(' ').slice(0,300),nearbyText:nearby,text:(el.innerText||el.value||'').slice(0,120),required:el.hasAttribute('required'),disabled:el.hasAttribute('disabled'),value:el.type==='file'?'':(el.value||'')};})""")
    forms=await page.locator('form').evaluate_all("""forms=>forms.slice(0,50).map((form,index)=>({index,action:form.getAttribute('action')||null,method:(form.getAttribute('method')||'get').toLowerCase(),fields:form.querySelectorAll('input,textarea,select').length}))""")
    return {'url':url,'title':title[:500],'forms':forms,'controls':controls,'submission_allowed':False,'warnings':['Inspection/fill are non-submitting operations.','CAPTCHA and anti-bot controls must not be bypassed.','OTP, payment, legal declarations and final submission require explicit approval.','Semantic self-healing uses accessibility labels and nearby context; ambiguous matches fail closed.']}
async def navigate_session(session,url):
    safe_url=validate_navigation_url(url); response=await session.page.goto(safe_url,wait_until='domcontentloaded'); return {'status':'ok','url':validate_navigation_url(session.page.url),'http_status':response.status if response else None}
async def screenshot_session(session):
    if not settings.browser_screenshot_enabled: raise BrowserSafetyError('browser screenshots are disabled')
    return await session.page.screenshot(type='png',full_page=True)
async def fill_control(session,index,value):
    if not isinstance(value,str) or len(value)>2000: raise BrowserSafetyError('invalid field value')
    locator=session.page.locator('input, textarea, select, button').nth(index)
    info=await locator.evaluate("el=>({tag:el.tagName.toLowerCase(),type:el.getAttribute('type')||'',disabled:el.disabled})")
    if info['disabled'] or info['tag']=='button' or info['type'] in {'submit','image','reset','file'}: raise BrowserSafetyError('control is not fillable')
    if info['type']=='checkbox' or info['type']=='radio': raise BrowserSafetyError('boolean controls require explicit mapping and are not auto-filled')
    await locator.fill(value); return {'index':index,'filled':True}
async def upload_control(session,index,file_path):
    locator=session.page.locator('input, textarea, select, button').nth(index)
    info=await locator.evaluate("el=>({tag:el.tagName.toLowerCase(),type:el.getAttribute('type')||'',disabled:el.disabled})")
    if info['disabled'] or info['tag']!='input' or info['type']!='file': raise BrowserSafetyError('control is not a file upload control')
    await locator.set_input_files(file_path); return {'index':index,'uploaded':True}
async def close_session(session_id,user_id):
    s=get_session(session_id,user_id)
    async with _LOCK: await _close_session(s)
async def close_all_sessions():
    async with _LOCK:
        for s in list(_SESSIONS.values()): await _close_session(s)
        global _PLAYWRIGHT
        if _PLAYWRIGHT is not None: await _PLAYWRIGHT.stop(); _PLAYWRIGHT=None
