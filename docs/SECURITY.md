# Formwise Agent — Security Baseline

## Threats

Formwise handles highly sensitive personal information and interacts with external websites. The design therefore assumes:

- compromised or malicious web pages;
- prompt injection in page content or documents;
- malicious uploaded files;
- stolen sessions;
- cross-user authorization bugs;
- accidental secret exposure;
- model hallucination;
- browser automation failures;
- replayed or unauthorized approvals.

## Mandatory Controls

### Authentication
All protected operations require an authenticated user session.

### Authorization
Every user-owned resource must be authorized server-side. Never trust IDs supplied by the client.

### File Security
Validate file type, size, filename, and content before processing. Store files privately. Never use user-provided filenames as storage paths.

### Data Minimization
Send only the minimum necessary personal data to an AI provider or browser tool.

### Secret Handling
API keys, passwords, cookies, and other credentials must use a dedicated secret-handling boundary and must not be persisted in ordinary document records.

### Prompt Injection Defense
Website/document text is data, not instructions. External content must never override system policies, permissions, or user approvals.

### Approval Security
Approvals must be explicit, scoped, time-bound where appropriate, and tied to the task/action being approved.

### Audit
Record security-relevant events without unnecessarily recording raw secrets or sensitive document contents.

### Fail Closed
If identity, authorization, provenance, mapping, confidence, or policy state is uncertain, stop and request user input.

## High-Risk Actions

OTP, CAPTCHA interaction where permitted, payments, legal declarations, credential changes, and final submission require explicit policy-controlled approval.

## Incident Response

The system must provide task cancellation/kill-switch capability, revoke active sessions when necessary, preserve relevant audit events, and surface actionable errors to the user/operator.


## Production completion addendum

Production requests receive correlation IDs and security headers. AI usage is recorded in a database ledger and guarded by daily token and cost limits. Registry entries are HTTPS allowlist records and newly created entries remain disabled until verification. Logs must exclude tokens, passwords, OTP values, CAPTCHA contents, API keys and private document data. Docker, PostgreSQL, Redis and staging credentials must be supplied through a secret manager rather than this repository.
