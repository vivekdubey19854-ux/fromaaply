from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db_models import AddressRecord, EducationRecord, ProfileRecord
from app.verified_data_repository import VerifiedDataRepository, VerifiedField

DEFAULT_MIN_CONFIDENCE = 0.80
MAX_REQUESTED_FIELDS = 20

SOURCE_PRIORITY = {
    "aadhaar": 100,
    "pan": 95,
    "passport": 90,
    "government_id": 90,
    "marksheet": 70,
    "certificate": 65,
    "profile": 50,
    "manual": 40,
}

@dataclass(frozen=True)
class DataGatewayResult:
    status: str
    field: str
    value: str | None = None
    confidence: float | None = None
    source_type: str | None = None
    source_id: str | None = None
    provenance_id: str | None = None
    reason: str | None = None

@dataclass(frozen=True)
class VerifiedDataResult:
    status: str
    field_key: str
    value: Any | None = None
    message: str | None = None
    source: str | None = None
    @property
    def usable(self) -> bool:
        return self.status == "VERIFIED"

class VerifiedDataStatus:
    VERIFIED = "VERIFIED"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    INVALID_FIELD = "INVALID_FIELD"
    ERROR = "ERROR"

class VerifiedDataService:
    """Zero-trust gateway with legacy get_field compatibility.

    New agent/browser paths must use get_requested_field() through a
    VerifiedDataRepository. get_field() remains only as a compatibility
    adapter for the existing live-browser gate and does not expose a profile
    or arbitrary query interface.
    """

    def __init__(self, repository_or_db: VerifiedDataRepository | Session):
        self.repository = repository_or_db if hasattr(repository_or_db, "get_verified_field") else None
        self._legacy_db = None if self.repository is not None else repository_or_db

    def get_requested_field(
        self,
        *,
        user_id: str,
        requested_field: str,
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    ) -> DataGatewayResult:
        if self.repository is None:
            raise RuntimeError("verified provenance repository is required")
        field = self._normalize_field(requested_field)
        self._validate_user(user_id)
        self._validate_confidence(min_confidence)
        result = self.repository.get_verified_field(user_id, field, min_confidence=min_confidence)

        if result.status == "conflict":
            return DataGatewayResult(status="conflict", field=field, reason=result.reason)
        if result.status != "verified" or not result.candidates:
            return DataGatewayResult(status=result.status, field=field, reason=result.reason)

        winner = self._choose_verified_candidate(result.candidates)
        return DataGatewayResult(
            status="verified",
            field=field,
            value=winner.value,
            confidence=winner.confidence,
            source_type=winner.source_type,
            source_id=winner.source_id,
            provenance_id=winner.provenance_id,
        )

    def get_requested_fields(
        self,
        *,
        user_id: str,
        requested_fields: Iterable[str],
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    ) -> list[DataGatewayResult]:
        self._validate_user(user_id)
        self._validate_confidence(min_confidence)
        fields = [self._normalize_field(field) for field in requested_fields]
        if not fields or len(fields) > MAX_REQUESTED_FIELDS:
            raise ValueError(f"requested_fields must contain 1-{MAX_REQUESTED_FIELDS} fields")
        if len(set(fields)) != len(fields):
            raise ValueError("duplicate requested fields are not allowed")
        if "*" in fields or "profile" in fields or "all" in fields:
            raise ValueError("wildcard/profile-wide requests are not allowed")
        return [
            self.get_requested_field(user_id=user_id, requested_field=field, min_confidence=min_confidence)
            for field in fields
        ]

    def get_field(self, user_id: str, field_key: str) -> VerifiedDataResult:
        """Legacy compatibility adapter used only by the live-browser human gate."""
        allowed = {
            "full_name", "date_of_birth", "gender", "email", "phone",
            "permanent_address.line1", "permanent_address.line2",
            "permanent_address.city", "permanent_address.state",
            "permanent_address.postal_code", "permanent_address.country",
            "education.latest.qualification", "education.latest.institution",
            "education.latest.board_university", "education.latest.passing_year",
            "education.latest.percentage_or_cgpa",
        }
        field = self._normalize_legacy_field(field_key)
        if field not in allowed:
            return VerifiedDataResult(VerifiedDataStatus.INVALID_FIELD, field, message="field is not approved for on-demand access")

        if self.repository is not None:
            result = self.get_requested_field(user_id=user_id, requested_field=field)
            if result.status == "verified":
                return VerifiedDataResult(VerifiedDataStatus.VERIFIED, field, result.value, source=result.source_type)
            if result.status == "conflict":
                return VerifiedDataResult(VerifiedDataStatus.CONFLICT, field, message=result.reason)
            return VerifiedDataResult(VerifiedDataStatus.NOT_FOUND, field, message=result.reason)

        db = self._legacy_db
        if db is None:
            return VerifiedDataResult(VerifiedDataStatus.ERROR, field, message="database context is unavailable")
        try:
            if field in {"full_name", "date_of_birth", "gender", "email", "phone"}:
                profile = db.get(ProfileRecord, user_id)
                if profile is None:
                    return VerifiedDataResult(VerifiedDataStatus.NOT_FOUND, field, message="profile not found")
                value = getattr(profile, field, None)
                if value is None or (isinstance(value, str) and not value.strip()):
                    return VerifiedDataResult(VerifiedDataStatus.NOT_FOUND, field, message="field value not found", source="profiles")
                return VerifiedDataResult(VerifiedDataStatus.VERIFIED, field, self._stringify(value), source="profiles")

            if field.startswith("permanent_address."):
                attribute = field.split(".", 1)[1]
                rows = db.scalars(
                    select(AddressRecord).where(AddressRecord.user_id == user_id, AddressRecord.label.ilike("permanent"))
                ).all()
                if not rows:
                    return VerifiedDataResult(VerifiedDataStatus.NOT_FOUND, field, message="permanent address not found")
                if len(rows) > 1:
                    return VerifiedDataResult(VerifiedDataStatus.CONFLICT, field, message="multiple permanent addresses found")
                value = getattr(rows[0], attribute, None)
                if value is None or (isinstance(value, str) and not value.strip()):
                    return VerifiedDataResult(VerifiedDataStatus.NOT_FOUND, field, message="address field value not found", source="addresses")
                return VerifiedDataResult(VerifiedDataStatus.VERIFIED, field, self._stringify(value), source="addresses")

            attribute = field.split(".", 2)[2]
            rows = db.scalars(
                select(EducationRecord).where(EducationRecord.user_id == user_id)
                .order_by(EducationRecord.passing_year.desc().nullslast(), EducationRecord.id.desc())
            ).all()
            if not rows:
                return VerifiedDataResult(VerifiedDataStatus.NOT_FOUND, field, message="education record not found")
            newest_year = rows[0].passing_year
            newest = [row for row in rows if row.passing_year == newest_year]
            if newest_year is not None and len(newest) > 1:
                return VerifiedDataResult(VerifiedDataStatus.CONFLICT, field, message="multiple latest education records found")
            value = getattr(newest[0], attribute, None)
            if value is None or (isinstance(value, str) and not value.strip()):
                return VerifiedDataResult(VerifiedDataStatus.NOT_FOUND, field, message="education field value not found", source="education")
            return VerifiedDataResult(VerifiedDataStatus.VERIFIED, field, self._stringify(value), source="education")
        except Exception as exc:
            return VerifiedDataResult(VerifiedDataStatus.ERROR, field, message=f"verified data lookup failed: {exc}")

    @staticmethod
    def _choose_verified_candidate(candidates: tuple[VerifiedField, ...]) -> VerifiedField:
        return max(candidates, key=lambda item: (item.confidence, SOURCE_PRIORITY.get(item.source_type.lower(), 0)))

    @staticmethod
    def _normalize_field(value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("requested_field must be a string")
        field = value.strip().lower()
        if not field or len(field) > 150:
            raise ValueError("invalid requested field")
        if any(character in field for character in (";", "--", "/*", "*/")):
            raise ValueError("invalid requested field")
        return field

    @staticmethod
    def _normalize_legacy_field(value: str) -> str:
        if not isinstance(value, str):
            return ""
        return value.strip().lower()

    @staticmethod
    def _stringify(value: Any) -> Any:
        return value.isoformat() if isinstance(value, date) else value

    @staticmethod
    def _validate_user(user_id: str) -> None:
        if not isinstance(user_id, str) or not user_id or len(user_id) > 128:
            raise ValueError("invalid user_id")

    @staticmethod
    def _validate_confidence(value: float) -> None:
        if not 0 <= value <= 1:
            raise ValueError("min_confidence must be between 0 and 1")
