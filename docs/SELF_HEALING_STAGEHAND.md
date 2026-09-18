# Stagehand-Inspired Self-Healing

Formwise uses the architectural ideas behind Stagehand's `act`, `observe`, `extract`, and self-healing primitives without replacing its existing Playwright executor or safety policy.

## Formwise mapping

- **Observe:** `browser_agent.inspect_session()` exposes live controls, accessibility labels, nearby text, form metadata, and current values.
- **Resolve:** `form_mapping.resolve_field_mapping()` combines deterministic metadata with semantic accessibility/label context. A high-confidence winner must beat the runner-up by at least 0.10; ambiguity fails closed.
- **Act:** `form_execution.execute_form()` performs only approved, fill-only mutations through the existing Playwright executor.
- **Extract:** user values are retrieved on-demand by `get_user_data()` with provenance; the full profile is never dumped into an agent prompt.
- **Self-heal:** if an old field index/name/id no longer matches, non-sensitive fields may be remapped from current semantic cues. Sensitive fields require a fresh plan and approval because approvals are bound to the exact target/payload.

## Safety boundary

Self-healing cannot override `operational_policy.py`. CAPTCHA, OTP, payment/banking, legal declarations, anti-bot controls, and final submission remain human-controlled or blocked. Formwise never clicks the final Submit/Confirm action.

## Test strategy

`backend/tests/test_self_healing_mapping.py` covers:

1. mutated DOM id/name with stable accessibility/label cues;
2. recovery from accessibility context after selector drift;
3. ambiguous matches failing closed.

CI remains headless and installs Chromium before running the full backend test suite.
