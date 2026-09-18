import React from 'react';

export default function HumanGatewayModal({ gate, gateValue, setGateValue, onResume, onCancel, busy }) {
  if (!gate) return null;
  const otp = gate.reason?.toLowerCase().includes('otp');
  return <div className="fw-gateway-overlay" aria-live="assertive">
    <div className="fw-gateway-backdrop" />
    <div className="fw-gateway-modal">
      <div className="fw-gateway-top"><span>● AUTOMATION MUTEX / HUMAN-IN-THE-LOOP</span><b>LOCK EXPIRES {gate.expires || 'SAFE HOLD'}</b></div>
      <div className="fw-gateway-grid">
        <section className="fw-gate-card">
          <div className="fw-gate-kicker">SECURITY GATE · LEVEL 1</div>
          <h2>{otp ? '6-Digit OTP Required' : 'Human CAPTCHA Required'}</h2>
          <p>{gate.message || 'Automation paused. Complete the required verification in the secure live browser canvas, then resume AI.'}</p>
          <div className="fw-gate-viewport"><div className="fw-gate-viewport-label">LIVE VIRTUAL SUB-VIEWPORT · HUMAN INPUT ENABLED</div><div className="fw-gate-viewport-inner"><span>{otp ? 'Enter the code in the live browser or use the dedicated field at right.' : "I'm not a robot"}</span></div></div>
          <div className="fw-gate-token"><span>▱ DOM TOKEN SLOT</span><b>PENDING_USER_INPUT</b><em>Direct Hook Active</em></div>
          <div className="fw-gate-actions"><button className="fw-ghost-btn" onClick={onCancel} disabled={busy}>Cancel / Keep Paused</button><button className="fw-neon-btn" onClick={onResume} disabled={busy || (otp && gateValue.length < 4)}>▷ Confirm &amp; Resume Autonomous Agent</button></div>
        </section>
        <section className="fw-gate-card fw-otp-card">
          <div className="fw-gate-kicker">SECONDARY IDENTITY GATE · {otp ? '2FA ENFORCED' : 'SERVER CONTROLLED'}</div>
          <h2>{otp ? 'Secure one-time code' : 'Human challenge relay'}</h2>
          <p>{otp ? 'Enter the one-time code yourself. The server verifies the corresponding human gate before relocking AI control.' : 'Use the live browser canvas to complete the challenge. Formwise never solves or bypasses CAPTCHA.'}</p>
          {otp && <div className="fw-otp-inputs"><input autoFocus inputMode="numeric" maxLength={6} value={gateValue} onChange={e => setGateValue(e.target.value.replace(/\D/g,''))} placeholder="6 digits"/><span>SMS / authenticator input is never persisted in local storage.</span></div>}
          <div className="fw-defense"><b>FORMWISE DEFENSE SHIELD</b><p>Server-authoritative control remains the source of truth. The canvas token stays in memory only.</p></div>
          <div className="fw-gate-actions"><button className="fw-ghost-btn">Use Authenticator App</button><button className="fw-neon-btn" onClick={onResume} disabled={busy || (otp && gateValue.length < 4)}>⌑ Done / Resume AI</button></div>
        </section>
      </div>
      <div className="fw-gateway-footer"><span>◇ Pipeline: Autonomous Form Completion</span><span>⌁ Zero-knowledge human relay</span><span>Server safety policy authoritative</span></div>
    </div>
  </div>;
}
