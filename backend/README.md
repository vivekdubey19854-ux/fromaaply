# Formwise Backend

Phase 3 adds document intelligence on top of the secure profile/document-vault foundation.

## Phase 3 included

- FastAPI profile/address/education/document APIs
- Private document upload, download, listing, and soft-delete
- Ownership checks and IDOR protection
- SHA-256 integrity metadata
- PDF text extraction with PyMuPDF
- Scanned-PDF OCR fallback with Tesseract
- Image OCR for JPEG/PNG/WEBP with Tesseract
- Deterministic structured-field extraction for common identity/contact fields
- Per-field confidence and source metadata
- Private JSON persistence for extraction artifacts
- Re-extraction endpoint and extraction-result retrieval
- Explicit failure when OCR dependencies/engine are unavailable; no invented values
- Unit and integration/security tests

## Run locally

```bash
cd backend
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env  # Windows
# cp .env.example .env  # Linux/macOS
alembic upgrade head
uvicorn app.main:app --reload
```

For image/scanned-PDF OCR, install the Tesseract system executable and ensure `tesseract` is on PATH. PDF text extraction does not require Tesseract when the PDF contains a real text layer.

### Extraction API

1. Upload: `POST /v1/documents`
2. Extract: `POST /v1/documents/{document_id}/extract`
3. Read saved result: `GET /v1/documents/{document_id}/extraction`

The extraction result contains raw text plus structured fields with confidence and source. It is an input to later agent/review phases, not an authoritative identity record. The product must require verification before consequential form submission.

Protected endpoints currently use the temporary `X-User-ID` identity adapter. This is intentionally not production authentication and must be replaced by verified session/JWT authentication before production use.

## Tests

```bash
cd backend
pytest -q
```

## Safety boundary

OCR and extraction never bypass CAPTCHA, anti-bot controls, OTP, payments, legal declarations, or final submission. Missing or uncertain data is surfaced rather than guessed.
