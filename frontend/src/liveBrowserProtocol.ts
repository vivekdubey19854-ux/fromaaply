export type LiveControl = 'locked' | 'unlocked';

export type LiveSocketMessage =
  | { type: 'session.ready'; session_id: string; control: LiveControl; mode: 'ai'; state: string }
  | { type: 'browser.frame'; data: string; width: number; height: number; control: LiveControl; seq: number; timestamp: number }
  | { type: 'agent.state'; state: 'running' | 'paused'; step: string; message: string; control: LiveControl }
  | { type: 'control.changed'; control: LiveControl; mode: 'ai' | 'human'; paused: boolean; reason: string | null; resume_allowed: boolean }
  | { type: 'human.required'; state: 'paused'; reason: string; control: LiveControl; message: string; resume_allowed: boolean }
  | { type: 'resume.rejected'; reason: string; message?: string }
  | { type: 'input.rejected'; reason: string }
  | { type: 'pong'; timestamp: number }
  | { type: 'error'; code: string };

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export function scalePoint(
  clientX: number,
  clientY: number,
  rect: Pick<DOMRect, 'left' | 'top' | 'width' | 'height'>,
  sourceWidth: number,
  sourceHeight: number,
) {
  const x = rect.width > 0 ? ((clientX - rect.left) / rect.width) * sourceWidth : 0;
  const y = rect.height > 0 ? ((clientY - rect.top) / rect.height) * sourceHeight : 0;
  return {
    x: clamp(x, 0, sourceWidth),
    y: clamp(y, 0, sourceHeight),
  };
}

export function isHumanInputEnabled(control: LiveControl, mode: 'ai' | 'human'): boolean {
  return control === 'unlocked' && mode === 'human';
}

export function apiToWebSocketUrl(apiBase: string, sessionId: string, token: string): string {
  const url = new URL(`/v1/browser/sessions/${sessionId}/live`, apiBase);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  url.searchParams.set('token', token);
  return url.toString();
}
