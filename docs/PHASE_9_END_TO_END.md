# Phase 9 — End-to-End Form Filling

Phase 9 connects the existing profile/document knowledge base, browser session, deterministic form mapping, and approval engine into one controlled execution flow.

## Flow
1. User creates a controlled browser session for an allowed HTTPS/HTTP destination.
2. `/v1/e2e/plan` inspects the page and maps supported controls.
3. Stored knowledge is resolved into deterministic proposals. Missing or ambiguous values are not invented.
4. Sensitive proposals are marked for explicit approval.
5. `/v1/e2e/approvals` creates a short-lived approval bound to the exact session, field, index and value.
6. `/v1/e2e/fill` fills mapped controls and consumes the matching approval for sensitive fields.
7. The response returns filled/blocked items and requires human review.

## Hard safety boundaries
- Never clicks a final Submit button.
- Never bypasses CAPTCHA, reCAPTCHA, hCaptcha or other anti-bot mechanisms.
- Never automates OTP entry, payments, legal declarations or final submission.
- Does not silently overwrite an already populated field.
- A stale mapping is rejected.
- Sensitive-field execution requires an exact, short-lived approval.
- Provenance is returned as source type/source id; raw personal values are not placed in audit events.

## Example API sequence
```text
POST /v1/browser/sessions
POST /v1/e2e/plan
POST /v1/e2e/approvals       # for each sensitive proposal
POST /v1/e2e/fill
GET  /v1/browser/sessions/{id}/screenshot
```

The existing temporary `X-User-ID` authentication adapter remains a production blocker. Phase 9 does not change that authentication boundary.

The existing `/v1/forms/fill` endpoint is retained for compatibility; new integrations should use `/v1/e2e/fill` because it enforces the Phase 8 approval workflow.
