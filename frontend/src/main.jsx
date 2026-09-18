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

async function ensureAccessToken() {
  if (accessToken) return accessToken;
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
  const token = await ensureAccessToken();
  const headers = { Authorization: `Bearer ${token}`, ...(opts.headers || {}) };
  if (opts.body && !(opts.body instanceof FormData) && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
  const response = await fetch(API + path, { ...opts, headers });
  let data = {}; try { data = await response.json(); } catch {}
  if (response.status === 401) { localStorage.removeItem('formwise_access_token'); accessToken = ''; }
  if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
  return data;
}

function AuthScreen({ onAuthenticated }) {
  const [mode, setMode] = useState('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const submit = async event => {
    event.preventDefault(); setError(''); setBusy(true);
    try {
      const response = await fetch(`${API}/v1/auth/${mode === 'signup' ? 'signup' : 'login'}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(mode === 'signup' ? { email, password, full_name: fullName || null } : { email, password }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || 'Authentication failed.');
      accessToken = data.access_token;
      localStorage.setItem('formwise_access_token', accessToken);
      if (data.user_id) localStorage.setItem(uidKey, data.user_id);
      if (data.refresh_token) localStorage.setItem('formwise_refresh_token', data.refresh_token);
      onAuthenticated();
    } catch (err) { setError(err instanceof Error ? err.message : 'Authentication failed.'); }
    finally { setBusy(false); }
  };
  return <main className="fw-auth-page"><form className="fw-auth-card" onSubmit={submit}>
    <div className="fw-kicker">FORMWISE // SECURE ACCOUNT</div><h1>{mode === 'signup' ? 'Create your account' : 'Welcome back'}</h1>
    <p>Save verified profile data securely and prepare forms with human approval at sensitive steps.</p>
    {mode === 'signup' && <input value={fullName} onChange={e => setFullName(e.target.value)} placeholder="Full name" maxLength={200} />}
    <input type="email" required value={email} onChange={e => setEmail(e.target.value)} placeholder="Email address" autoComplete="email" />
    <input type="password" required minLength={12} value={password} onChange={e => setPassword(e.target.value)} placeholder="Password (12+ characters)" autoComplete={mode === 'signup' ? 'new-password' : 'current-password'} />
    {error && <div className="fw-inline-status">{error}</div>}
    <button className="fw-neon-btn" disabled={busy}>{busy ? 'AUTHENTICATING…' : mode === 'signup' ? 'CREATE ACCOUNT' : 'SIGN IN'}</button>
    <button type="button" className="fw-link-btn" onClick={() => { setMode(mode === 'signup' ? 'login' : 'signup'); setError(''); }}>{mode === 'signup' ? 'Already have an account? Sign in' : 'Create a new account'}</button>
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
  if (!signedIn && !isAdminSurface) return <AuthScreen onAuthenticated={() => setSignedIn(true)} />;
  if (view === 'admin') return <AdminDashboard />;
  const renderView = () => { if(view==='vault')return <DocumentVaultScreen docs={docs} busy={busy} onUpload={upload} onExtract={extract}/>; if(view==='knowledge')return <MasterKnowledgeScreen profile={profile} education={education} addresses={addresses}/>; if(view==='billing')return <BillingLogsScreen billing={billing} busy={busy} onRefresh={loadBilling}/>; if(view==='human')return <HumanGatewayScreen gate={activeGate} onClose={()=>setView('core')}/>; return <CoreWorkspaceScreen apiBase={API} userId={uid} accessToken={accessToken} workflow={workflow} instruction={instruction} setInstruction={setInstruction} busy={busy} status={status} docs={docs} onStart={start} onConfirm={confirm} onOpen={openApp} onUpload={upload} onExtract={extract} onApprove={approveField} onFill={fill} onFinalApproval={finalApproval} onFinalSubmit={finalSubmit} approval={approval} screenshot={screenshot} onHumanGate={onHumanGate} onLiveControl={onLiveControl} resumeRequest={resumeRequest} saveProfile={saveProfile} />; };
  return <StitchShell view={view} onNavigate={setView} status={status}>{renderView()}{activeGate&&<HumanGatewayModal gate={activeGate} gateValue={gateValue} setGateValue={setGateValue} onResume={resumeHuman} onCancel={()=>setView('human')} busy={busy}/>}</StitchShell>;
}

createRoot(document.getElementById('root')).render(<App />);
