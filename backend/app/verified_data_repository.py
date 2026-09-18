from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class VerifiedField:
    field: str
    value: str
    confidence: float
    verification_status: str
    source_type: str
    source_id: str | None
    source_locator: str | None
    provenance_id: str
    verified_at: Any | None


@dataclass(frozen=True)
class VerifiedFieldLookup:
    status: str
    candidates: tuple[VerifiedField, ...] = ()
    value: str | None = None
    reason: str | None = None


class VerifiedDataRepository:
    """Read-only, provenance-backed gateway for verified user fields.

    The repository deliberately returns no value for unverified, revoked,
    low-confidence, cross-user, or conflicting data. Callers must resolve a
    conflict through the human approval flow instead of guessing.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_verified_field(
        self,
        user_id: str,
        field: str,
        *,
        min_confidence: float = 0.80,
    ) -> VerifiedFieldLookup:
        if not isinstance(user_id, str) or not user_id.strip() or len(user_id) > 128:
            raise ValueError("invalid user_id")
        if not isinstance(field, str) or not field.strip() or len(field) > 150:
            raise ValueError("invalid field")
        if not 0 <= float(min_confidence) <= 1:
            raise ValueError("min_confidence must be between 0 and 1")

        rows = self.db.execute(
            text(
                "SELECT id, field_name, field_value, source_type, source_id, "
                "source_locator, confidence, verification_status, verified_at "
                "FROM field_provenance "
                "WHERE user_id = :user_id AND field_name = :field "
                "AND verification_status = 'verified' "
                "AND revoked_at IS NULL AND confidence >= :min_confidence "
                "ORDER BY confidence DESC, created_at DESC, id ASC"
            ),
            {"user_id": user_id.strip(), "field": field.strip().lower(), "min_confidence": float(min_confidence)},
        ).mappings().all()

        candidates = tuple(
            VerifiedField(
                field=str(row["field_name"]),
                value=str(row["field_value"]),
                confidence=float(row["confidence"]),
                verification_status=str(row["verification_status"]),
                source_type=str(row["source_type"]),
                source_id=str(row["source_id"]) if row["source_id"] is not None else None,
                source_locator=str(row["source_locator"]) if row["source_locator"] is not None else None,
                provenance_id=str(row["id"]),
                verified_at=row["verified_at"],
            )
            for row in rows
        )
        if not candidates:
            return VerifiedFieldLookup(status="not_found", reason="no verified value available")

        distinct_values = {candidate.value for candidate in candidates}
        if len(distinct_values) > 1:
            return VerifiedFieldLookup(
                status="conflict",
                candidates=candidates,
                reason="multiple verified sources disagree; human confirmation required",
            )

        return VerifiedFieldLookup(status="verified", candidates=candidates, value=candidates[0].value)


__all__ = ["VerifiedDataRepository", "VerifiedField", "VerifiedFieldLookup"]
