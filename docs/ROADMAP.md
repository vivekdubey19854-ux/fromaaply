# Formwise Agent — Implementation Roadmap

## Phase 1 — Architecture & Project Foundation
- Product requirements
- Architecture
- Security principles
- Domain model
- Repository conventions
- Development rules

## Phase 2 — Profile & Secure Document Vault
- Real profile data
- Addresses
- Education
- Secure upload
- Private storage
- Document metadata
- Ownership checks
- Audit events

## Phase 3 — OCR & Document Intelligence
- File preprocessing
- OCR pipeline
- Structured extraction
- Confidence scores
- Source provenance
- User verification

## Phase 4 — Personal Knowledge Base
- Normalized personal facts
- Retrieval layer
- Semantic search
- Provenance-aware retrieval
- Versioning

## Phase 5 — AI Agent
- Task planning
- Model provider abstraction
- Tool calling
- Structured outputs
- Policy-aware reasoning
- Agent state machine

## Phase 6 — Browser Agent
- Playwright
- Browser isolation
- Session management
- Navigation
- Page inspection
- Safe interaction tools

## Phase 7 — Form Mapping
- Form/field detection
- Label and semantic matching
- Source selection
- Confidence scoring
- Field-level evidence

## Phase 8 — Safety & Approval
- Permission engine
- Approval workflows
- Sensitive action checkpoints
- Kill switch
- Policy configuration

## Phase 9 — End-to-End Form Filling
- Supported website adapters
- Real task execution
- Review screen
- Resume/retry
- Submission boundary

## Phase 10 — Security & Reliability
- Threat modeling
- Encryption hardening
- Rate limiting
- Abuse controls
- Recovery
- Observability
- Audit integrity

## Phase 11 — Testing & Production
- Unit tests
- Integration tests
- Browser tests
- Security tests
- IDOR tests
- Load testing
- Deployment
- Monitoring
- Operational documentation

### Rule
No phase is considered complete until its acceptance criteria and tests pass. The next phase starts only after review of the previous phase.


## Release status — 2026-09-22

The secure beta foundation and production-completion code pass are implemented and locally tested. AI usage ledger/quota, official registry metadata, admin operational APIs, deployment manifests, backup tooling and CI service definitions are complete in the repository. The staging release remains gated on real PostgreSQL, Redis, AI, S3-compatible storage, email and Razorpay credentials, followed by safe browser smoke tests that stop before final submit.


## Unified platform expansion — implemented

The provider control plane now includes 24 direct/gateway AI provider records plus OmniRoute, capability and reasoning metadata, model discovery for compatible endpoints, free-first route metadata, quotas, health and fallback. Storage and authentication registries cover the five requested provider families with encrypted credential fields, private storage failover and canonical identity mapping. Admin APIs expose masked live configuration, capacity/health metadata, credential rotation, model discovery and real connection testing.

Remaining launch checks are external credential and infrastructure validation only; no provider secret is stored in this repository.
