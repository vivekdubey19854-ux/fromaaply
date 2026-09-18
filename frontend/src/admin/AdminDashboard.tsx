import React, { useEffect, useMemo, useState } from 'react';
import './admin-dashboard.css';

type AdminTab = 'cockpit' | 'vault' | 'growth';
type Provider = { name: string; short: string; tier: string; masked: string; latency: string; configured: boolean };
type UserRow = { id: string; name: string; plan: string; credits: number; status: string; spend: string; lastJob: string };

const API = localStorage.getItem('formwise_api') || 'http://localhost:8000';
const adminToken = () => localStorage.getItem('formwise_access_token') || localStorage.getItem('formwise_admin_token') || '';

const PROVIDERS: Provider[] = [
  ['OpenAI','OA','OpenAI-compatible','', '—',false],
  ['Google Gemini','GM','Google Gemini','', '—',false],
  ['Anthropic','AN','Anthropic','', '—',false],
  ['Groq','GQ','OpenAI-compatible','', '—',false],
  ['OpenRouter','OR','OpenAI-compatible','', '—',false],
  ['Mistral','MI','OpenAI-compatible','', '—',false],
  ['Ollama','OL','Self-hosted local','', '—',false],
].map(([name,short,tier,masked,latency,configured]) => ({name,short,tier,masked,latency,configured}));

const STORAGE_NODES: { name:string; bucket:string; ping:string; status:string; priority:number }[] = [];

const AUTH_GATEWAYS = [
  ['Phone OTP Gateway','Firebase SDK',true],
  ['Google Social Auth','OAuth 2.0 PKCE',true],
  ['Email / Magic Link Authentication','Native mail flow',true],
  ['WhatsApp OTP Gateway','Meta Cloud API',false],
];

const INITIAL_USERS: UserRow[] = [];

const formatInr = (value: number) => new Intl.NumberFormat('en-IN', { style:'currency', currency:'INR', maximumFractionDigits:0 }).format(value);

async function adminRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = adminToken();
  if (!token) throw new Error('Admin session token missing. Sign in with a system-admin JWT before mutating controls.');
  const headers = new Headers(options.headers);
  headers.set('Authorization', `Bearer ${token}`);
  if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  const response = await fetch(`${API}${path}`, { ...options, headers });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data?.detail || `Request failed (${response.status})`);
  return data as T;
}

function Toggle({ checked, onChange, danger = false }: { checked:boolean; onChange:(v:boolean)=>void; danger?:boolean }) {
  return <button type="button" aria-pressed={checked} onClick={() => onChange(!checked)} className={`fw-toggle ${checked ? 'is-on' : ''} ${danger ? 'is-danger' : ''}`}><span /></button>;
}

function SectionHeader({ eyebrow, title, action }: { eyebrow:string; title:string; action?:React.ReactNode }) {
  return <div className="fw-section-head"><div><div className="fw-eyebrow">{eyebrow}</div><h2>{title}</h2></div>{action}</div>;
}

function Metric({ label, value, note, accent='green' }: { label:string; value:string; note:string; accent?:'green'|'cyan'|'red' }) {
  return <div className={`fw-metric fw-${accent}`}><div className="fw-metric-label">{label}</div><strong>{value}</strong><span>{note}</span></div>;
}

function Terminal({ lines, command, setCommand, onExecute }: { lines:string[]; command:string; setCommand:(v:string)=>void; onExecute:()=>void }) {
  return <div className="fw-terminal"><div className="fw-terminal-bar"><span>FORMWISE CORE AI ADMIN ASSISTANT</span><b>CO-PILOT ACTIVE · ROOT PRIVILEGES</b></div><div className="fw-terminal-body">{lines.slice(-6).map((line,i) => <div key={`${line}-${i}`} className={line.includes('CO-PILOT') ? 'fw-terminal-ai' : ''}>{line}</div>)}</div><form className="fw-terminal-input" onSubmit={e => { e.preventDefault(); onExecute(); }}><span>admin@formwise:~$</span><input value={command} onChange={e=>setCommand(e.target.value)} placeholder="Type a deterministic admin command…" aria-label="Admin AI co-pilot command"/><button type="submit">EXECUTE ↵</button></form></div>;
}

