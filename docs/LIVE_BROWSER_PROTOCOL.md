# Formwise Live Browser WebSocket Protocol

This feature exposes a session-scoped, one-time authenticated WebSocket for a Playwright browser session. The browser viewport is streamed as JPEG frames encoded in JSON. Remote mouse/keyboard input is accepted only while the server-side control state is `unlocked` and `mode` is `human`.

## 1. Capability token

```http
POST /v1/browser/sessions/{session_id}/live-token
X-User-ID: <development-user-id>
```

Response:

```json
{
  "session_id": "<session-id>",
  "live_token": "<one-time-token>",
  "ws_url": "wss://api.example.com/v1/browser/sessions/<session-id>/live?token=<one-time-token>",
  "expires_in": 300
}
```

The token is session-scoped, short-lived, hashed server-side, and single-use. Production deployments must use HTTPS/WSS and should redact query parameters from access logs.

## 2. WebSocket

Connect to `ws_url`.

The server starts in AI-controlled mode:

```json
{
  "type": "session.ready",
  "version": 1,
  "session_id": "<session-id>",
  "control": "locked",
  "mode": "ai",
  "state": "ai_running"
}
```

## 3. Browser frames

Frames are JSON messages with base64 JPEG data:

```json
{
  "type": "browser.frame",
  "seq": 1042,
  "timestamp": 1789290000123,
  "width": 1280,
  "height": 720,
  "encoding": "jpeg",
  "quality": 60,
  "data": "<base64-jpeg>",
  "control": "locked"
}
```

## 4. AI state

Authenticated backend components can publish agent progress:

```http
POST /v1/browser/sessions/{session_id}/live/agent-state
Content-Type: application/json
X-User-ID: <user-id>
```

```json
{
  "step": "self_healing",
  "message": "Self-Healing Active..."
}
```

The server broadcasts:

```json
{
  "type": "agent.state",
  "state": "running",
  "step": "self_healing",
  "message": "Self-Healing Active...",
  "control": "locked"
}
```

## 5. Operational-policy pause

The WebSocket manager evaluates the same `operational_policy.py` classifier against the live page. CAPTCHA and OTP pauses become human-controlled:

```json
{
  "type": "human.required",
  "state": "paused",
  "reason": "captcha",
  "control": "unlocked",
  "message": "PAUSED: CAPTCHA detected. Please solve it manually.",
  "resume_allowed": true
}
```

Payment and legal-declaration pauses may unlock the browser for observation/manual interaction, but `resume_allowed` remains false. Final submission remains a hard stop.

## 6. Human input

Mouse:

```json
{"type":"input.mouse","event":"move","x":640,"y":350}
{"type":"input.mouse","event":"down","button":"left","x":640,"y":350}
{"type":"input.mouse","event":"up","button":"left","x":640,"y":350}
```

Wheel:

```json
{"type":"input.wheel","delta_x":0,"delta_y":520}
```

Keyboard:

```json
{"type":"input.key","event":"press","key":"Enter"}
```

If the server is locked, the event is rejected even if the frontend tries to send it:

```json
{"type":"input.rejected","reason":"control_locked"}
```

## 7. Resume

After the human completes CAPTCHA/OTP, the frontend sends:

```json
{"type":"human.resume"}
```

The backend verifies that the relevant field is actually populated before relocking the browser and resuming AI control. Otherwise:

```json
{
  "type":"resume.rejected",
  "reason":"human_gate_not_filled",
  "message":"Please complete the CAPTCHA/OTP in the live browser before resuming."
}
```

Successful resume broadcasts an `agent.state` event followed by `control.changed` with `control: locked` and `mode: ai`.

## 8. Security boundary

The frontend never grants itself control. `control=unlocked` is authoritative only when the backend sets it. Final submission is never made available as a remote input action by this protocol.
