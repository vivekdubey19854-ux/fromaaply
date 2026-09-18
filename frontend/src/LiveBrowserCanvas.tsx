import React, { useCallback, useEffect, useRef, useState } from 'react';
import { apiToWebSocketUrl, isHumanInputEnabled, scalePoint, type LiveControl, type LiveSocketMessage } from './liveBrowserProtocol';

type Props = {
  apiBase: string;
  userId: string;
  sessionId: string;
  onStatus?: (message: string) => void;
  onHumanGate?: (gate: { reason: string; message: string; resume_allowed: boolean }) => void;
  onLiveControl?: (state: { control: LiveControl; mode: 'ai' | 'human'; paused: boolean }) => void;
  resumeRequest?: number;
};

type Frame = { data: string; width: number; height: number; seq: number };
const MOUSE_MOVE_INTERVAL_MS = 33;

export default function LiveBrowserCanvas({ apiBase, userId, sessionId, onStatus, onHumanGate, onLiveControl, resumeRequest = 0 }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const frameRef = useRef<Frame | null>(null);
  const rafRef = useRef<number | null>(null);
  const lastMouseMoveRef = useRef(0);
  const lastResumeRequestRef = useRef(0);
  const dimensionsRef = useRef({ width: 1280, height: 720 });

  const [control, setControl] = useState<LiveControl>('locked');
  const [mode, setMode] = useState<'ai' | 'human'>('ai');
  const [connected, setConnected] = useState(false);
  const [phase, setPhase] = useState('Connecting live browser…');
  const [agentMessage, setAgentMessage] = useState('Connecting to Formwise live session.');
  const [pauseReason, setPauseReason] = useState<string | null>(null);
  const [resumeAllowed, setResumeAllowed] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const publishControl = useCallback((nextControl: LiveControl, nextMode: 'ai' | 'human', paused: boolean) => {
    setControl(nextControl); setMode(nextMode); onLiveControl?.({ control: nextControl, mode: nextMode, paused });
  }, [onLiveControl]);

  const drawLatestFrame = useCallback(() => {
    rafRef.current = null;
    const canvas = canvasRef.current; const frame = frameRef.current;
    if (!canvas || !frame) return;
    const image = new Image();
    image.onload = () => { const ctx = canvas.getContext('2d'); if (!ctx) return; if (canvas.width !== frame.width || canvas.height !== frame.height) { canvas.width = frame.width; canvas.height = frame.height; } ctx.clearRect(0, 0, canvas.width, canvas.height); ctx.drawImage(image, 0, 0, frame.width, frame.height); dimensionsRef.current = { width: frame.width, height: frame.height }; };
    image.src = `data:image/jpeg;base64,${frame.data}`;
  }, []);
  const scheduleFrameDraw = useCallback(() => { if (rafRef.current === null) rafRef.current = requestAnimationFrame(drawLatestFrame); }, [drawLatestFrame]);
  const send = useCallback((payload: Record<string, unknown>) => { const socket = socketRef.current; if (!socket || socket.readyState !== WebSocket.OPEN) return false; socket.send(JSON.stringify(payload)); return true; }, []);

  useEffect(() => { if (resumeRequest && resumeRequest !== lastResumeRequestRef.current) { lastResumeRequestRef.current = resumeRequest; send({ type: 'human.resume' }); } }, [resumeRequest, send]);

  const connect = useCallback(async () => {
    setError(null); setPhase('Requesting secure live capability…');
    try {
      const response = await fetch(`${apiBase}/v1/browser/sessions/${sessionId}/live-token`, { method: 'POST', headers: { 'X-User-ID': userId } });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || `Live token request failed (${response.status})`);
      const socket = new WebSocket(apiToWebSocketUrl(apiBase, sessionId, payload.live_token)); socketRef.current = socket;
      socket.onopen = () => { setConnected(true); publishControl('locked', 'ai', false); setPhase('AI control active'); onStatus?.('Live browser connected. AI control is locked.'); };
      socket.onmessage = event => {
        let message: LiveSocketMessage; try { message = JSON.parse(event.data) as LiveSocketMessage; } catch { return; }
        switch (message.type) {
          case 'session.ready': publishControl(message.control, 'ai', false); setPhase('AI control active'); break;
          case 'browser.frame': frameRef.current = message; scheduleFrameDraw(); break;
          case 'agent.state': publishControl(message.control, 'ai', message.state === 'paused'); setPhase(message.message); setAgentMessage(message.message); break;
          case 'control.changed':
            publishControl(message.control, message.mode, message.paused); setResumeAllowed(message.resume_allowed); setPauseReason(message.reason); setPhase(message.control === 'unlocked' ? 'Human control active' : message.paused ? 'Workflow paused' : 'AI control active'); break;
          case 'human.required':
            publishControl(message.control, message.control === 'unlocked' ? 'human' : 'ai', true); setResumeAllowed(message.resume_allowed); setPauseReason(message.reason); setPhase(message.resume_allowed ? 'Action required' : 'Workflow paused'); setAgentMessage(message.message); onStatus?.(message.message); onHumanGate?.({ reason: message.reason, message: message.message, resume_allowed: message.resume_allowed }); break;
          case 'resume.rejected': setError(message.message || 'Resume was rejected by the safety policy.'); break;
          case 'input.rejected': setError(`Remote input rejected: ${message.reason}`); break;
          case 'error': setError(`Live browser error: ${message.code}`); break;
          default: break;
        }
      };
      socket.onerror = () => { setError('Live browser connection error.'); onStatus?.('Live browser connection error.'); };
      socket.onclose = () => { setConnected(false); publishControl('locked', 'ai', false); setPhase('Live browser disconnected'); };
    } catch (err) { const message = err instanceof Error ? err.message : 'Unable to connect to live browser.'; setError(message); setPhase('Live browser unavailable'); onStatus?.(message); }
  }, [apiBase, onHumanGate, onLiveControl, onStatus, publishControl, scheduleFrameDraw, sessionId, userId]);

  useEffect(() => { void connect(); return () => { socketRef.current?.close(1000, 'component unmounted'); if (rafRef.current !== null) cancelAnimationFrame(rafRef.current); }; }, [connect]);

  const interactive = isHumanInputEnabled(control, mode);
  const pointFromEvent = (event: React.PointerEvent<HTMLCanvasElement>) => { const rect = event.currentTarget.getBoundingClientRect(); return scalePoint(event.clientX, event.clientY, rect, dimensionsRef.current.width, dimensionsRef.current.height); };
  const handlePointerMove = (event: React.PointerEvent<HTMLCanvasElement>) => { if (!interactive) return; const now = performance.now(); if (now - lastMouseMoveRef.current < MOUSE_MOVE_INTERVAL_MS) return; lastMouseMoveRef.current = now; const point = pointFromEvent(event); send({ type: 'input.mouse', event: 'move', x: point.x, y: point.y }); };
  const handlePointerDown = (event: React.PointerEvent<HTMLCanvasElement>) => { if (!interactive) return; event.currentTarget.focus(); const point = pointFromEvent(event); send({ type: 'input.mouse', event: 'down', button: event.button === 2 ? 'right' : event.button === 1 ? 'middle' : 'left', x: point.x, y: point.y }); };
  const handlePointerUp = (event: React.PointerEvent<HTMLCanvasElement>) => { if (!interactive) return; const point = pointFromEvent(event); send({ type: 'input.mouse', event: 'up', button: event.button === 2 ? 'right' : event.button === 1 ? 'middle' : 'left', x: point.x, y: point.y }); };
  const handleWheel = (event: React.WheelEvent<HTMLCanvasElement>) => { if (!interactive) return; event.preventDefault(); send({ type: 'input.wheel', delta_x: event.deltaX, delta_y: event.deltaY }); };
  const handleKeyDown = (event: React.KeyboardEvent<HTMLCanvasElement>) => { if (!interactive) return; event.preventDefault(); send({ type: 'input.key', event: 'down', key: event.key }); };
  const handleKeyUp = (event: React.KeyboardEvent<HTMLCanvasElement>) => { if (!interactive) return; event.preventDefault(); send({ type: 'input.key', event: 'up', key: event.key }); };
  const resume = () => send({ type: 'human.resume' });

  return <section className={`live-browser-card ${interactive ? 'human-active' : 'ai-locked'}`}>
    <div className="live-browser-header"><div><div className="live-browser-title">Live Browser Session</div><div className="live-browser-subtitle">Playwright viewport · server-authoritative control</div></div><span className={`live-browser-badge ${connected ? 'online' : 'offline'}`}>{connected ? '● LIVE' : '● OFFLINE'}</span></div>
    <div className="live-browser-stage"><canvas ref={canvasRef} className="live-browser-canvas" tabIndex={interactive ? 0 : -1} aria-label="Live remote browser viewport" onContextMenu={event => event.preventDefault()} onPointerMove={handlePointerMove} onPointerDown={handlePointerDown} onPointerUp={handlePointerUp} onWheel={handleWheel} onKeyDown={handleKeyDown} onKeyUp={handleKeyUp}/>{!connected && <div className="live-browser-empty">{phase}</div>}<div className="live-browser-overlay"><span className="live-browser-lock">{interactive ? '🔓 HUMAN CONTROL' : '🔒 AI CONTROL'}</span><span>{phase}</span></div></div>
    <div className={`live-browser-status ${interactive ? 'attention' : ''}`}><strong>{interactive ? 'Action Required' : phase}</strong><span>{agentMessage}</span>{pauseReason && <small>Gate: {pauseReason.toUpperCase()}</small>}</div>
    {interactive && resumeAllowed && <div className="live-browser-human-panel"><div><strong>Complete the required human step on the live screen.</strong><span>The backend will re-lock the browser only after its gate verifier accepts the step.</span></div><button className="primary" onClick={resume}>Done / Resume AI</button></div>}
    {error && <div className="live-browser-error" role="alert">{error}</div>}
  </section>;
}
