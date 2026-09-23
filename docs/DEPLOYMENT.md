# Formwise Production Deployment

The supported deployment topology is API, durable worker/browser worker, PostgreSQL, Redis, and the static frontend. `docker-compose.production.yml` supplies restart policies, health checks, Redis authentication, PostgreSQL persistence, Alembic startup migration, and graceful worker shutdown.

Copy `.env.production.example` to `.env.production` and generate fresh values for `JWT_SECRET`, `AUTH_TOKEN_PEPPER`, and `CREDENTIAL_ENCRYPTION_KEY`. Provider credentials must be injected through the deployment secret manager. They must not be committed to the repository.

Run `docker compose -f docker-compose.production.yml up -d --build`. Confirm `/health` and `/ready` before opening the frontend. `/ready` is degraded until both PostgreSQL and Redis respond successfully. Enable a website only after its official-domain verification and a safe browser smoke test. CAPTCHA, OTP, legal declarations, payment confirmation, and final submit remain human actions.

## Rollback

Keep the previous image digest and migration backup. Stop new workers, restore the previous image, and roll back only migrations that have an explicit tested downgrade. Do not downgrade a schema after application data has been written unless the restore drill has verified it. Restart API and workers, then confirm `/ready`, queue processing, and task lease recovery.

## Backup and restore

Run `POSTGRES_CONTAINER=... POSTGRES_DB=formwise POSTGRES_USER=formwise deploy/backup_restore.sh` daily. The script creates a PostgreSQL custom-format dump, validates its archive list, and removes dumps older than thirty days. A staging restore drill must create an isolated database, restore the dump, run `alembic check`, and verify `/ready` before the dump is accepted.

Object storage must use provider-side versioning and retention. Database backups and storage retention are infrastructure responsibilities and require real provider configuration before launch.

## External requirements

Real PostgreSQL, Redis, object-storage, email, AI, and Razorpay credentials are required for infrastructure validation. The repository contains no credentials and the local sandbox did not have Docker, PostgreSQL, or Redis daemons available; therefore those checks are covered by CI configuration and must be executed in staging.


## Provider control-plane configuration

After applying migrations through `0016_unified_provider_control_plane`, system administrators configure AI, OmniRoute, storage and authentication providers through authenticated Admin APIs. The deployment environment must provide `FORMWISE_CREDENTIAL_ENCRYPTION_KEY`; provider secrets are submitted only over the protected Admin API and are encrypted before database storage. Do not place provider keys in Git, frontend bundles or ordinary environment templates.

The first deployment should configure at least one direct AI provider and one private storage provider before enabling user workflows. OmniRoute is optional. Provider test and model-discovery endpoints report real reachability only after making the external request; unavailable credentials remain an explicit unavailable/configuration-error state.
