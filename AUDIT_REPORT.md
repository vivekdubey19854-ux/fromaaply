# Formwise Repository Audit Report

**Audit date:** 2026-09-21  
**Repository:** [vivekdubey19854-ux/fromaaply][1]  
**Audited requirements:** `pasted_content_4.txt` and the current source tree at commit `d19749d`, including the audit fixes made during this review.

## Executive conclusion

The repository contains a substantial working foundation for a secure form-assistance product. Authentication, token revocation, one-time password-reset and verification tokens, private document handling, OCR/verified-data workflows, server-side browser safety, live browser frame streaming, AI failover adapters, payment webhook idempotency, and an admin website registry are implemented.

The repository is **not yet a complete production universal portal**. The largest remaining gaps are operational rather than cosmetic: durable browser workers, real provider credentials, storage-provider routing, website-specific registry data, complete admin API wiring, usage/cost accounting, subscription/refund reconciliation, and a real Admin AI action layer.

During this audit, two code changes were made. The payment checkout verification route was added and the Razorpay ledger lookup was corrected for the first-party `auth_users` schema while retaining a legacy Supabase compatibility fallback. The admin dashboard's headline metrics were changed from synthetic revenue/worker/uptime figures to API-backed values or explicit unavailable states.

## Requirement-by-requirement status

| Requirement | Status | Evidence and remaining work |
|---|---|---|
| Real live browser screen with backend frames | **Implemented foundation** | `live_browser.py` captures real Playwright JPEG screenshots and sends them over an authenticated WebSocket. `LiveBrowserCanvas.tsx` consumes frames and gates human input. Durable workers, reconnect recovery, multi-instance state, and production browser deployment remain. |
| Multi-AI production gateway | **Partial** | `ai_provider_adapter.py` has provider aliases, native/OpenAI-compatible handlers, timeouts, failover, and audit callbacks. The admin UI does not yet expose real model, priority, quota, cost, error-rate, or test-connection data. Usage accounting and provider health persistence are missing. |
| Multi-website database | **Partial** | `website_registry` migration and admin list/create APIs exist with HTTPS and allowed-domain validation. The registry is not populated with verified official portals, and website version, OTP/CAPTCHA/payment/legal stages, health checks, and field-mapping fields are only implicit in an untyped JSON config. |
| Razorpay order-to-ledger flow | **Implemented core** | Order creation, encrypted credentials, checkout signature verification, the new `/payments/verify` settlement route, webhook HMAC verification, duplicate-event protection, amount matching, wallet crediting, and receipt notification exist. Subscription plans, retries, refunds, reconciliation jobs, and full coupon-to-payment integration remain. |
| Production document storage | **Partial** | Local private storage and an S3-compatible failover adapter exist. The document routes currently use local `PrivateStorage`; the multi-cloud adapter is not the selected route, signed temporary URLs are not implemented, and provider health/usage/retention/backup controls are absent. |
| Live admin panel | **Partial** | Server-side admin authorization, encrypted provider-key update, pricing/coupon endpoints, database-backed summary, and website APIs exist. The dashboard still contains non-live provider/auth/storage/referral sections and static health claims. Users, payments, browser sessions, AI usage, storage, jobs, and audit-log screens are not fully API-wired. |
| Admin AI assistant | **Not implemented as a system assistant** | The visible command panel records local command text and toggles a few local UI states. It does not query operational data, execute guarded server actions, or provide confirmation workflows for disable/refund/delete/mass-marketing/provider actions. |
| Production deployment | **Not implemented** | CI workflows and a health route exist. There is no complete deployment manifest, durable queue/Redis worker, browser-worker topology, secret manager configuration, TLS/WSS deployment, backup/restore drill, monitoring/error tracking, or rate-limit/WAF setup. |

## Security and data-flow findings

The live browser token is short-lived, single-use, hashed in memory, and bound to the browser session and user. Human gates can unlock input only for CAPTCHA, OTP, legal declaration, payment, or verification conditions. The final website Submit control remains a manual human action.

