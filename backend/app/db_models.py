from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AuthUserRecord(Base):
    __tablename__ = "auth_users"
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(30), default="active")
    role: Mapped[str] = mapped_column(String(30), default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)


class ProfileRecord(Base):
    __tablename__ = "profiles"
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    full_name: Mapped[str | None] = mapped_column(String(200))
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    gender: Mapped[str | None] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    addresses: Mapped[list["AddressRecord"]] = relationship(back_populates="profile", cascade="all, delete-orphan")
    education: Mapped[list["EducationRecord"]] = relationship(back_populates="profile", cascade="all, delete-orphan")
    documents: Mapped[list["DocumentRecord"]] = relationship(back_populates="profile", cascade="all, delete-orphan")


class AddressRecord(Base):
    __tablename__ = "addresses"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("profiles.user_id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(50))
    line1: Mapped[str] = mapped_column(String(200))
    line2: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(100))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    country: Mapped[str] = mapped_column(String(100), default="India")
    profile: Mapped[ProfileRecord] = relationship(back_populates="addresses")


class EducationRecord(Base):
    __tablename__ = "education"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("profiles.user_id", ondelete="CASCADE"), index=True)
    qualification: Mapped[str] = mapped_column(String(150))
    institution: Mapped[str | None] = mapped_column(String(200))
    board_university: Mapped[str | None] = mapped_column(String(200))
    passing_year: Mapped[int | None] = mapped_column(Integer)
    percentage_or_cgpa: Mapped[str | None] = mapped_column(String(50))
    profile: Mapped[ProfileRecord] = relationship(back_populates="education")


class DocumentRecord(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("profiles.user_id", ondelete="CASCADE"), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(500), unique=True)
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(30), default="uploaded")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    profile: Mapped[ProfileRecord] = relationship(back_populates="documents")


class AuditLogRecord(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(100))
    resource_type: Mapped[str] = mapped_column(String(50))
    resource_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    details: Mapped[str | None] = mapped_column(Text)
