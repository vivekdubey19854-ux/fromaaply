import React from 'react';
import LiveBrowserCanvas from '../LiveBrowserCanvas.tsx';

export default function CoreWorkspaceScreen({
  apiBase, userId, workflow, instruction, setInstruction, busy, status, docs,
  onStart, onConfirm, onOpen, onUpload, onExtract, onApprove, onFill, onFinalApproval, onFinalSubmit,
  approval, screenshot, onHumanGate, onLiveControl, resumeRequest,
}) {
  const fills = workflow?.plan?.fills || [];
  const approvals = workflow?.fieldApprovals || {};
  const human = workflow?.plan?.human_required || workflow?.result?.human_required || [];
  const facts = workflow?.research?.facts || {};
  const progress = workflow?.state === 'final_review' ? 92 : workflow?.session_id ? 68 : workflow ? 36 : 10;
  return <div className="fw-core-layout">
    <section className="fw-left-rail">
      <button className="fw-upload-card" onClick={() => document.getElementById('fw-upload')?.click()}><span className="fw-upload-plus">+</span><span><b>Instant Upload</b><small>Drop PDF, XML, image</small></span><em>RAW/OCR</em></button>
      <input id="fw-upload" className="fw-hidden" type="file" accept=".pdf,.jpg,.jpeg,.png,.webp" onChange={onUpload}/>
      <div className="fw-search-box">⌕ <input aria-label="Smart search" placeholder="Search target schema or ask AI" value={instruction} onChange={e => setInstruction(e.target.value)} /></div>
      <div className="fw-chat-card">
        <div className="fw-card-head"><div><i className="fw-dot"/> Neural Agent Chat</div><span>AUTONOMOUS<br/>MODE</span></div>
        <div className="fw-chat-line"><b>FORMWISE_DAEMON</b><time>11:41:40</time><p>Target portal loaded. Semantic field discovery is ready; sensitive values stay server-side.</p></div>
        <div className="fw-chat-line"><b>FORMWISE_DAEMON</b><time>11:41:52</time><p>Ready to automate with verified parameters and server-side approvals.</p></div>
        <div className="fw-metric-grid"><span>Confidence <b>99.4%</b></span><span>Encrypted Vault <b>READY</b></span><span>Human Gates <b>{human.length || 0}</b></span></div>
        <button className="fw-neon-btn" onClick={onStart} disabled={busy || instruction.length < 3}>Start autonomous workflow ↗</button>
      </div>
    </section>

    <section className="fw-center-stage">
      <div className="fw-panel-title"><div><span className="fw-kicker">AGENT // RUNNING</span><b>{workflow?.session_id ? `TARGET SESSION #${workflow.session_id}` : 'TARGET SESSION // NOT STARTED'}</b></div><span className="fw-safe-pill">⌁ Isolated headless browser</span></div>
      {workflow?.session_id ? <LiveBrowserCanvas apiBase={apiBase} userId={userId} sessionId={workflow.session_id} onStatus={() => {}} onHumanGate={onHumanGate} onLiveControl={onLiveControl} resumeRequest={resumeRequest} /> : <div className="fw-empty-browser"><div>FORM FILL VIEWPORT</div><h2>Start a workflow to attach the secure live browser.</h2><p>PR #12/#13 guardrails remain authoritative: AI input stays locked unless backend broadcasts an approved human gate.</p></div>}

      {workflow?.state === 'research_ready' && <div className="fw-inline-status"><b>Research ready for human review.</b><p>{facts.application_window || 'Application window not extracted'} · Last date: {facts.last_date || 'Not extracted'} · Fee: {facts.fee_rupees ? `₹${facts.fee_rupees}` : 'Not extracted'}</p><div><button onClick={() => onConfirm(true)} disabled={busy}>I reviewed it — continue</button><button onClick={() => onConfirm(false)} disabled={busy}>Cancel</button></div></div>}
      {workflow?.state === 'documents_missing' && <div className="fw-inline-status"><b>Document checklist requires attention.</b><pre>{JSON.stringify(workflow.document_check || {}, null, 2)}</pre><button onClick={() => onConfirm(true)} disabled={busy}>Re-check checklist</button></div>}
      {workflow?.state === 'documents_ready' && <div className="fw-inline-status"><b>Document checklist passed.</b><p>Target application can now be opened inside the isolated browser.</p><button className="fw-neon-btn" onClick={onOpen} disabled={busy}>Open target application ↗</button></div>}

      {workflow && <div className="fw-action-bar"><button onClick={onOpen} disabled={busy || workflow.state !== 'documents_ready'}>⌗ Inspect DOM</button><button>◉ Pause Agent</button><button onClick={() => fills[0] && onApprove(fills[0])} disabled={busy || !fills[0] || !fills[0].requires_approval}>⇥ Approve Field</button><button className="fw-neon-btn" onClick={onFill} disabled={busy || !fills.length}>Request Sign-Off</button></div>}
      {workflow && <div className="fw-field-strip">{fills.slice(0,4).map(x => <div key={x.index} className="fw-field-card"><span>{x.index + 1}. {x.field}</span><b>{x.requires_approval ? 'SENSITIVE' : 'VERIFIED'}</b><p>{String(x.value ?? '').slice(0,34)}</p><small>{approvals[x.index] ? 'APPROVED' : 'READY'}</small></div>)}</div>}
      {workflow?.state === 'final_review' && <div className="fw-inline-status"><b>Final review — nothing is submitted yet.</b><p>Review every field and screenshot. Formwise will never click the final Submit/Confirm control. You must submit manually on the website.</p>{screenshot && <img className="shot" src={screenshot} alt="Latest workflow screenshot"/>}<button onClick={onFinalApproval} disabled={busy}>I reviewed the form — show manual submit instructions</button>{approval && <button className="fw-neon-btn" onClick={onFinalSubmit} disabled={busy}>I WILL CLICK FINAL SUBMIT MANUALLY</button>}</div>}
      {status && <div className="fw-inline-status">{status}</div>}
    </section>

    <section className="fw-right-rail">
      <div className="fw-progress-card"><div className="fw-card-head"><h3>Progress Matrix</h3><span>STREAM: LIVE</span></div><div className="fw-log-list"><p><b>[11:42:01]</b> DOM MUTATION <span>Self-Healing active</span></p><p><b>[11:42:11]</b> SECURITY <span>Verified values never leave server</span></p><p><b>[11:42:18]</b> HUMAN GATE <span>{human.length ? human.join(', ') : 'None detected'}</span></p><p><b>[11:42:22]</b> BROWSER <span>Live frame loop connected</span></p></div></div>
      <div className="fw-progress-metric"><div><span>Progress Metric</span><b>{progress}%</b></div><div className="fw-progress-track"><i style={{width:`${progress}%`}}/></div><p>Phase {workflow?.state || 'ready'} · final submission remains explicit</p><div className="fw-mini-chart">▁▃▂▆▄▇▅█</div></div>
      <div className="fw-vault-mini"><div className="fw-card-head"><h3>Secure Vault</h3><span>{docs.length} docs</span></div>{docs.slice(0,3).map(d => <div className="fw-mini-row" key={d.id}><span>▣ {d.original_filename}</span><b>{d.status}</b><button onClick={() => onExtract(d.id)} disabled={busy}>Extract</button></div>)}{!docs.length && <p>No documents uploaded yet. Use Instant Upload to add PDF/JPEG/PNG/WEBP up to 10MB.</p>}</div>
    </section>
  </div>;
}
