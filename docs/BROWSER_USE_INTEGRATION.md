# Browser Use Integration & Formwise Operational Contract

Formwise integrates the open-source Browser Use Python library as an optional browser-agent adapter. Formwise safety controls remain authoritative.

## Allowed

- Navigate within the approved HTTP(S) target and same-site pages.
- Inspect form controls and page structure.
- Map website fields to verified Formwise profile/knowledge data.
- Fill ordinary fields without guessing.
- Use clearly intermediate `Next`, `Continue`, or `Save Draft` controls.

## Mandatory human pauses

The agent must immediately pause when it encounters:

- CAPTCHA, reCAPTCHA, hCaptcha, sliders, audio challenges, or other anti-bot checks.
- OTP or secondary verification codes.
- Legal declarations, self-attestation, or applicant attestations.
- Payment, card, banking, or fee-payment portals.
- Final Submit, Confirm Application, Pay & Submit, or equivalent consequential submission.
- Unexpected layout/system errors that make safe continuation uncertain.

The UI should report a clear `PAUSED: ...` reason and wait for a human-controlled workflow transition.

## CI / headless execution

CI and normal cloud tests use Playwright headless mode by default. `FORMWISE_BROWSER_HEADLESS=true` can be explicitly supplied by deployment/CI environments. If a Linux deployment later needs a headed browser, configure a virtual display such as Xvfb rather than assuming a desktop display exists.

Browser Use is disabled by default and is opt-in with `FORMWISE_BROWSER_USE_ENABLED=true`. Vision/browser-agent workloads can consume substantially more memory than deterministic tests, so production deployments should size RAM and timeouts for the selected model/browser workload. CI remains deterministic and should not invoke live LLM browser runs by default.

## License

The upstream Browser Use library is MIT licensed. When distributing substantial copied upstream code, retain the upstream copyright and license notice. Formwise currently depends on the package rather than copying its source tree.
