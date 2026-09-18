from __future__ import annotations

import re
from typing import Any

from app.knowledge_base import rank_chunks

SCHEMA_VERSION = "1"

_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "full_name": ("name", "full name", "candidate name", "applicant name", "नाम"),
    "date_of_birth": ("dob", "date of birth", "birth date", "जन्म तिथि"),
    "gender": ("gender", "sex", "लिंग"),
    "email": ("email", "email address", "e-mail"),
    "phone": ("phone", "mobile", "mobile number", "telephone", "contact number"),
    "aadhaar_number": ("aadhaar", "aadhaar number", "uid"),
    "pan_number": ("pan", "pan number"),
    "address": ("address", "permanent address", "current address", "mailing address"),
    "postal_code": ("pin", "pincode", "postal code", "zip code"),
}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def infer_field(instruction: str) -> str | None:
    text = _normalize(instruction)
    for field, aliases in _FIELD_ALIASES.items():
        if any(alias in text for alias in aliases):
            return field
    return None


def _field_match(field: str, chunk: dict[str, Any]) -> bool:
    text = _normalize(str(chunk.get("text", "")))
    aliases = _FIELD_ALIASES.get(field, (field,))
    return any(alias in text for alias in aliases)


def plan_from_knowledge(instruction: str, chunks: list[dict[str, Any]], top_k: int = 8) -> dict[str, Any]:
    field = infer_field(instruction)
    if not field:
        return {"schema_version": SCHEMA_VERSION, "status": "needs_clarification", "action": "none", "requires_approval": False, "candidates": [], "warnings": ["Could not identify a supported personal-data field from the instruction."]}

    ranked = rank_chunks(instruction, chunks, max(top_k, 20))
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in ranked:
        if not _field_match(field, item):
            continue
        value = _extract_value(field, str(item.get("text", "")))
        if not value or value in seen:
            continue
        seen.add(value)
        candidates.append({
            "field": field,
            "value": value,
            "source_type": str(item.get("source_type", "unknown")),
            "source_id": str(item.get("source_id", "unknown")),
            "confidence": min(1.0, float(item.get("score", 0.0))),
            "reason": "Matched a stored knowledge source; no value was invented.",
        })

    warnings: list[str] = []
    requires_approval = False
    if len(candidates) == 0:
        warnings.append("No verified stored value matched this field.")
    elif len(candidates) > 1:
        warnings.append("Multiple stored values matched; human selection is required before use.")
        requires_approval = True
    elif field in {"aadhaar_number", "pan_number", "date_of_birth", "address"}:
        requires_approval = True
        warnings.append("This field contains sensitive or materially important personal data and requires explicit approval before use.")

    return {"schema_version": SCHEMA_VERSION, "status": "ready" if candidates else "needs_clarification", "action": "propose_field_value" if candidates else "none", "requires_approval": requires_approval, "candidates": candidates, "warnings": warnings}


def _extract_value(field: str, text: str) -> str | None:
    patterns = {
        "email": r"(?i)\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        "phone": r"(?<!\d)(?:\+91[ -]?)?[6-9]\d{9}(?!\d)",
        "pan_number": r"\b[A-Z]{5}[0-9]{4}[A-Z]\b",
        "aadhaar_number": r"\b\d{4}\s?\d{4}\s?\d{4}\b",
        "date_of_birth": r"\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b",
    }
    pattern = patterns.get(field)
    if pattern:
        match = re.search(pattern, text)
        return match.group(0) if match else None
    aliases = _FIELD_ALIASES.get(field, (field,))
    for alias in aliases:
        match = re.search(rf"(?i)(?:{re.escape(alias)})\s*[:=-]\s*([^;|\n]+)", text)
        if match:
            return match.group(1).strip()
    return None
