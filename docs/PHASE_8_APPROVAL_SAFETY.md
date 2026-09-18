# Phase 8 — Approval + Permission + Safety Engine

Phase 8 adds a server-side approval gate for materially consequential actions.

## Rules

- Sensitive personal fields require an explicit approval record before execution.
- Approval is bound to the exact action, resource and payload fingerprint.
- Approvals expire after a short configurable TTL (30 seconds to 1 hour).
- An approval cannot be reused as a different action/resource/payload.
- CAPTCHA, anti-bot bypass, OTP handling, payment, legal declarations and final submission are hard-blocked from this approval mechanism.
- Approval records are stored inside the user's private storage namespace.
- Audit events contain identifiers only; personal field values are not written to logs.
- User isolation is enforced by the existing private-storage keying.

## API

`POST /v1/approvals` creates a pending approval request.

`GET /v1/approvals/{approval_id}` retrieves the user's own approval.

`POST /v1/approvals/{approval_id}/approve` approves only if action, resource and payload are byte-for-byte represented by the same deterministic fingerprint used when the request was created.

The approval layer is intentionally separate from final browser submission. Later execution code must consume an approved record and must never silently downgrade a blocked action.

## Production note

The current authentication adapter uses the temporary `X-User-ID` header from the foundation. Production deployment must replace it with a verified session/JWT before exposing personal-data operations publicly.
