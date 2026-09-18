from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID


class DocumentStatus(StrEnum):
    UPLOADED = "uploaded"
    VERIFIED = "verified"
    REJECTED = "rejected"
    DELETED = "deleted"


@dataclass(slots=True)
class Profile:
    user_id: UUID
    full_name: str | None = None
    date_of_birth: date | None = None
    gender: str | None = None
    email: str | None = None
    phone: str | None = None


@dataclass(slots=True)
class Address:
    id: UUID
    user_id: UUID
    label: str
    line1: str
    line2: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str = "India"


@dataclass(slots=True)
class Education:
    id: UUID
    user_id: UUID
    qualification: str
    institution: str | None = None
    board_university: str | None = None
    passing_year: int | None = None
    percentage_or_cgpa: str | None = None


@dataclass(slots=True)
class Document:
    id: UUID
    user_id: UUID
    original_filename: str
    storage_key: str
    content_type: str
    size_bytes: int
    sha256: str
    status: DocumentStatus = DocumentStatus.UPLOADED
    created_at: datetime | None = None


@dataclass(slots=True)
class AuditEvent:
    id: UUID
    user_id: UUID
    action: str
    resource_type: str
    resource_id: UUID | None = None
    created_at: datetime | None = None
