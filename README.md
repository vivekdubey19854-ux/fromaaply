# Formwise Agent

> Privacy-first AI agent for researching and preparing online forms from user-approved personal data and documents.

## Current status

The repository now contains the core end-to-end workflow: research → user confirmation → document/OCR readiness checks → controlled browser → human-supplied OTP → deterministic field mapping → sensitive-field approvals → field-by-field screenshots → final review → explicit final-submit approval.

The workflow is intentionally **not a CAPTCHA/anti-bot bypasser** and never invents personal data.

## Example request

> “SSC CHSL 2026 ka form bhar do.”

Formwise researches official information, presents it for confirmation, checks the user's private document vault, opens the supported application site, pauses for OTP, proposes verified field values, asks for sensitive-field approvals, captures screenshots while filling, and stops for final review. Submission occurs only after an explicit final approval.

## Core safety rules

- Never guess or fabricate personal information.
- Never bypass CAPTCHA, reCAPTCHA, hCaptcha, or anti-bot controls.
- OTP is entered only when the user explicitly provides it.
- Payments are not automated.
- Legal declarations require human review.
- Final submission requires a short-lived, exact-payload approval token.
- All workflow state and screenshots are private per user.
- User ownership checks are enforced on profile, documents, approvals, browser sessions, knowledge and workflow data.

## Research

The backend supports an optional Serper provider (`FORMWISE_SERPER_API_KEY`) and a public DuckDuckGo HTML fallback. For SSC workflows, official `ssc.gov.in` / government sources are preferred. If current research cannot be obtained, Formwise does not fabricate dates, fees, eligibility, or notification details.

## Main workflow API

- `POST /v1/workflows` — start research-driven task
- `GET /v1/workflows/{workflow_id}` — inspect private workflow state
- `POST /v1/workflows/{workflow_id}/confirm` — confirm research / re-check documents
- `POST /v1/workflows/{workflow_id}/open` — open application after readiness
- `POST /v1/workflows/{workflow_id}/otp` — continue with user-supplied OTP
- `POST /v1/workflows/{workflow_id}/plan` — inspect and map the current form
- `POST /v1/workflows/{workflow_id}/fill` — fill approved values and capture step screenshots
- `GET /v1/workflows/{workflow_id}/screenshot` — authenticated latest private screenshot
- `POST /v1/workflows/{workflow_id}/final-approval` — create exact final-submit approval
- `POST /v1/workflows/{workflow_id}/submit` — submit only with valid final approval

## Development

Backend tests run through GitHub Actions. Frontend build verification runs through a separate GitHub Actions workflow.

Production authentication requires a verified JWT; the legacy `X-User-ID` development header must be disabled in production.


## Unified provider control plane

Formwise now includes a database-backed control plane for **24 AI providers plus OmniRoute**, with extensible OpenAI-compatible adapters, capability metadata, reasoning flags, model discovery, free-tier classification, quota/rate/cooldown policy, health tracking and bounded failover. OmniRoute is treated as an optional federation gateway rather than a required dependency; direct providers remain available when it is unavailable.

The control plane also supports private storage provider records for Oracle Object Storage, Cloudflare R2, Backblaze B2, Firebase Storage and Supabase Storage. S3-compatible credentials are encrypted at rest, storage remains private by default, and uploads/downloads use primary-plus-failover routing with signed URLs.

Authentication configuration includes Firebase, Supabase, Clerk, Stytch and Descope provider records. The public authentication capability endpoint exposes only enabled login methods; provider secrets never leave the server. The canonical Formwise user remains the application identity, while external identity mappings are stored separately.

System-admin APIs under `/v1/admin` manage AI provider policy and credentials, model discovery, storage capacity and credentials, authentication provider methods, provider tests, health, priority and fallback order. All configuration changes require server-side admin authorization and secrets are masked in responses.
