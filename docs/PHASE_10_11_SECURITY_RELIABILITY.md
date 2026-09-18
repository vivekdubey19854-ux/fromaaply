# Phase 10–11 Complete

Formwise now has verified JWT authentication, production startup security checks, controlled browser/network boundaries, approval-bound sensitive filling, stale mapping protection, private per-user storage, and release/test documentation.

Production configuration:
- `FORMWISE_ENVIRONMENT=production`
- `FORMWISE_JWT_SECRET` must be a strong 32+ character secret
- `FORMWISE_ALLOW_LEGACY_USER_HEADER=false`

Never commit secrets or personal documents. Use HTTPS and deployment-level rate limiting. Apply Alembic migrations and install Playwright browser dependencies before deployment.

The agent intentionally never bypasses CAPTCHA/anti-bot, automates OTP, performs payment, accepts legal declarations, or clicks final Submit. Those actions remain human-controlled.

End-to-end complete means the secure backend workflow is implemented; third-party websites with unusual or changing HTML may still require a site-specific adapter.
