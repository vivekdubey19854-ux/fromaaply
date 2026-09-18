from __future__ import annotations

from datetime import date, datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class ProfileUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=200)
    date_of_birth: date | None = None
    gender: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=30)


class ProfileResponse(ProfileUpdate):
    user_id: str
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class AddressCreate(BaseModel):
    label: str = Field(min_length=1, max_length=50)
    line1: str = Field(min_length=1, max_length=200)
    line2: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)
    country: str = Field(default="India", max_length=100)


class AddressResponse(AddressCreate):
    id: str
    model_config = ConfigDict(from_attributes=True)


class EducationCreate(BaseModel):
    qualification: str = Field(min_length=1, max_length=150)
    institution: str | None = Field(default=None, max_length=200)
    board_university: str | None = Field(default=None, max_length=200)
    passing_year: int | None = Field(default=None, ge=1900, le=2200)
    percentage_or_cgpa: str | None = Field(default=None, max_length=50)


class EducationResponse(EducationCreate):
    id: str
    model_config = ConfigDict(from_attributes=True)


class DocumentMetadata(BaseModel):
    id: str
    original_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    status: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ExtractionField(BaseModel):
    name: str
    value: str
    confidence: float = Field(ge=0, le=1)
    source: str


class ExtractionResponse(BaseModel):
    schema_version: str
    status: str
    filename: str
    content_type: str
    pages: int = Field(ge=1)
    engine: str
    extracted_at: str
    text: str
    fields: list[ExtractionField]
    warning: str
