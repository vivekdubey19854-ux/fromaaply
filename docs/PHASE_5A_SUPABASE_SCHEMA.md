# Phase 5-A — Supabase Schema + Secure Repository Layer

## Purpose

Phase 5-A establishes the database contract for real verified user data. Browser Use and Playwright are not given database credentials or unrestricted queries. They will receive only minimal, provenance-backed values through the later data gateway.

## Tables

| Table | Purpose | Required security metadata |
|---|---|---|
| `profiles` | Core identity/profile | `user_id`, `confidence`, `verification_status` |
| `addresses` | Address records | `user_id`, `confidence`, `verification_status` |
| `education` | Education records | `user_id`, `confidence`, `verification_status` |
| `documents` | Private document metadata | `user_id`, `confidence`, `verification_status` |
| `document_extractions` | OCR/extraction output | `user_id`, `confidence`, `verification_status` |
| `field_provenance` | Field value + source + verification | `user_id`, `confidence`, `verification_status` |
| `knowledge_chunks` | Per-user retrieval chunks | `user_id`, `confidence`, `verification_status` |
| `verification_records` | Verification state transitions | `user_id`, `confidence`, `new_status` |
| `audit_logs` | Security/audit trail | `user_id`, `confidence`, `verification_status` |

## Verification lifecycle

`uploaded/processing -> extracted -> review_required -> verified -> revoked`

Only `verified` and non-revoked `field_provenance` rows are eligible for the Phase 5-B data gateway. If multiple verified sources disagree, the repository returns `conflict` and does not select a winner.

## RLS / Data API

Every table has RLS enabled. `anon` has no table privileges. `authenticated` receives table privileges but policies restrict rows to `(select auth.uid())::text = user_id`. UPDATE policies use both `USING` and `WITH CHECK` so a caller cannot move a row to another user's tenant.

This explicit-grant approach is intentional because Supabase is moving to no automatic Data API exposure for newly created public tables; new projects already use the safer model and the change is scheduled to reach existing projects on October 30, 2026.

## Files

- `supabase/migrations/20260912000000_phase5a_schema_provenance.sql` — production Supabase/Postgres SQL migration with RLS and explicit grants.
- `backend/migrations/versions/0002_phase5a_provenance.py` — Alembic migration for the existing FastAPI database contract.
- `backend/app/verified_data_repository.py` — narrow repository boundary for verified field reads, conflict detection and verification events.
- `backend/tests/test_verified_data_repository.py` — fail-closed repository tests.

## Boundary rule

`browser_use_agent.py` must not import or instantiate this repository directly. Phase 5-B will introduce the Agent Data Gateway, which will enforce field allowlists, verification thresholds, provenance minimization and conflict handling before any value reaches browser automation.
