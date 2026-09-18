import React from 'react';

const NAV = [
  ['core', '▣', 'Core Workspace'],
  ['vault', '⌑', 'Document Vault'],
  ['knowledge', '◉', 'Master Knowledge'],
  ['billing', '▤', 'Billing & Logs'],
  ['human', '◇', 'Human Gateway'],
];

export default function StitchShell({ view, onNavigate, status, children }) {
  return (
    <div className="fw-app-shell">
      <header className="fw-topbar">
        <div className="fw-brand-wrap">
          <button className="fw-brand-mark" aria-label="Formwise home" onClick={() => onNavigate('core')}>↦</button>
          <div className="fw-brand">FORMWISE</div>
          <span className="fw-enterprise">ENTERPRISE<br/>AI</span>
          <span className="fw-live-chip"><i /> LIVE WORKSPACE <b>#FW-8841</b></span>
        </div>
        <nav className="fw-topnav" aria-label="Primary">
          {NAV.map(([key,,label]) => <button key={key} className={view === key ? 'active' : ''} onClick={() => onNavigate(key)}>{label}</button>)}
        </nav>
        <div className="fw-top-actions">
          <div className="fw-cluster"><i /> Cluster: <b>Healthy</b><span>|</span><em>0.4s DOM Resolution</em></div>
          <button className="fw-ghost-btn">⌘ Inspect DOM</button>
          <button className="fw-ghost-btn fw-pause">◉ Pause Agent</button>
          <div className="fw-avatar">●</div>
        </div>
      </header>

      <aside className="fw-sidebar">
        <div>
          <div className="fw-section-label">OPERATIONAL SYSTEMS</div>
          {NAV.map(([key, icon, label]) => (
            <button key={key} className={`fw-side-nav ${view === key ? 'active' : ''}`} onClick={() => onNavigate(key)}>
              <span>{icon}</span>{label}
            </button>
          ))}
        </div>
        <div className="fw-telemetry">
          <div className="fw-telemetry-head"><span>TELEMETRY</span><b>ACTIVE</b></div>
          <div>Engine: <strong>v4.2.0-fast</strong></div>
          <div>Tokens: <strong>89,420 pps</strong></div>
          <div>Latency: <strong>18ms p95</strong></div>
        </div>
      </aside>

      <main className="fw-main">
        <div className="fw-status-strip">
          <div><span className="fw-dot" /> {status || 'FORMWISE DAEMON // READY'}</div>
          <div className="fw-status-meta">Server-authoritative safeguards · no client-side bypass</div>
        </div>
        {children}
      </main>
    </div>
  );
}
