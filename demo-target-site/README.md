# Formwise local demo target

This folder is a deliberately local-only target used to exercise the real browser workflow without touching a government site.

## Run

```bash
cd demo-target-site
npm install
npm start
```

The form runs on `http://localhost:5000` and contains profile fields, photo/signature uploads, CAPTCHA, OTP and a final Submit button.

For Formwise development, set:

```env
FORMWISE_ENVIRONMENT=development
FORMWISE_BROWSER_ALLOW_LOCAL_DEMO_TARGET=true
FORMWISE_BROWSER_DEMO_TARGET_PORT=5000
FORMWISE_BROWSER_BLOCK_PRIVATE_NETWORKS=true
```

The browser safety layer permits only this exact local demo target in this mode. Production cannot enable the local-demo exception.

## Safety

- CAPTCHA is supplied by the human; Formwise never solves or bypasses it.
- OTP is supplied by the human.
- Final submission requires an explicit approval action.
- The demo contains no real application and should not be exposed publicly.