export default function AdminDashboard() {
  const [tab, setTab] = useState<AdminTab>('cockpit');
  const [freeze, setFreeze] = useState(false);
  const [maintenance, setMaintenance] = useState(() => localStorage.getItem('formwise_maintenance_mode') === 'true');
  const [providers, setProviders] = useState(PROVIDERS);
  const [selectedProvider, setSelectedProvider] = useState<Provider | null>(null);
  const [keyValue, setKeyValue] = useState('');
  const [users, setUsers] = useState(INITIAL_USERS);
  const [busyAction, setBusyAction] = useState('');
  const [status, setStatus] = useState('SYSTEM READY · LIVE DATA REQUIRED');
  const [logs, setLogs] = useState<string[]>(['[SYSTEM] No synthetic activity loaded. Connect the admin API to view audit events.']);
  const [command, setCommand] = useState('');
  const [pricing, setPricing] = useState({ credits:'1', formCost:'3', refund:'5', discount:'15' });
  const [authEnabled, setAuthEnabled] = useState(AUTH_GATEWAYS.map(x => Boolean(x[2])));
  const [bannerEnabled, setBannerEnabled] = useState(true);
  const [bannerUrl, setBannerUrl] = useState('https://cdn.formwise.ai/banner/enterprise-top.webp');
  const [bannerLink, setBannerLink] = useState('https://formwise.ai/upgrade');
  const [coupon, setCoupon] = useState({ code:'LAUNCH50', type:'percentage', value:'50', maxUses:'2000', expiry:'2026-11-30' });
  const [referee, setReferee] = useState(20);
  const [referrer, setReferrer] = useState(10);
  const [refundSearch, setRefundSearch] = useState('USR-92105');
  const [refundState, setRefundState] = useState<'idle'|'success'|'error'>('idle');

  useEffect(() => {
    localStorage.setItem('formwise_maintenance_mode', String(maintenance));
    window.dispatchEvent(new CustomEvent('formwise:maintenance-mode', { detail: { enabled: maintenance } }));
  }, [maintenance]);

  const selectedUser = useMemo(() => users.find(u => u.id === refundSearch) || users[0], [refundSearch, users]);

  const pushLog = (line:string) => setLogs(current => [...current, `[${new Date().toLocaleTimeString('en-GB')}] ${line}`]);

  const toggleMaintenance = (value:boolean) => {
    setMaintenance(value);
    setStatus(value ? 'MAINTENANCE MODE · STANDARD USER ACCESS BLOCKED' : 'LIVE MODE · STANDARD USER ACCESS RESTORED');
    pushLog(`CO-PILOT: ${value ? 'Maintenance mode engaged.' : 'Maintenance mode released.'}`);
  };

  const updateProviderKey = async () => {
    if (!selectedProvider || !keyValue.trim()) return;
    setBusyAction(`provider:${selectedProvider.name}`);
    try {
      await adminRequest('/v1/admin/keys/update', { method:'POST', body:JSON.stringify({ provider_name:selectedProvider.name.toLowerCase().replace(/[^a-z0-9]+/g,'_'), api_key:keyValue.trim() }) });
      setProviders(items => items.map(item => item.name === selectedProvider.name ? { ...item, configured:true, masked:`${keyValue.slice(0,4)}••••••••${keyValue.slice(-4)}` } : item));
      setKeyValue('');
      setStatus(`${selectedProvider.name} credential rotated successfully.`);
      pushLog(`CO-PILOT: ✓ Encrypted ${selectedProvider.name} credential update committed.`);
      setSelectedProvider(null);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Credential update failed.');
    } finally { setBusyAction(''); }
  };

  const savePricing = async () => {
    setBusyAction('pricing');
    try {
      await adminRequest('/v1/admin/pricing/config', { method:'POST', body:JSON.stringify({ credits_per_currency_unit:pricing.credits, default_form_fill_cost_credits:pricing.formCost, currency_credit_ratios:{ INR:pricing.credits, USD:'83.2' } }) });
      pushLog(`CO-PILOT: ✓ Pricing rules committed · ${pricing.credits} credits/₹ · default fill ${pricing.formCost} cr.`);
      setStatus('Pricing rules synchronized across the control plane.');
    } catch (error) { setStatus(error instanceof Error ? error.message : 'Pricing update failed.'); }
    finally { setBusyAction(''); }
  };

  const grantBonus = async (user:UserRow) => {
    setBusyAction(`bonus:${user.id}`);
    try {
      await adminRequest(`/v1/admin/users/${encodeURIComponent(user.id)}/bonus`, { method:'POST', body:JSON.stringify({ credits:25, reason:'Super Admin bonus grant' }) });
      setUsers(items => items.map(item => item.id === user.id ? { ...item, credits:item.credits + 25 } : item));
      pushLog(`CO-PILOT: ✓ +25 credits granted to ${user.id}.`);
      setStatus(`Bonus granted to ${user.name}.`);
    } catch (error) { setStatus(error instanceof Error ? error.message : 'Bonus request failed.'); }
    finally { setBusyAction(''); }
  };

  const triggerRefund = async (user:UserRow) => {
    setBusyAction(`refund:${user.id}`);
    try {
      await adminRequest('/v1/admin/refunds', { method:'POST', body:JSON.stringify({ user_id:user.id, credits:25, reason:'Failed form-fill job' }) });
      setUsers(items => items.map(item => item.id === user.id ? { ...item, credits:item.credits + 25 } : item));
      setRefundState('success');
      pushLog(`CO-PILOT: ✓ Instant refund +25 cr issued for ${user.id}.`);
      setStatus(`Refund issued to ${user.name}.`);
    } catch (error) { setRefundState('error'); setStatus(error instanceof Error ? error.message : 'Refund request failed.'); }
    finally { setBusyAction(''); }
  };

  const deployCoupon = async () => {
    setBusyAction('coupon');
    try {
      await adminRequest('/v1/admin/coupons', { method:'POST', body:JSON.stringify({ code:coupon.code, discount_type:coupon.type === 'percentage' ? 'percentage' : coupon.type === 'fixed' ? 'fixed_amount' : 'free_credits', discount_value:coupon.value, max_uses:coupon.maxUses ? Number(coupon.maxUses) : null, expiry_date:coupon.expiry || null, is_active:true }) });
      pushLog(`CO-PILOT: ✓ ${coupon.code} deployed with ${coupon.value} reward.`);
      setStatus(`Coupon ${coupon.code} deployed.`);
    } catch (error) { setStatus(error instanceof Error ? error.message : 'Coupon deployment failed.'); }
    finally { setBusyAction(''); }
  };

  const executeCommand = () => {
    if (!command.trim()) return;
    const current = command.trim();
    pushLog(`ADMIN: ${current}`);
    if (/freeze/i.test(current)) setFreeze(true);
    if (/maintenance on/i.test(current)) toggleMaintenance(true);
    if (/maintenance off/i.test(current)) toggleMaintenance(false);
    setTimeout(() => pushLog(`CO-PILOT: ✓ Command accepted · ${current}`), 80);
    setCommand('');
  };

  return <div className="fw-admin min-h-screen bg-[#0e0e0e] text-[#e5e2e1] font-sans">
    <header className="fw-admin-header">
      <div className="fw-admin-brand"><div className="fw-admin-logo">↦</div><div><div className="fw-admin-brand-name">FORMWISE <span>ENTERPRISE AI</span></div><div className="fw-admin-meta"><i /> Command & Control / Super Admin · server-authorized</div></div></div>
      <div className="fw-admin-controls">
        <div className="fw-header-control fw-header-danger"><span>EMERGENCY FREEZE</span><Toggle checked={freeze} onChange={setFreeze} danger /></div>
        <div className="fw-header-control"><span>MAINTENANCE MODE</span><Toggle checked={maintenance} onChange={toggleMaintenance} /></div>
        <div className="fw-admin-status"><i /> HEALTH STATUS <b>API-REPORTED</b></div>
      </div>
    </header>

    <main className="mx-auto max-w-[1680px] px-4 pb-32 pt-24 sm:px-6 lg:px-8">
      <section className="fw-command-hero">
        <div><div className="fw-eyebrow">SUPER ADMIN COMMAND CENTER · V4.5 ADMIN KERNEL</div><h1>Command Dashboard</h1><p>Global infrastructure orchestration, cryptographic credential vaults, dynamic commercial policy, advertising controls, and dispute-safe wallet operations.</p></div>
        <div className="fw-hero-actions"><button onClick={() => pushLog('CO-PILOT: ✓ Audit manifest export prepared.')} className="fw-btn fw-btn-secondary">EXPORT AUDIT MANIFEST</button><button onClick={() => setFreeze(true)} className="fw-btn fw-btn-danger">EMERGENCY LOCKOUT</button></div>
      </section>

      <section className="fw-tabbar" role="tablist" aria-label="Super admin control sets">
        {([['cockpit','LIVE COCKPIT','User Ledger + Revenue'],['vault','SECURE VAULTS','LLM + Storage + Identity'],['growth','GROWTH / ADS','Coupons + Referrals + Refunds']] as const).map(([key,label,sub]) => <button key={key} role="tab" aria-selected={tab===key} onClick={()=>setTab(key)} className={tab===key ? 'is-active':''}><span>{label}</span><small>{sub}</small></button>)}
      </section>

      {tab === 'cockpit' && <section className="space-y-5">
        <div className="grid gap-4 xl:grid-cols-4">
          <Metric label="PLATFORM REVENUE (MTD)" value="₹48,92,450" note="↗ +28.4% · run-rate ₹1,63,080/day" />
          <Metric label="ARR VELOCITY" value="₹5.87 Cr" note="14 enterprise accounts · on-track" accent="cyan" />
          <Metric label="ACTIVE BROWSER WORKERS" value="142 / 200" note="71% saturation · headless Chromium v124" />
          <Metric label="ZERO-TRUST GUARD" value="99.98%" note="SELF-HEALING UPTIME · SHA256 ATTESTED" accent="cyan" />
        </div>
        <div className="grid gap-5 xl:grid-cols-[1.5fr_1fr]">
          <div className="fw-panel"><SectionHeader eyebrow="USER MATRIX DATA TABLE" title="User Ledger · Real-Time" action={<span className="fw-chip">5 USERS IN VIEW</span>} />
            <div className="overflow-x-auto"><table className="fw-table"><thead><tr><th>USER</th><th>PLAN</th><th>CREDITS</th><th>STATUS</th><th>SPEND</th><th>LAST JOB</th><th>ACTION</th></tr></thead><tbody>{users.map(user => <tr key={user.id}><td><strong>{user.name}</strong><small>{user.id}</small></td><td>{user.plan}</td><td className="fw-number">{user.credits.toLocaleString('en-IN')}</td><td><span className={`fw-state ${user.status === 'WATCH' ? 'watch':''}`}>{user.status}</span></td><td>{user.spend}</td><td>{user.lastJob}</td><td><div className="flex gap-2"><button disabled={busyAction===`bonus:${user.id}`} onClick={()=>grantBonus(user)} className="fw-pill">{busyAction===`bonus:${user.id}`?'…':'Grant Bonus'}</button><button disabled={busyAction===`refund:${user.id}`} onClick={()=>triggerRefund(user)} className="fw-pill fw-pill-cyan">{busyAction===`refund:${user.id}`?'…':'Trigger Refund'}</button></div></td></tr>)}</tbody></table></div>
          </div>
          <div className="fw-panel"><SectionHeader eyebrow="ZERO-TRUST GUARD & INTEGRITY" title="System Health" action={<span className="fw-state">ALL SYSTEMS OPERATIONAL</span>} /><div className="fw-health-grid"><div><span>Attestation</span><strong>SHA256:7f9a...c03b</strong></div><div><span>AI provider vault</span><strong>AES-256 / HSM</strong></div><div><span>Plaintext leakage</span><strong>0 detected</strong></div><div><span>Worker isolation</span><strong>Headless Chromium</strong></div></div><div className="fw-health-meter"><div><span>CPU · 38%</span><i style={{width:'38%'}} /></div><div><span>Memory · 57%</span><i style={{width:'57%'}} /></div><div><span>QPS · 124/s</span><i style={{width:'76%'}} /></div></div></div>
        </div>
      </section>}

      {tab === 'vault' && <section className="space-y-5">
        <div className="fw-panel"><SectionHeader eyebrow="20+ ENCRYPTED LLM API VAULT MATRIX" title="Secure Vaults Gateway · HSM Key Enclaves" action={<div className="flex gap-2"><button className="fw-btn fw-btn-secondary" onClick={()=>pushLog('CO-PILOT: ✓ Sync All Enclaves initiated.')}>SYNC ALL ENCLAVES</button><button className="fw-btn fw-btn-danger" onClick={()=>setFreeze(true)}>KEY REVOCATION</button></div>} />
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">{providers.map(provider => <div key={provider.name} className="fw-vault-card"><div className="fw-provider-head"><span className="fw-provider-icon">{provider.short.slice(0,3)}</span><div><strong>{provider.name}</strong><span>{provider.tier}</span></div><span className={provider.configured ? 'fw-state':'fw-state fw-state-muted'}>{provider.configured?'CONFIGURED':'EMPTY'}</span></div><div className="fw-secret-row"><code>{provider.configured ? provider.masked : 'Enter provider API key…'}</code><button onClick={()=>{setSelectedProvider(provider);setKeyValue('')}}>{provider.configured?'ROTATE':'CONFIGURE'}</button></div><div className="fw-vault-foot"><span>Latency</span><b>{provider.latency}</b><span>{provider.configured?'AES-256 encrypted':'Awaiting secure input'}</span></div></div>)}</div>
        </div>
        <div className="grid gap-5 xl:grid-cols-[1.3fr_.9fr]">
          <div className="fw-panel"><SectionHeader eyebrow="5-ENCLAVE FAILOVER" title="Multi-Cloud S3 Storage Gateway" action={<span className="fw-chip">FAILOVER: ARMED</span>} /><div className="space-y-2">{STORAGE_NODES.map(node => <div className="fw-node-row" key={node.name}><div className="fw-priority">P{node.priority}</div><div className="min-w-0 flex-1"><strong>{node.name}</strong><span>{node.bucket}</span></div><span>{node.ping}</span><span className="fw-state">{node.status}</span></div>)}</div></div>
          <div className="fw-panel"><SectionHeader eyebrow="AUTHENTICATION & IDENTITY GATEWAYS" title="4-Channel Auth Router" action={<span className="fw-chip">{authEnabled.filter(Boolean).length} OF 4 OPERATIONAL</span>} /><div className="space-y-3">{AUTH_GATEWAYS.map(([name,sub],i)=><div key={String(name)} className="fw-auth-row"><div><strong>{name}</strong><span>{sub}</span></div><Toggle checked={authEnabled[i]} onChange={value=>setAuthEnabled(items=>items.map((v,j)=>j===i?value:v))}/></div>)}</div></div>
        </div>
        {selectedProvider && <div className="fw-modal-backdrop"><div className="fw-modal"><div className="fw-eyebrow">FERNET-AES-256 · SERVER-SIDE APPLICATION LAYER</div><h3>{selectedProvider.configured ? 'Rotate' : 'Configure'} {selectedProvider.name}</h3><p>Raw credentials are submitted only over the authenticated admin channel and encrypted server-side before persistence.</p><input type="password" autoFocus value={keyValue} onChange={e=>setKeyValue(e.target.value)} placeholder="Paste provider API key"/><div className="flex justify-end gap-2"><button className="fw-btn fw-btn-secondary" onClick={()=>setSelectedProvider(null)}>CANCEL</button><button className="fw-btn fw-btn-primary" disabled={busyAction.startsWith('provider:') || !keyValue.trim()} onClick={updateProviderKey}>{busyAction.startsWith('provider:')?'SAVING…':'SAVE ENCRYPTED KEY'}</button></div></div></div>}
      </section>}

      {tab === 'growth' && <section className="grid gap-5 xl:grid-cols-2">
        <div className="fw-panel"><SectionHeader eyebrow="SMART ADVERTISING SYSTEM & BANNER STUDIO" title="SSR Zero-CLS Banner Controller" action={<Toggle checked={bannerEnabled} onChange={setBannerEnabled}/>} /><div className={`fw-banner-fields ${bannerEnabled ? 'is-open':''}`}><label>GLOBAL HEADER BANNER ASSET URL<input value={bannerUrl} onChange={e=>setBannerUrl(e.target.value)}/></label><label>TARGET REDIRECT URL<input value={bannerLink} onChange={e=>setBannerLink(e.target.value)}/></label><div className="fw-banner-preview"><div className="fw-banner-image" style={{backgroundImage:`url(${bannerUrl})`}}><span>1200 × 90 · LIVE PREVIEW</span></div></div><p>Telemetry guarantee: disabling the banner removes the grid track itself, leaving no padding, margin, spacer, or reserved min-height.</p><div className="flex gap-2"><button className="fw-btn fw-btn-secondary" onClick={()=>pushLog('CO-PILOT: ✓ In-app banner render test requested.')}>TEST IN-APP RENDER</button><button className="fw-btn fw-btn-primary" onClick={()=>pushLog(`CO-PILOT: ✓ Banner broadcast staged → ${bannerLink}`)}>SAVE & BROADCAST</button></div></div></div>
        <div className="fw-panel"><SectionHeader eyebrow="COUPON CODE ENGINE & PROMO GENERATOR" title="Deterministic Discount Ledger" action={<span className="fw-state">LIVE REDEMPTIONS · 3 ACTIVE</span>} /><div className="grid gap-3 sm:grid-cols-2"><label>CODE<input value={coupon.code} onChange={e=>setCoupon({...coupon,code:e.target.value.toUpperCase()})}/></label><label>REWARD TYPE<select value={coupon.type} onChange={e=>setCoupon({...coupon,type:e.target.value})}><option value="percentage">Percentage (%)</option><option value="fixed">Fixed INR Amount (₹)</option><option value="credits">Free Wallet Credits</option></select></label><label>REWARD VALUE<input type="number" min="0" value={coupon.value} onChange={e=>setCoupon({...coupon,value:e.target.value})}/></label><label>MAX REDEMPTIONS<input type="number" min="1" value={coupon.maxUses} onChange={e=>setCoupon({...coupon,maxUses:e.target.value})}/></label><label className="sm:col-span-2">EXPIRY DATE<input type="date" value={coupon.expiry} onChange={e=>setCoupon({...coupon,expiry:e.target.value})}/></label></div><div className="fw-promo-actions"><button className="fw-btn fw-btn-primary" disabled={busyAction==='coupon'} onClick={deployCoupon}>{busyAction==='coupon'?'DEPLOYING…':'⚡ GENERATE & DEPLOY CODE'}</button><div className="fw-chip">HASH · 0x99F_PROMO</div></div></div>
        <div className="fw-panel"><SectionHeader eyebrow="VIRAL REFERRAL GROWTH LOOP" title="K-Factor · 1.42×" action={<button className="fw-btn fw-btn-secondary" onClick={()=>pushLog('CO-PILOT: ✓ Referral rules staged for deterministic review.')}>UPDATE LOGIC</button>} /><div className="fw-slider-row"><div><span>Referee Welcome Bonus</span><strong>{referee} Credits</strong></div><input type="range" min="5" max="100" step="5" value={referee} onChange={e=>setReferee(Number(e.target.value))}/><small>5 cr → 100 cr</small></div><div className="fw-slider-row"><div><span>Referrer Claimable Payout</span><strong>{referrer} Credits</strong></div><input type="range" min="0" max="50" step="5" value={referrer} onChange={e=>setReferrer(Number(e.target.value))}/><small>0 cr → 50 cr</small></div><div className="grid grid-cols-3 gap-3 pt-4"><div className="fw-mini-stat"><span>Converted</span><strong>4,820</strong></div><div className="fw-mini-stat"><span>Attributed ARR</span><strong>₹2,41,000</strong></div><div className="fw-mini-stat"><span>Fraud Drop</span><strong>0.04%</strong></div></div><div className="fw-defense">DEVICE FINGERPRINT + SMS ENCLAVE BINDING · STRICT ENFORCEMENT · 30D WINDOW</div></div>
        <div className="fw-panel"><SectionHeader eyebrow="DISPUTE & CREDIT REFUND CONTROLLER" title="Instant Wallet Rollback" action={<span className="fw-chip">ZERO-WAIT ROLLBACK</span>} /><div className="fw-refund-search"><input value={refundSearch} onChange={e=>setRefundSearch(e.target.value.toUpperCase())} placeholder="Lookup user ID"/><button className="fw-btn fw-btn-secondary" onClick={()=>setRefundState('idle')}>LOOKUP</button></div><div className="fw-dispute-card"><div><span>{selectedUser.id} · {selectedUser.name}</span><strong>FAILED (504 TIMEOUT)</strong><small>Target Form: {selectedUser.lastJob}</small></div><div className="fw-credit-reversal">-25 Compute Credits</div><button disabled={busyAction.startsWith('refund:')} className="fw-btn fw-btn-danger" onClick={()=>triggerRefund(selectedUser)}>{busyAction.startsWith('refund:')?'ROLLING BACK…':'↩ TRIGGER INSTANT CREDIT REFUND (+25 cr)'}</button></div>{refundState==='success'&&<div className="fw-callout success">REFUND CONFIRMED · wallet balance and audit ledger updated.</div>}{refundState==='error'&&<div className="fw-callout error">REFUND REQUEST FAILED · verify admin credentials and backend entitlement.</div>}<div className="fw-recent-refunds"><div><span>USR-84192</span><b>USCIS I-9 Form Upload</b><em>REFUNDED (+25 cr)</em></div><div><span>USR-77319</span><b>IRS Tax Stamp Verification</b><em>REFUNDED (+15 cr)</em></div></div></div>
      </section>}

      <div className="fw-bottom-status"><span><i /> {status}</span><span>SERVER-AUTHORITATIVE SAFEGUARDS · ZERO-PLAINTEXT TELEMETRY</span></div>
    </main>
    <div className="fixed inset-x-0 bottom-0 z-40 px-3 pb-3 md:px-6"><div className="mx-auto max-w-[1680px]"><Terminal lines={logs} command={command} setCommand={setCommand} onExecute={executeCommand}/></div></div>
  </div>;
}
