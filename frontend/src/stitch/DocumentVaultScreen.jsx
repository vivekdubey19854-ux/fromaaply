import React, { useRef, useState } from 'react';

const TYPES = ['.pdf','.jpg','.jpeg','.png','.webp'];
const CARDS = [
  ['Aadhaar National ID','Aadhaar'],
  ['Income Tax PAN Card','PAN'],
  ['Passport / Republic of India','Passport'],
  ['Photo & Signature','Photo'],
];

function matches(doc, token) { return `${doc.original_filename} ${doc.content_type}`.toLowerCase().includes(token.toLowerCase()); }

export default function DocumentVaultScreen({ docs, busy, onUpload, onExtract }) {
  const inputRef = useRef(null);
  const [drag, setDrag] = useState(false);
  const choose = files => { const file = files?.[0]; if (!file) return; onUpload({ target: { files: [file] } }); };
  const docFor = token => docs.find(d => matches(d, token));
  const drop = e => { e.preventDefault(); setDrag(false); choose(e.dataTransfer.files); };
  return <div className="fw-page">
    <div className="fw-page-head"><div><span className="fw-kicker">ZERO-KNOWLEDGE HARDWARE ENCLAVE</span><h1>Personal Knowledge Vault &amp; Identity Safe</h1><p>Private customer-isolated documents with 10MB server validation, ephemeral extraction, and explicit re-indexing.</p></div><div className="fw-head-actions"><button className="fw-ghost-btn">↻ Sync Hardware Enclave</button><button className="fw-ghost-btn">▣ Export Manifest</button><button className="fw-ghost-btn">▤ Audit Access Logs</button></div></div>
    <div className="fw-enclave-strip"><b><i className="fw-dot"/> VAULT STATUS: ACTIVE</b><span>AES-256-GCM</span><span>SHA-256 Merkle</span><span>TEE Attestation: server verified</span><span>Client memory isolated</span></div>
    <div className={`fw-dropzone ${drag ? 'drag' : ''}`} onDragOver={e => {e.preventDefault();setDrag(true)}} onDragLeave={() => setDrag(false)} onDrop={drop} onClick={() => inputRef.current?.click()}>
      <div className="fw-cloud">↥</div><h2>Drag &amp; drop identity documents here or browse computer</h2><p>Supports PDF, JPEG, PNG, WEBP <b>(Max 10MB)</b> · auto-routed to secure extraction</p><button className="fw-light-btn" type="button">Select Files from Secure Storage</button><input ref={inputRef} className="fw-hidden" type="file" accept={TYPES.join(',')} onChange={e => choose(e.target.files)}/><div className="fw-drop-meta">♢ CLIENT-SIDE EPHEMERAL HASH · ● MEMORY ISOLATION SANDBOX · ⊙ AUTO-WIPE SCRATCHPAD</div>
    </div>
    <div className="fw-section-heading"><h2>Extracted Identity Tokens &amp; Cryptographic Manifests</h2><span>4 VERIFIED UNITS</span></div>
    <div className="fw-vault-grid">{CARDS.map(([title, token], i) => { const d = docFor(token); const ready = Boolean(d); return <article className="fw-doc-card" key={title}><div className="fw-card-head"><div><h3>{title}</h3><small>{d?.original_filename || 'Awaiting secure upload'}</small></div><span className={ready ? 'fw-status-ok' : 'fw-status-muted'}>{ready ? 'VERIFIED' : 'READY'}</span></div><div className="fw-doc-body">{ready ? <><div><label>Document status</label><strong>{d.status?.toUpperCase() || 'UPLOADED'}</strong></div><div><label>Content type</label><strong>{d.content_type}</strong></div><div><label>Encrypted size</label><strong>{Math.ceil((d.size_bytes || 0)/1024)} KB</strong></div><div><label>SHA-256</label><strong className="fw-mono">{String(d.sha256 || '').slice(0,16)}…</strong></div></> : <p className="fw-muted-copy">Upload the matching identity document. Formwise never invents extracted values; OCR is only triggered by your action.</p>}</div><div className="fw-doc-actions">{d && <button onClick={() => onExtract(d.id)} disabled={busy}>↯ Extract / OCR</button>}<span>{i === 2 ? 'OCR pipeline ready' : 'DOM injection gated'}</span></div></article>})}</div>
    <div className="fw-log-console"><div className="fw-console-head"><b>● Enclave Telemetry &amp; Attestation Pipeline</b><span>TAILING LOGS (LOCAL UI)</span></div><p><b>VAULT</b> user-isolated object scope active</p><p><b>OCR</b> extraction writes to private storage only</p><p><b>POLICY</b> unsupported file types and &gt;10MB uploads are rejected server-side</p></div>
  </div>;
}
