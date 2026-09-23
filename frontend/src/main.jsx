import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';
import StitchShell from './stitch/StitchShell.jsx';
import CoreWorkspaceScreen from './stitch/CoreWorkspaceScreen.jsx';
import DocumentVaultScreen from './stitch/DocumentVaultScreen.jsx';
import MasterKnowledgeScreen from './stitch/MasterKnowledgeScreen.jsx';
import BillingLogsScreen from './stitch/BillingLogsScreen.jsx';
import HumanGatewayScreen from './stitch/HumanGatewayScreen.jsx';
import HumanGatewayModal from './stitch/HumanGatewayModal.jsx';
import './admin/tailwind.css';
import AdminDashboard from './admin/AdminDashboard.tsx';

const API = localStorage.getItem('formwise_api') || 'http://localhost:8000';
const uidKey = 'formwise_user';
const isLocalApi = /^(https?:\/\/)?(localhost|127\.0\.0\.1)(:\d+)?$/i.test(new URL(API, window.location.origin).host);
const getUid = () => localStorage.getItem(uidKey) || `demo-${crypto.randomUUID()}`;
const MAX_UPLOAD = 10 * 1024 * 1024;
const ALLOWED = ['application/pdf','image/jpeg','image/png','image/webp'];
const isAdminSurface = new URLSearchParams(window.location.search).get('admin') === '1';
let accessToken = localStorage.getItem('formwise_access_token') || '';
let tokenPromise = null;
async function refreshSession() {
  const refreshToken = localStorage.getItem('formwise_refresh_token');
  if (!refreshToken) return false;
  const response = await fetch(API + '/v1/auth/refresh', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({refresh_token:refreshToken}) });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || !data.access_token) return false;
  accessToken = data.access_token; localStorage.setItem('formwise_access_token', accessToken);
  if (data.refresh_token) localStorage.setItem('formwise_refresh_token', data.refresh_token);
  if (data.user_id) localStorage.setItem(uidKey, data.user_id);
  return true;
}
async function ensureAccessToken() {
  if (accessToken) return accessToken;
  if (await refreshSession()) return accessToken;
  if (!isLocalApi) throw new Error('Authentication required. Sign in to continue.');
  if (!tokenPromise) {
    tokenPromise = fetch(API + '/v1/auth/dev-token', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: getUid(), ttl_seconds: 3600 }),
    }).then(async response => {
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.access_token) throw new Error(data.detail || 'Development authentication failed.');
      accessToken = data.access_token;
      localStorage.setItem('formwise_access_token', accessToken);
      localStorage.setItem(uidKey, getUid());
      return accessToken;
    }).finally(() => { tokenPromise = null; });
  }
  return tokenPromise;
}

