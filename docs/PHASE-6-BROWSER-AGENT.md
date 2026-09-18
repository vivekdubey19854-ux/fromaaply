# Phase 6 — Browser Agent + Playwright

Phase 6 adds a controlled browser runtime for Formwise Agent. It can open and inspect supported HTTP(S) pages, enumerate forms and interactive controls, navigate to another approved URL, and capture a private screenshot.

## Endpoints

All endpoints require the current temporary `X-User-ID` authentication adapter.

- `POST /v1/browser/sessions` — create an isolated Chromium session and open a URL.
- `POST /v1/browser/sessions/{session_id}/navigate` — navigate the existing session.
- `GET /v1/browser/sessions/{session_id}/inspect` — read-only form/control inspection.
- `GET /v1/browser/sessions/{session_id}/screenshot` — capture a private PNG screenshot.
- `DELETE /v1/browser/sessions/{session_id}` — close the session.

## Safety boundary

- Only HTTP(S) URLs are accepted.
- URLs containing embedded credentials are rejected.
- localhost, loopback, link-local, multicast, reserved, unspecified, and private-network destinations are rejected by default.
- Browser requests are intercepted and checked, including redirects/subresources.
- Downloads are disabled.
- Service workers are blocked.
- Each user is limited to a small number of active sessions.
- Form submission is never exposed by the Phase 6 API.
- CAPTCHA/anti-bot bypass is not implemented.
- OTP, payment, legal declarations, and final submission remain explicit approval checkpoints for later phases.
- Audit events do not contain form values or document contents.

## Runtime setup

After installing Python dependencies, install the Chromium browser binary in the deployment image/environment:

```bash
python -m playwright install chromium
```

For Debian/Ubuntu CI or a container where system libraries are missing, use Playwright's dependency installation mechanism instead.

## Important limitation

Browser sessions are intentionally process-local in this phase. A restart closes all sessions. Durable browser profiles, distributed workers, form-field mapping, approval workflows, and production authentication are implemented in later phases.
