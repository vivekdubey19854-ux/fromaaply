"""add provenance, extraction, knowledge and verification tables

Revision ID: 0002_phase5a_provenance
Revises: 0001_profile_vault
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_phase5a_provenance"
down_revision = "0001_profile_vault"
branch_labels = None
depends_on = None


def _add_security_columns(table: str, confidence_default: str) -> None:
    op.add_column(table, sa.Column("confidence", sa.Numeric(5, 4), nullable=False, server_default=sa.text(confidence_default)))
    op.add_column(table, sa.Column("verification_status", sa.String(40), nullable=False, server_default=sa.text(f"'{default_status(table)}'")))


def default_status(table: str) -> str:
    return {
        "profiles": "unverified",
        "addresses": "unverified",
        "education": "unverified",
        "documents": "uploaded",
        "audit_logs": "recorded",
    }[table]


def _id_column() -> sa.Column:
    # Existing Formwise migrations support SQLite for CI/dev. Supabase production
    # uses UUID-compatible string identifiers at this application boundary.
    return sa.Column("id", sa.String(36), primary_key=True)


def _json_type() -> sa.types.TypeEngine:
    return sa.JSON()


def upgrade() -> None:
    _add_security_columns("profiles", "0.0000")
    _add_security_columns("addresses", "0.0000")
    _add_security_columns("education", "0.0000")
    _add_security_columns("documents", "1.0000")
    _add_security_columns("audit_logs", "1.0000")

    # Confidence constraints for these legacy tables are enforced in the
    # production Supabase SQL migration. They are intentionally not added via
    # ALTER TABLE here because SQLite cannot add standalone CHECK constraints.

    op.create_table(
        "document_extractions",
        _id_column(),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("extractor_version", sa.String(100), nullable=False),
        sa.Column("raw_text", sa.Text()),
        sa.Column("extracted_fields", _json_type(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False, server_default="0"),
        sa.Column("verification_status", sa.String(40), nullable=False, server_default="'extracted'"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["profiles.user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="document_extractions_confidence_ck"),
        sa.CheckConstraint("verification_status IN ('processing','extracted','review_required','verified','revoked')", name="document_extractions_status_ck"),
    )
    op.create_index("ix_document_extractions_user_id", "document_extractions", ["user_id"])
    op.create_index("ix_document_extractions_document_id", "document_extractions", ["document_id"])

    op.create_table(
        "field_provenance",
        _id_column(),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("field_name", sa.String(150), nullable=False),
        sa.Column("field_value", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(80), nullable=False),
        sa.Column("source_id", sa.String(200)),
        sa.Column("source_locator", sa.String(500)),
        sa.Column("extraction_id", sa.String(36)),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False, server_default="0"),
        sa.Column("verification_status", sa.String(40), nullable=False, server_default="'review_required'"),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("verified_by", sa.String(128)),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["profiles.user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["extraction_id"], ["document_extractions.id"], ondelete="SET NULL"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="field_provenance_confidence_ck"),
        sa.CheckConstraint("verification_status IN ('unverified','review_required','verified','revoked')", name="field_provenance_status_ck"),
    )
    op.create_index("ix_field_provenance_user_field", "field_provenance", ["user_id", "field_name"])
    op.create_index("ix_field_provenance_user_status", "field_provenance", ["user_id", "verification_status"])

    op.create_table(
        "knowledge_chunks",
        _id_column(),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("source_type", sa.String(80), nullable=False),
        sa.Column("source_id", sa.String(200)),
        sa.Column("chunk_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False, server_default="0"),
        sa.Column("verification_status", sa.String(40), nullable=False, server_default="'unverified'"),
        sa.Column("metadata", _json_type(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["profiles.user_id"], ondelete="CASCADE"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="knowledge_chunks_confidence_ck"),
        sa.CheckConstraint("verification_status IN ('unverified','review_required','verified','revoked')", name="knowledge_chunks_status_ck"),
        sa.CheckConstraint("chunk_index >= 0", name="knowledge_chunks_chunk_index_ck"),
    )
    op.create_index("ix_knowledge_chunks_user_id", "knowledge_chunks", ["user_id"])
    op.create_index("ix_knowledge_chunks_user_source", "knowledge_chunks", ["user_id", "source_type", "source_id"])
    op.create_index("ux_knowledge_chunks_user_hash", "knowledge_chunks", ["user_id", "content_hash"], unique=True)

    op.create_table(
        "verification_records",
        _id_column(),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(80), nullable=False),
        sa.Column("target_id", sa.String(200), nullable=False),
        sa.Column("previous_status", sa.String(40)),
        sa.Column("new_status", sa.String(40), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False, server_default="0"),
        sa.Column("verifier_type", sa.String(40), nullable=False, server_default="'human'"),
        sa.Column("verifier_id", sa.String(128)),
        sa.Column("reason", sa.Text()),
        sa.Column("evidence", _json_type(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["profiles.user_id"], ondelete="CASCADE"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="verification_records_confidence_ck"),
        sa.CheckConstraint("new_status IN ('unverified','processing','extracted','review_required','verified','revoked')", name="verification_records_status_ck"),
    )
    op.create_index("ix_verification_records_user_target", "verification_records", ["user_id", "target_type", "target_id"])


def downgrade() -> None:
    op.drop_index("ix_verification_records_user_target", table_name="verification_records")
    op.drop_table("verification_records")
    op.drop_index("ux_knowledge_chunks_user_hash", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_user_source", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_user_id", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    op.drop_index("ix_field_provenance_user_status", table_name="field_provenance")
    op.drop_index("ix_field_provenance_user_field", table_name="field_provenance")
    op.drop_table("field_provenance")
    op.drop_index("ix_document_extractions_document_id", table_name="document_extractions")
    op.drop_index("ix_document_extractions_user_id", table_name="document_extractions")
    op.drop_table("document_extractions")
    for table in ("audit_logs", "documents", "education", "addresses", "profiles"):
        op.drop_column(table, "verification_status")
        op.drop_column(table, "confidence")