Authentication now includes password hashing, access and refresh tokens, refresh-token revocation, logout, hashed one-time action tokens, expiry, and one-time use. Production email delivery is intentionally disabled until a provider is configured; raw action tokens are not returned in production responses.

Documents uploaded through the current user routes are stored under the private local storage adapter and returned through authenticated download routes. This is safer than exposing public URLs, but it is not the requested production object-storage architecture. The S3-compatible adapter currently returns a constructed object URL rather than a signed temporary URL and is not wired into the primary document route.

## Audit fixes applied in this review

1. Added `/payments/verify` to verify the Razorpay checkout signature and settle the matching ledger transaction.
2. Corrected the payment ledger's primary email lookup to `auth_users(user_id)` and retained a legacy fallback for existing Supabase fixtures.
3. Replaced fabricated admin headline values such as revenue, worker saturation, uptime, and user counts with API-backed values or explicit unavailable states.
4. Added a database-backed admin summary fetch to the dashboard.
5. Disabled unconfigured phone, social, and email gateway claims in the admin UI.
6. Added durable task lifecycle tables for tasks, steps, browser sessions, session events, workflow events, and task locks.
7. Added ownership-scoped task APIs with idempotent creation, state-machine validation, leases, retries, and resume references.

## Verification results

The final backend run after the runtime slice completed with **137 passed tests**. The frontend suite completed with **4 passed tests**, and the Vite production build completed successfully. Python compilation and `git diff --check` also passed during the audit.

The test suite has warnings for the development JWT secret length, legacy `datetime.utcnow()` usage, and Alembic's legacy path separator setting. These warnings do not fail the suite, but they should be cleaned before a production release.

## Recommended release order

First, deploy the current foundation to a staging environment with PostgreSQL and a real secret manager. Then configure one email provider, one AI provider, one object-storage provider, and Razorpay test credentials. After that, wire the admin dashboard to provider, storage, payment, browser-session, and audit APIs. Finally, populate the website registry only with verified official URLs and run a real browser test for each portal before enabling it for users.

Until these steps are completed, the correct product label is **secure beta foundation**, not a fully operational universal production portal.

## References

[1]: https://github.com/vivekdubey19854-ux/fromaaply "Formwise repository"


## Production completion addendum — 2026-09-22

The repository now includes a durable `ai_usage_ledger` with provider, model, request, task, user, token, latency, status, fallback and estimated-cost fields. The adapter applies a daily token and cost guard before eligible user calls and records successful and failed provider attempts. Migration `0013_ai_usage_ledger` is the schema authority.

Migration `0014_registry_production` adds verified status, version, health status, health-check timestamps, allowed paths, supported fields and mapping metadata. It seeds only official HTTPS domains for SSC, UPSC, National Scholarship Portal and NTA. Newly created registry records remain disabled and unverified until administrator verification.

The admin API now exposes live users, AI usage, tasks, browser sessions, payments, storage nodes, audit logs, websites, summary counts and health. The dashboard consumes live summary, user and AI usage APIs and displays unavailable states instead of fabricated operational metrics.

Production container files are present at the repository root, with PostgreSQL, Redis authentication, API, durable worker/browser worker and frontend services in `docker-compose.production.yml`. The deployment package includes `.env.production.example`, Nginx routing, backup validation, CI PostgreSQL/Redis services and `docs/DEPLOYMENT.md`.

The local verification result is **142 backend tests passed**, **4 frontend tests passed**, a successful frontend production build, successful Python compilation, one Alembic head at `0014_registry_production`, and no Alembic drift. Docker, PostgreSQL and Redis could not be executed in this sandbox because their local daemons/CLI are unavailable. Real credential and staging validation therefore remains an external release requirement rather than a claimed local completion.


## Final remaining production pass — 2026-09-22

The AI policy layer now supports database-configured provider enablement, priority, daily/monthly token and cost limits, request-per-minute limits, cooldown checks and provider health counters. Calls with authenticated user metadata record provider health and usage data; fallback remains bounded and policy failures fail closed for disabled or quota-limited providers.

