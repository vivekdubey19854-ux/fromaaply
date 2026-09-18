from __future__ import annotations

import io
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class ExtractedField:
    name: str
    value: str
    confidence: float
    source: str


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" :\t\r\n")


def _fields_from_text(text: str) -> list[ExtractedField]:
    fields: list[ExtractedField] = []
    patterns = [
        ("aadhaar_number", r"\b(\d{4}\s?\d{4}\s?\d{4})\b", 0.97),
        ("pan_number", r"\b([A-Z]{5}[0-9]{4}[A-Z])\b", 0.98),
        ("phone", r"(?<!\d)(?:\+91[ -]?)?([6-9]\d{9})(?!\d)", 0.94),
        ("email", r"\b([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})\b", 0.98),
        ("date_of_birth", r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{4})\b", 0.88),
    ]
    for name, pattern, confidence in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = _clean(match.group(1))
            if name == "aadhaar_number":
                value = re.sub(r"\s+", " ", value)
            fields.append(ExtractedField(name, value, confidence, "text"))

    name_patterns = [
        r"(?im)^\s*(?:name|full name)\s*[:\-]\s*([A-Za-z][A-Za-z .'-]{2,100})\s*$",
        r"(?im)^\s*नाम\s*[:\-]\s*([^\n]{2,100})\s*$",
    ]
    for pattern in name_patterns:
        match = re.search(pattern, text)
        if match:
            fields.append(ExtractedField("full_name", _clean(match.group(1)), 0.82, "text"))
            break
    return fields


def _ocr_image(data: bytes) -> tuple[str, str]:
    try:
        import pytesseract
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("OCR dependencies are not installed") from exc
    if shutil.which("tesseract") is None:
        raise RuntimeError("Tesseract OCR engine is not installed on the server")
    image = Image.open(io.BytesIO(data))
    return pytesseract.image_to_string(image), "tesseract"


def extract_document(data: bytes, content_type: str, filename: str) -> dict:
    """Extract text and high-confidence structured fields without inventing values.

    PDF text extraction uses PyMuPDF. Scanned PDFs fall back to page rendering + Tesseract.
    Image OCR uses Tesseract. Missing OCR binaries produce an explicit failure instead of guessing.
    """
    text = ""
    engine = "none"
    pages = 1
    if content_type == "application/pdf":
        try:
            import fitz
        except ImportError as exc:
            raise RuntimeError("PDF extraction dependency is not installed") from exc
        document = fitz.open(stream=data, filetype="pdf")
        pages = len(document)
        text = "\n".join(page.get_text("text") for page in document).strip()
        engine = "pymupdf"
        if len(text) < 20:
            try:
                import pytesseract
                from PIL import Image
            except ImportError as exc:
                raise RuntimeError("OCR dependencies are not installed") from exc
            if shutil.which("tesseract") is None:
                raise RuntimeError("Tesseract OCR engine is not installed on the server")
            chunks: list[str] = []
            for page in document:
                pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
                image = Image.open(io.BytesIO(pix.tobytes("png")))
                chunks.append(pytesseract.image_to_string(image))
            text = "\n".join(chunks).strip()
            engine = "pymupdf+tesseract"
    elif content_type.startswith("image/"):
        text, engine = _ocr_image(data)
    else:
        raise ValueError("unsupported document type for extraction")

    fields = [field.__dict__ for field in _fields_from_text(text)]
    return {
        "schema_version": "1.0",
        "status": "completed",
        "filename": filename,
        "content_type": content_type,
        "pages": pages,
        "engine": engine,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "text": text,
        "fields": fields,
        "warning": "Extracted values are suggestions and must be verified before use in forms.",
    }
