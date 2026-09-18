# Self-Healing Demonstration

The local demo intentionally mutates the machine-oriented `name` and `id` attributes of the Full Name, Date of Birth, Email, and Mobile controls while preserving their visible labels and accessibility context.

`run_demo.py` records the original control metadata, applies the mutation through a demo-only endpoint, then runs the normal Formwise E2E planner. The expected result is that deterministic metadata no longer identifies the original controls, while the Stagehand-inspired semantic resolver recovers the controls from label and nearby accessibility context.

Safety remains unchanged: CAPTCHA and OTP are human-provided, and Formwise never clicks the final Submit button.
