# Formwise Repository Audit Report

**Audit date:** 2026-09-21  
**Repository:** [vivekdubey19854-ux/fromaaply][1]  
**Audited requirements:** `pasted_content_4.txt` and the current source tree at commit `d19749d`, including the audit fixes made during this review.

## Executive conclusion

The repository contains a substantial working foundation for a secure form-assistance product. Authentication, token revocation, one-time password-reset and verification tokens, private document handling, OCR/verified-data workflows, server-side browser safety, live browser frame streaming, AI failover adapters, payment webhook idempotency, and an admin website registry are implemented.

The repository is **not yet a complete production universal portal**. The largest remaining gaps are operational rather than cosmetic: production deployment, durable browser workers, real provider credentials, storage-provider routing, website-specific registry data, complete admin API wiring, usage/cost accounting, subscription/refund reconciliation, and a real Admin AI action layer.

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

## Verification results

The final backend run after the audit fixes completed with **134 passed tests**. The frontend suite completed with **4 passed tests**, and the Vite production build completed successfully. Python compilation and `git diff --check` also passed during the audit.

The test suite has warnings for the development JWT secret length, legacy `datetime.utcnow()` usage, and Alembic's legacy path separator setting. These warnings do not fail the suite, but they should be cleaned before a production release.

## Recommended release order

First, deploy the current foundation to a staging environment with PostgreSQL and a real secret manager. Then configure one email provider, one AI provider, one object-storage provider, and Razorpay test credentials. After that, wire the admin dashboard to provider, storage, payment, browser-session, and audit APIs. Finally, populate the website registry only with verified official URLs and run a real browser test for each portal before enabling it for users.

Until these steps are completed, the correct product label is **secure beta foundation**, not a fully operational universal production portal.

## References

[1]: https://github.com/vivekdubey19854-ux/fromaaply "Formwise repository"
