# Phase 5-B — Real Knowledge Service + Agent Data Gateway

The `VerifiedDataService` is the narrow boundary between the browser agent and verified personal data.

## Allowed flow

`authenticated user -> repository -> verified data service -> one explicitly requested field -> browser workflow`

The service does not expose a profile object, document contents, arbitrary SQL, storage keys, or a wildcard field query.

## Request contract

Use:

```python
service.get_requested_field(
    user_id=user_id,
    requested_field="date_of_birth",
)
```

For a known finite set, `get_requested_fields()` accepts 1–20 explicit field names. `*`, `profile`, `all`, an empty list, and duplicate fields are rejected.

## Confidence and provenance

Only repository results with `verification_status='verified'`, `revoked_at IS NULL`, and the configured minimum confidence are eligible.

Ranking is:

1. highest confidence
2. source authority as a tie-breaker (`aadhaar`, `pan`, government ID, etc.)

Source priority is **never** allowed to override a conflict. If verified sources contain different values, the repository returns `conflict` and the gateway returns no value. This preserves the project's no-guessing rule.

## Browser boundary

`browser_use_agent.py` must remain unaware of Supabase credentials and database sessions. Phase 5-B provides the data contract; the next integration step can adapt it into the orchestrator's field-resolution path without granting Browser Use broad data access.
