from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import AddressRecord, DocumentRecord, EducationRecord, ProfileRecord
from app.storage import PrivateStorage


ALIASES = {
    "name": "full_name",
    "applicant_name": "full_name",
    "first_name": "first_name",
    "dob": "date_of_birth",
    "date_of_birth": "date_of_birth",
    "email_address": "email",
    "mobile": "phone",
    "mobile_number": "phone",
    "aadhaar": "aadhaar_number",
    "aadhar": "aadhaar_number",
    "pan": "pan_number",
    "pin": "postal_code",
    "pincode": "postal_code",
}


def _normalise(field: str) -> str:
    key = field.strip().lower().replace("-", "_").replace(" ", "_")
    return ALIASES.get(key, key)


def get_user_data(db: Session, storage: PrivateStorage, user_id: str, field: str) -> dict[str, Any] | None:
    """Fetch exactly one requested user-data field with source provenance.

    This is intentionally on-demand: callers request a field only after a live
    form control has been identified. Missing data returns None; nothing is guessed.
    """
    requested = _normalise(field)
    profile = db.get(ProfileRecord, user_id)
    if profile is None:
        return None

    profile_values = {
        "full_name": profile.full_name,
        "date_of_birth": profile.date_of_birth.isoformat() if isinstance(profile.date_of_birth, date) else profile.date_of_birth,
        "gender": profile.gender,
        "email": profile.email,
        "phone": profile.phone,
    }
    if requested in profile_values:
        value = profile_values[requested]
        return {"field": requested, "value": value, "source_type": "profile"} if value not in (None, "") else None

    if requested == "first_name" and profile.full_name:
        return {"field": requested, "value": profile.full_name.strip().split()[0], "source_type": "profile.full_name"}
    if requested == "last_name" and profile.full_name:
        parts = profile.full_name.strip().split()
        return {"field": requested, "value": parts[-1] if len(parts) > 1 else "", "source_type": "profile.full_name"} if len(parts) > 1 else None

    addresses = db.scalars(select(AddressRecord).where(AddressRecord.user_id == user_id)).all()
    if addresses:
        address = addresses[0]
        address_values = {
            "address": ", ".join(x for x in [address.line1, address.line2, address.city, address.state, address.postal_code, address.country] if x),
            "city": address.city,
            "state": address.state,
            "postal_code": address.postal_code,
            "country": address.country,
        }
        if requested in address_values and address_values[requested]:
            return {"field": requested, "value": address_values[requested], "source_type": "address", "source_id": address.id}

    education = db.scalars(select(EducationRecord).where(EducationRecord.user_id == user_id)).all()
    if education:
        record = education[0]
        education_values = {
            "qualification": record.qualification,
            "institution": record.institution,
            "board_university": record.board_university,
            "passing_year": record.passing_year,
            "percentage_or_cgpa": record.percentage_or_cgpa,
        }
        if requested in education_values and education_values[requested] not in (None, ""):
            return {"field": requested, "value": education_values[requested], "source_type": "education", "source_id": record.id}

    document_field_names = {"aadhaar_number", "pan_number", "photo", "signature", "roll_number", "registration_number", "father_name", "mother_name"}
    if requested in document_field_names:
        documents = db.scalars(select(DocumentRecord).where(DocumentRecord.user_id == user_id, DocumentRecord.status != "deleted")).all()
        matches: list[dict[str, Any]] = []
        for doc in documents:
            try:
                extraction = storage.read_json(user_id, f"{doc.storage_key}.extraction.json")
            except FileNotFoundError:
                continue
            for extracted in extraction.get("fields", []):
                if extracted.get("name") == requested and extracted.get("value") not in (None, ""):
                    matches.append({
                        "field": requested,
                        "value": extracted["value"],
                        "source_type": "document_extraction",
                        "source_id": doc.id,
                        "filename": doc.original_filename,
                        "confidence": extracted.get("confidence"),
                    })
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(f"multiple verified values found for {requested}; manual resolution required")

    return None
