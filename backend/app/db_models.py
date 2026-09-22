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


class RevokedTokenRecord(Base):
    __tablename__ = "revoked_tokens"
    jti: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class WebsiteRegistryRecord(Base):
    __tablename__ = "website_registry"
    website_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(50))
    base_url: Mapped[str] = mapped_column(String(500))
    allowed_domains_json: Mapped[str] = mapped_column(Text, default="[]")
    enabled: Mapped[bool] = mapped_column(default=False)
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    verified: Mapped[bool] = mapped_column(default=False)
    version: Mapped[str] = mapped_column(String(40), default="1.0.0")
    health_status: Mapped[str] = mapped_column(String(30), default="unknown")
    last_health_check: Mapped[datetime | None] = mapped_column(DateTime)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    allowed_paths_json: Mapped[str] = mapped_column(Text, default="[]")
    supported_fields_json: Mapped[str] = mapped_column(Text, default="[]")
    mapping_metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AuthActionTokenRecord(Base):
    __tablename__ = "auth_action_tokens"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    purpose: Mapped[str] = mapped_column(String(40), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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


class FormTaskRecord(Base):
    __tablename__ = "form_tasks"
    task_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    workflow_id: Mapped[str | None] = mapped_column(String(36), index=True)
    website_id: Mapped[str | None] = mapped_column(String(36), index=True)
    state: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    current_step: Mapped[str | None] = mapped_column(String(100))
    target_url: Mapped[str | None] = mapped_column(String(500))
    browser_session_id: Mapped[str | None] = mapped_column(String(100), index=True)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(1000))
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), unique=True, index=True)
    resume_reference: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime)


class TaskStepRecord(Base):
    __tablename__ = "task_steps"
    step_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    task_id: Mapped[str] = mapped_column(String(36), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    step_name: Mapped[str] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(30), default="pending")
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class BrowserSessionRecord(Base):
    __tablename__ = "browser_sessions"
    browser_session_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    state: Mapped[str] = mapped_column(String(30), default="created")
    target_url: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)


class BrowserSessionEventRecord(Base):
    __tablename__ = "browser_session_events"
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    browser_session_id: Mapped[str] = mapped_column(String(100), index=True)
    task_id: Mapped[str] = mapped_column(String(36), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(80))
    details: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class WorkflowEventRecord(Base):
    __tablename__ = "workflow_events"
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    task_id: Mapped[str] = mapped_column(String(36), index=True)
    workflow_id: Mapped[str | None] = mapped_column(String(36), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(80))
    from_state: Mapped[str | None] = mapped_column(String(40))
    to_state: Mapped[str | None] = mapped_column(String(40))
    details: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TaskLockRecord(Base):
    __tablename__ = "task_locks"
    task_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(120))
    locked_until: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AIUsageLedgerRecord(Base):
    __tablename__ = "ai_usage_ledger"
    usage_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    provider: Mapped[str] = mapped_column(String(80), index=True)
    model: Mapped[str] = mapped_column(String(160))
    request_id: Mapped[str] = mapped_column(String(80), index=True)
    task_name: Mapped[str] = mapped_column(String(100))
    user_id: Mapped[str | None] = mapped_column(String(64), index=True)
    task_id: Mapped[str | None] = mapped_column(String(36), index=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), index=True)
    fallback_from: Mapped[str | None] = mapped_column(String(80))
    estimated_cost: Mapped[float] = mapped_column(default=0)
    error_type: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
