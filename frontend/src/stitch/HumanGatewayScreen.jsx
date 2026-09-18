import React from 'react';

export default function HumanGatewayScreen({ gate, onClose }) {
  return <div className="fw-page fw-human-page">
    <div className="fw-page-head"><div><span className="fw-kicker">AUTOMATION MUTEX / THREAD #8841</span><h1>Human Gateway</h1><p>Server-controlled interception surface for CAPTCHA, OTP, legal acknowledgement, and other mandatory human steps.</p></div><span className="fw-gateway-lock">{gate ? '● ACTIVE GATE' : '● READY'}</span></div>
    <div className="fw-human-banner"><b>Zero-Knowledge Human Relay Mode</b><span>AI control remains locked unless the backend explicitly changes the live session to unlocked + human.</span></div>
    <div className="fw-human-grid"><article className="fw-human-info"><div className="fw-gate-kicker">CONTROL PLANE</div><h2>Server authoritative</h2><p>PR #12 owns the browser session and one-time capability token. PR #13 owns the canvas event scaling and throttling. This commercial layer only renders the resulting control state.</p><div className="fw-human-stat"><span>Remote input</span><b>LOCKED by default</b></div><div className="fw-human-stat"><span>Resume</span><b>Verification-gated</b></div><div className="fw-human-stat"><span>CAPTCHA / OTP</span><b>Human supplied</b></div></article><article className="fw-human-info"><div className="fw-gate-kicker">CURRENT EVENT</div><h2>{gate ? gate.reason?.toUpperCase() : 'No active interception'}</h2><p>{gate?.message || 'Start or attach a workflow session. Any backend human.required event will appear as the Stitch overlay without changing the safety boundary.'}</p><button className="fw-neon-btn" onClick={onClose}>{gate ? 'Return to Core Workspace' : 'Return to Core Workspace'}</button></article></div>
  </div>;
}
