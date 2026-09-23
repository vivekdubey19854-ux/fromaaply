# Formwise Agent — Architecture

## Architectural Principles

1. Privacy by default.
2. Human control over high-impact actions.
3. Provider-neutral AI interfaces.
4. Modular components with replaceable infrastructure.
5. Strong tenant/user isolation.
6. Every important action is auditable.
7. Deterministic safety policies take precedence over model output.
8. Fail closed when authorization, provenance, or confidence is insufficient.

## Logical Layers

```text
Web UI
  |
API / Application Services
  |
Policy & Permission Engine
  |
Agent Orchestrator
  |--------- Intelligence / Retrieval
  |--------- Browser Execution
  |--------- Task State / Recovery
  |
Data Access Layer
  |--------- PostgreSQL
  |--------- Private Object Storage
  |--------- Credential Vault
  |
Audit / Observability
```

## Major Components

### 1. Presentation Layer

Responsible for authentication UI, dashboard, profile, document vault, task creation, review, approvals, activity, and privacy controls.

### 2. API/Application Layer

Owns authentication-aware request handling, validation, service boundaries, and authorization checks.

### 3. Policy & Permission Engine

A deterministic control layer between user intent and execution. It decides whether an operation is allowed, requires approval, or must be denied.

### 4. Agent Orchestrator

Manages task lifecycle and coordinates retrieval, reasoning, browser tools, approvals, and recovery. The orchestrator must not bypass policy decisions.

### 5. Intelligence Layer

Provides OCR, extraction, embeddings/retrieval, confidence scoring, and LLM provider abstraction. Model output is untrusted until validated by application policies.

### 6. Browser Execution Layer

Uses isolated Playwright browser sessions for supported websites. Browser actions are represented as auditable events.

### 7. Data Layer

Provides database repositories, private object storage abstraction, and a separate credential vault abstraction. Application code should not depend directly on one storage vendor.

### 8. Audit/Observability

Records task state changes, data access, approvals, browser actions, policy decisions, failures, and recovery events without unnecessarily storing sensitive values.

## Core Domain Objects

- User
- Profile
- Address
- Education
- Document
- DocumentVersion
- PersonalDataSource
- FormTask
- TaskStep
- FieldMapping
- ApprovalRequest
- BrowserSession
- CredentialReference
- PolicyDecision
- AuditEvent
- AIUsageEvent

## Security Boundaries

### Documents
Private object storage; access through authorized backend operations only.

### Credentials
Kept logically and operationally separate from ordinary documents. Secrets should be encrypted and never exposed to the model as plain text unless absolutely required by a controlled tool operation.

### Browser Sessions
Per-user/per-task isolation, restricted persistence, explicit lifecycle, and secure cleanup.

### AI Models
Treat prompts, model responses, and tool arguments as untrusted. Never allow an LLM to directly authorize a sensitive operation.

## Golden Field-Filling Rule

A field can be automatically populated only when:

`Approved Source + Valid Mapping + Sufficient Confidence + Policy Permission`

If any condition is missing, the system pauses or asks the user.

## Failure Model

Expected failures include expired sessions, website layout changes, missing data, ambiguous fields, OCR errors, network failures, browser crashes, provider failures, and policy denial.

Tasks must support safe pause, retry where appropriate, recovery, cancellation, and clear user-facing errors.


## Production completion addendum

PostgreSQL is the durable authority for task recovery, AI usage accounting, registry metadata and audit state. Redis carries queue messages but never replaces database state. The worker owns Playwright contexts and uses lease ownership for mutations. The production topology is API, worker/browser worker, PostgreSQL, Redis and a static frontend. Provider credentials are encrypted and injected through deployment secrets.


## Unified provider federation

The `ai_provider_registry` and `ai_model_registry` tables define provider capabilities, reasoning support, free-tier classification, priority and fallback order without requiring source changes for new OpenAI-compatible providers. The runtime catalog covers 24 providers and OmniRoute. Smart routing considers task type, capability, free-tier classification, quota, RPM, cooldown, health and priority before bounded fallback. OmniRoute is optional and never a single point of failure.

`storage_provider_registry` provides an encrypted, private provider registry for Oracle, Cloudflare R2, Backblaze B2, Firebase and Supabase. The storage adapter keeps primary-plus-failover semantics and does not replicate objects without an explicit policy. `auth_provider_registry` and `auth_identity_mappings` separate external authentication subjects from the canonical Formwise user identity.

The Admin control plane is the server-authoritative configuration boundary for these registries. It exposes masked metadata only, writes credentials through encrypted storage, and requires system-admin authorization for every mutation.