Payment controls now include retry state handling, expiry handling, refund ledger requests, server-side Razorpay refund invocation, reconciliation records, unmatched-order reconciliation and admin reconciliation endpoints. Refund and other high-risk admin actions use an authorization, preview and explicit-confirmation sequence. Unsupported destructive actions are denied rather than executed.

Website registry health checks validate HTTPS, verified state and allowed official hostname before requesting the site. Results persist as healthy, degraded or down history. Three consecutive failures disable a site through the safe policy. Manual enablement requires verified and healthy state. A dedicated scheduler worker runs the checks every five minutes.

Admin AI is now a deterministic server-side read-only operational assistant. It reads database-backed users, tasks, browser sessions, AI usage and failed-task counts. Mutations cannot be issued through the assistant query endpoint. High-risk actions require a preview and confirmation record tied to the authenticated admin, with expiry and audit logging.

The final deterministic suite passes **145 backend tests**. Frontend tests and production build pass. Local PostgreSQL, Redis and Docker execution remain unavailable in the sandbox, so staging credentials and live provider verification remain external requirements.


## Unified platform expansion — 2026-09-22

The final expansion adds an extensible provider control plane. The runtime catalog contains 24 AI providers and OmniRoute, including direct SDK handlers and generic OpenAI-compatible providers. Capabilities, reasoning flags, free-tier classification, model discovery, priority, fallback order, quota, RPM, cooldown and health are represented in durable registries. OmniRoute is optional and direct-provider operation remains independent.

Storage configuration now has a private encrypted registry for Oracle Object Storage, Cloudflare R2, Backblaze B2, Firebase Storage and Supabase Storage, with capacity/quota fields and generic S3-compatible failover integration. Authentication configuration now has Firebase, Supabase, Clerk, Stytch and Descope registries plus separate canonical identity mappings and a public enabled-methods capability endpoint.

Admin APIs expose masked live provider, storage and authentication state, encrypted credential rotation, model discovery, connection testing and priority/fallback configuration. No credential is returned in an API response. Deterministic tests cover the 20+ catalog, generic provider dispatch, secret-safety contract and existing storage failover.


## Real multi-provider authentication — 2026-09-23

The authentication layer now supports durable email/password sessions, refresh rotation, revocation and logout; Google OAuth authorization-code flow with one-time state, nonce and short-lived handoff exchange; provider-issued token verification for Firebase, Supabase Auth, Clerk, Stytch and Descope; phone OTP request/verification through configured provider adapters; canonical Formwise identity resolution; and secure account linking that rejects identities already owned by another account or unverified email collisions.

Provider routing falls back only on provider outage or timeout. Invalid passwords, OTP codes, OAuth codes and external identity tokens fail immediately without trying another provider. Admin APIs manage provider credentials, OAuth/JWKS/OTP endpoints, enablement, priority, fallback methods and configuration while returning masked metadata only. Production dev-token issuance remains disabled.

The repository implementation is credential-ready. Real Google, Firebase, Supabase, Clerk, Stytch, Descope and SMS-provider credentials plus redirect URLs must still be configured in staging before external end-to-end smoke testing.


## Final end-to-end completion pass — 2026-09-24

Implemented in this pass: durable platform settings for branding, real marketing insight and draft APIs, read-only Admin AI summaries across users/tasks/payments/refunds/storage/websites, worker lease summaries, real storage-provider bucket probes, authentication-provider configuration probes, storage failover on configuration errors, and confirmation-gated refund execution in the admin UI. Synthetic referral, banner, and refund-history metrics are no longer presented as live operational data.

Locally tested: 152 backend tests, frontend tests and production build, Python compilation, Alembic head/check, diff validation, and secret scan. Real PostgreSQL/Redis/Playwright and external provider validation remain environment-dependent and are not claimed here.

External validation required: configure provider credentials and execute staging smoke tests for AI, storage, authentication, Razorpay, email/SMS, Redis/PostgreSQL, browser workers, and official portals.
