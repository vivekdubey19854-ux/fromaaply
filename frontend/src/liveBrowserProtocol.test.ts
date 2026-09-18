import { describe, expect, it } from 'vitest';
import { apiToWebSocketUrl, isHumanInputEnabled, scalePoint } from './liveBrowserProtocol';

describe('live browser protocol helpers', () => {
  it('maps CSS canvas coordinates into remote viewport coordinates', () => {
    const point = scalePoint(200, 150, { left: 100, top: 50, width: 400, height: 200 }, 1200, 600);
    expect(point).toEqual({ x: 300, y: 300 });
  });

  it('clamps coordinates outside the visible canvas', () => {
    const point = scalePoint(50, 400, { left: 100, top: 50, width: 400, height: 200 }, 1200, 600);
    expect(point).toEqual({ x: 0, y: 600 });
  });

  it('only enables remote input for an unlocked human session', () => {
    expect(isHumanInputEnabled('locked', 'ai')).toBe(false);
    expect(isHumanInputEnabled('unlocked', 'ai')).toBe(false);
    expect(isHumanInputEnabled('locked', 'human')).toBe(false);
    expect(isHumanInputEnabled('unlocked', 'human')).toBe(true);
  });

  it('converts HTTPS API endpoints to WSS without persisting the token', () => {
    const url = apiToWebSocketUrl('https://example.com', 'session-123', 'one-time-token');
    expect(url).toBe('wss://example.com/v1/browser/sessions/session-123/live?token=one-time-token');
  });
});
