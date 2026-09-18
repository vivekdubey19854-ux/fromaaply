"""create profile, address, education, document and audit tables"""

from alembic import op
import sqlalchemy as sa

revision = "0001_profile_vault"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "profiles",
        sa.Column("user_id", sa.String(64), primary_key=True),
        sa.Column("full_name", sa.String(200)),
        sa.Column("date_of_birth", sa.Date()),
        sa.Column("gender", sa.String(50)),
        sa.Column("email", sa.String(320)),
        sa.Column("phone", sa.String(30)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "addresses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("label", sa.String(50), nullable=False),
        sa.Column("line1", sa.String(200), nullable=False),
        sa.Column("line2", sa.String(200)),
        sa.Column("city", sa.String(100)),
        sa.Column("state", sa.String(100)),
        sa.Column("postal_code", sa.String(20)),
        sa.Column("country", sa.String(100), nullable=False, server_default="India"),
        sa.ForeignKeyConstraint(["user_id"], ["profiles.user_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_addresses_user_id", "addresses", ["user_id"])
    op.create_table(
        "education",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("qualification", sa.String(150), nullable=False),
        sa.Column("institution", sa.String(200)),
        sa.Column("board_university", sa.String(200)),
        sa.Column("passing_year", sa.Integer()),
        sa.Column("percentage_or_cgpa", sa.String(50)),
        sa.ForeignKeyConstraint(["user_id"], ["profiles.user_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_education_user_id", "education", ["user_id"])
    op.create_table(
        "documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False, unique=True),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="uploaded"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["profiles.user_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_documents_user_id", "documents", ["user_id"])
    op.create_index("ix_documents_sha256", "documents", ["sha256"])
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", sa.String(36)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("details", sa.Text()),
    )
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_user_id", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_index("ix_documents_sha256", table_name="documents")
    op.drop_index("ix_documents_user_id", table_name="documents")
    op.drop_table("documents")
    op.drop_index("ix_education_user_id", table_name="education")
    op.drop_table("education")
    op.drop_index("ix_addresses_user_id", table_name="addresses")
    op.drop_table("addresses")
    op.drop_table("profiles")
