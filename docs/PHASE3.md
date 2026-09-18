# Phase 3 — OCR + Document Intelligence

Phase 3 turns private uploaded documents into machine-readable evidence for later Formwise agent phases.

## Pipeline

1. User uploads a supported document.
2. The document remains private and ownership-scoped.
3. Text PDFs are parsed with PyMuPDF.
4. Scanned PDFs/images use Tesseract OCR when the server has the OCR engine installed.
5. Deterministic extraction identifies common fields such as PAN, Aadhaar, phone, email, date of birth, and explicitly labelled names.
6. Every extracted field carries confidence and source metadata.
7. The complete extraction artifact is stored privately beside the source document.
8. Later agent phases can retrieve the artifact, but consequential form actions must require verification.

## Safety

The extractor never fills missing values by inference. It returns an explicit empty result or dependency error. OCR output is treated as untrusted document-derived data and must be reviewed before it becomes authoritative profile data.

CAPTCHA, anti-bot controls, OTP, payment, legal declarations, and final submission are outside this phase.