async function api(path, opts = {}) {
  let token = await ensureAccessToken();
  let headers = { Authorization: `Bearer ${token}`, ...(opts.headers || {}) };
  if (opts.body && !(opts.body instanceof FormData) && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
  let response = await fetch(API + path, { ...opts, headers });
  let data = {}; try { data = await response.json(); } catch {}
  if (response.status === 401 && await refreshSession()) {
    token = accessToken; headers = { Authorization: `Bearer ${token}`, ...(opts.headers || {}) }; response = await fetch(API + path, { ...opts, headers }); data = await response.json().catch(() => ({}));
  }
  if (response.status === 401) { localStorage.removeItem('formwise_access_token'); localStorage.removeItem('formwise_refresh_token'); accessToken = ''; }
  if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
  return data;
}

function AuthScreen({ onAuthenticated }) {
  const [mode, setMode] = useState('login'); const [email, setEmail] = useState(''); const [password, setPassword] = useState(''); const [fullName, setFullName] = useState('');
  const [phone, setPhone] = useState(''); const [challengeId, setChallengeId] = useState(''); const [otp, setOtp] = useState(''); const [error, setError] = useState(''); const [busy, setBusy] = useState(false); const [providers, setProviders] = useState([]);
  const finish = data => { accessToken = data.access_token; localStorage.setItem('formwise_access_token', accessToken); if (data.user_id) localStorage.setItem(uidKey, data.user_id); if (data.refresh_token) localStorage.setItem('formwise_refresh_token', data.refresh_token); onAuthenticated(); };
  useEffect(() => {
    fetch(`${API}/v1/auth/providers`).then(r=>r.ok?r.json():{providers:[]}).then(d=>setProviders((d.providers||[]).filter(p=>p.configured && (p.methods||[]).includes('oauth')))).catch(()=>{});
    const code = new URLSearchParams(window.location.search).get('auth_code'); if (!code) return; setBusy(true);
    fetch(`${API}/v1/auth/oauth/exchange`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({code}) }).then(async r => { const data=await r.json().catch(()=>({})); if(!r.ok) throw new Error(data.detail || 'OAuth sign-in failed.'); window.history.replaceState({}, document.title, window.location.pathname); finish(data); }).catch(e=>setError(e.message)).finally(()=>setBusy(false));
  }, []);
  const submit = async event => { event.preventDefault(); setError(''); setBusy(true); try {
    if (mode === 'google') { window.location.href = `${API}/v1/auth/oauth/google/start`; return; }
    if (mode === 'phone') { const r=await fetch(`${API}/v1/auth/otp/request`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({phone})}); const d=await r.json().catch(()=>({})); if(!r.ok) throw new Error(d.detail || 'OTP request failed.'); setChallengeId(d.challenge_id); setMode('verify-phone'); return; }
    if (mode === 'verify-phone') { const r=await fetch(`${API}/v1/auth/otp/verify`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({challenge_id:challengeId,code:otp})}); const d=await r.json().catch(()=>({})); if(!r.ok) throw new Error(d.detail || 'OTP verification failed.'); finish(d); return; }
    if (mode === 'reset') { const r=await fetch(`${API}/v1/auth/password-reset/request`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email})}); const d=await r.json().catch(()=>({})); if(!r.ok) throw new Error(d.detail || 'Password reset request failed.'); setError(d.email_delivery_configured ? 'Reset email sent.' : 'Reset accepted; email provider is not configured.'); return; }
    const r=await fetch(`${API}/v1/auth/${mode === 'signup' ? 'signup' : 'login'}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(mode === 'signup' ? {email,password,full_name:fullName || null} : {email,password})}); const d=await r.json().catch(()=>({})); if(!r.ok) throw new Error(d.detail || 'Authentication failed.'); finish(d);
  } catch (e) { setError(e instanceof Error ? e.message : 'Authentication failed.'); } finally { setBusy(false); } };
  const heading = mode === 'signup' ? 'Create your account' : mode === 'reset' ? 'Reset your password' : mode === 'phone' || mode === 'verify-phone' ? 'Phone verification' : 'Welcome back';
  return <main className="fw-auth-page"><form className="fw-auth-card" onSubmit={submit}><div className="fw-kicker">FORMWISE // SECURE ACCOUNT</div><h1>{heading}</h1><p>Use a verified identity. OTP is sent and checked by the configured provider; Formwise never bypasses CAPTCHA or OTP.</p>
    {(mode === 'login' || mode === 'signup' || mode === 'reset') && <input type="email" required value={email} onChange={e=>setEmail(e.target.value)} placeholder="Email address" autoComplete="email" />}
    {mode === 'signup' && <input value={fullName} onChange={e=>setFullName(e.target.value)} placeholder="Full name" maxLength={200} />}
    {(mode === 'login' || mode === 'signup') && <input type="password" required minLength={12} value={password} onChange={e=>setPassword(e.target.value)} placeholder="Password (12+ characters)" autoComplete={mode === 'signup' ? 'new-password' : 'current-password'} />}
    {mode === 'phone' && <input required value={phone} onChange={e=>setPhone(e.target.value)} placeholder="Phone, e.g. +919876543210" autoComplete="tel" />}
    {mode === 'verify-phone' && <input required inputMode="numeric" value={otp} onChange={e=>setOtp(e.target.value)} placeholder="Enter the OTP you received" autoComplete="one-time-code" />}
    {error && <div className="fw-inline-status">{error}</div>}<button className="fw-neon-btn" disabled={busy}>{busy ? 'PROCESSING…' : mode === 'signup' ? 'CREATE ACCOUNT' : mode === 'reset' ? 'SEND RESET LINK' : mode === 'phone' ? 'SEND OTP' : mode === 'verify-phone' ? 'VERIFY OTP' : 'SIGN IN'}</button>
    {mode === 'login' && <><button type="button" className="fw-link-btn" onClick={()=>{setBusy(true);window.location.href=`${API}/v1/auth/oauth/google/start`;}}>CONTINUE WITH GOOGLE</button>{providers.filter(p=>p.provider !== 'google').map(p=><button key={p.provider} type="button" className="fw-link-btn" onClick={()=>{setBusy(true);window.location.href=`${API}/v1/auth/oauth/${p.provider}/start`;}}>CONTINUE WITH {String(p.display_name||p.provider).toUpperCase()}</button>)}<button type="button" className="fw-link-btn" onClick={()=>setMode('phone')}>SIGN IN WITH PHONE OTP</button><button type="button" className="fw-link-btn" onClick={()=>{setMode('reset');setError('');}}>Forgot password?</button></>}
    {mode === 'verify-phone' && <button type="button" className="fw-link-btn" onClick={()=>{setMode('phone');setError('');}}>Request a new OTP</button>}
    {mode === 'login' || mode === 'reset' ? <button type="button" className="fw-link-btn" onClick={()=>{setMode('signup');setError('');}}>Create a new account</button> : <button type="button" className="fw-link-btn" onClick={()=>{setMode('login');setError('');}}>Back to email login</button>}
  </form></main>;
}

function App() {
  const [view, setView] = useState(isAdminSurface ? 'admin' : 'core');
  const [signedIn, setSignedIn] = useState(Boolean(accessToken) || isLocalApi);
  const [profile, setProfile] = useState({ full_name:'', date_of_birth:'', gender:'', email:'', phone:'' });
  const [docs, setDocs] = useState([]); const [education, setEducation] = useState([]); const [addresses, setAddresses] = useState([]); const [billing, setBilling] = useState(null);
  const [instruction, setInstruction] = useState('SSC ka form bhar do'); const [workflow, setWorkflow] = useState(null); const [approval, setApproval] = useState(null); const [screenshot, setScreenshot] = useState('');
  const [gateValue, setGateValue] = useState(''); const [activeGate, setActiveGate] = useState(null); const [resumeRequest, setResumeRequest] = useState(0); const [status, setStatus] = useState('Ready'); const [busy, setBusy] = useState(false);
  const uid = getUid();
  const load = async () => { try { const [p,d,e,a] = await Promise.all([api('/v1/profile'),api('/v1/documents'),api('/v1/education'),api('/v1/addresses')]); setProfile(p); setDocs(d); setEducation(e); setAddresses(a); } catch (e) { setStatus(e.message); } };
  const loadBilling = async () => { try { setBilling(await api('/v1/billing/summary')); } catch { setBilling(null); } };
  useEffect(() => { if (signedIn && !isAdminSurface) { void load(); void loadBilling(); } }, [signedIn]);
  const saveProfile = async () => { setBusy(true); try { setProfile(await api('/v1/profile',{method:'PUT',body:JSON.stringify(profile)})); setStatus('Profile saved.'); } catch(e) { setStatus(e.message); } finally { setBusy(false); } };
  const upload = async event => { const file=event?.target?.files?.[0]; if(!file)return; if(file.size>MAX_UPLOAD){setStatus('Upload rejected: maximum size is 10MB.');return;} if(!ALLOWED.includes(file.type)&&! /\.(pdf|jpe?g|png|webp)$/i.test(file.name)){setStatus('Upload rejected: allowed types are PDF, JPEG, PNG, WEBP.');return;} setBusy(true); try {const fd=new FormData();fd.append('file',file);const d=await api('/v1/documents',{method:'POST',body:fd});setDocs(x=>[d,...x]);setStatus('Document uploaded securely.');}catch(e){setStatus(e.message);}finally{setBusy(false);} };
  const extract = async id => { setBusy(true); try { await api(`/v1/documents/${id}/extract`,{method:'POST'}); await api('/v1/knowledge/reindex',{method:'POST'}); await load(); setStatus('OCR completed and knowledge index refreshed.'); } catch(e) { setStatus(e.message); } finally { setBusy(false); } };
  const start = async () => { setBusy(true); try { const d=await api('/v1/workflows',{method:'POST',body:JSON.stringify({instruction})});setWorkflow(d);setApproval(null);setScreenshot('');setStatus('Research ready. Review before continuing.'); }catch(e){setStatus(e.message);}finally{setBusy(false);} };
  const confirm = async confirmed => { if(!workflow)return;setBusy(true);try{const d=await api(`/v1/workflows/${workflow.workflow_id}/confirm`,{method:'POST',body:JSON.stringify({confirmed})});setWorkflow(d);setStatus(d.state==='documents_missing'?'Complete the checklist first.':'Documents ready.');}catch(e){setStatus(e.message);}finally{setBusy(false);} };
  const openApp = async () => { if(!workflow)return;setBusy(true);try{const d=await api(`/v1/workflows/${workflow.workflow_id}/open`,{method:'POST'});const p=await api(`/v1/workflows/${d.workflow_id}/plan`,{method:'POST'});setWorkflow(p);setStatus('Target inspected. Review fields and human gates.');}catch(e){setStatus(e.message);}finally{setBusy(false);} };
  const approveField = async item => { if(!workflow)return;setBusy(true);try{const a=await api('/v1/e2e/approvals',{method:'POST',body:JSON.stringify({session_id:workflow.session_id,item,ttl_seconds:600})});const payload={index:item.index,field:item.field,value:item.value,session_id:workflow.session_id};await api(`/v1/approvals/${a.approval_id}/approve`,{method:'POST',body:JSON.stringify({action:'fill_sensitive',resource_id:workflow.session_id,payload})});setWorkflow(p=>({...p,fieldApprovals:{...(p.fieldApprovals||{}),[item.index]:a.approval_id}}));setStatus(`Approved ${item.field}.`);}catch(e){setStatus(e.message);}finally{setBusy(false);} };
  const refreshShot = async currentWorkflow => { try {const response=await fetch(`${API}/v1/workflows/${currentWorkflow.workflow_id}/screenshot`,{headers:{Authorization:`Bearer ${accessToken}`},cache:'no-store'});if(response.ok){if(screenshot)URL.revokeObjectURL(screenshot);setScreenshot(URL.createObjectURL(await response.blob()));}}catch{} };
  const fill = async () => { if(!workflow)return;setBusy(true);try{const fills=(workflow.plan?.fills||[]).filter(x=>!x.requires_approval||workflow.fieldApprovals?.[x.index]).map(x=>({...x,approval_id:workflow.fieldApprovals?.[x.index]}));const d=await api(`/v1/workflows/${workflow.workflow_id}/fill`,{method:'POST',body:JSON.stringify({fills})});setWorkflow(d);await refreshShot(d);setStatus(d.state==='final_review'?'All automated fields filled. Final review required.':'Approved fields filled.');}catch(e){setStatus(e.message);}finally{setBusy(false);} };
  const finalApproval = () => { if(!workflow||workflow.state!=='final_review')return;setApproval({manual_action_required:true,message:"Review the completed form carefully and click the website's final Submit/Confirm button yourself. Formwise never clicks the final submission control."});setStatus('Final review ready. Manual website submission is required.'); };
  const finalSubmit = () => setStatus('Manual action required: click the final Submit/Confirm button on the live website yourself.');
  const onHumanGate = gate => {setActiveGate(gate);setView('core');}; const onLiveControl = state => {if(state.control==='locked'&&state.mode==='ai'&&!state.paused)setActiveGate(null);}; const resumeHuman = () => {setResumeRequest(x=>x+1);setGateValue('');};
  const logout = async () => { try { if (accessToken) await fetch(`${API}/v1/auth/logout`, { method:'POST', headers:{ Authorization:`Bearer ${accessToken}`, 'Content-Type':'application/json' }, body:JSON.stringify({ refresh_token:localStorage.getItem('formwise_refresh_token') }) }); } finally { localStorage.removeItem('formwise_access_token'); localStorage.removeItem('formwise_refresh_token'); accessToken=''; setSignedIn(false); setWorkflow(null); } };
  if (!signedIn && !isAdminSurface) return <AuthScreen onAuthenticated={() => setSignedIn(true)} />;
  if (view === 'admin') return <AdminDashboard />;
  const renderView = () => { if(view==='vault')return <DocumentVaultScreen docs={docs} busy={busy} onUpload={upload} onExtract={extract}/>; if(view==='knowledge')return <MasterKnowledgeScreen profile={profile} education={education} addresses={addresses}/>; if(view==='billing')return <BillingLogsScreen billing={billing} busy={busy} onRefresh={loadBilling}/>; if(view==='human')return <HumanGatewayScreen gate={activeGate} onClose={()=>setView('core')}/>; return <CoreWorkspaceScreen apiBase={API} userId={uid} accessToken={accessToken} workflow={workflow} instruction={instruction} setInstruction={setInstruction} busy={busy} status={status} docs={docs} onStart={start} onConfirm={confirm} onOpen={openApp} onUpload={upload} onExtract={extract} onApprove={approveField} onFill={fill} onFinalApproval={finalApproval} onFinalSubmit={finalSubmit} approval={approval} screenshot={screenshot} onHumanGate={onHumanGate} onLiveControl={onLiveControl} resumeRequest={resumeRequest} saveProfile={saveProfile} />; };
  return <StitchShell view={view} onNavigate={setView} status={status} onLogout={logout}>{renderView()}{activeGate&&<HumanGatewayModal gate={activeGate} gateValue={gateValue} setGateValue={setGateValue} onResume={resumeHuman} onCancel={()=>setView('human')} busy={busy}/>}</StitchShell>;
}

createRoot(document.getElementById('root')).render(<App />);
