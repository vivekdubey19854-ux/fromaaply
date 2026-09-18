"""Add server-side password accounts for production authentication."""

import sqlalchemy as sa
from alembic import op

revision = "0008_auth_users"
down_revision = "0007_merge_phase5a_commercial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_users",
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="active"),
        sa.Column("role", sa.String(length=30), nullable=False, server_default="user"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_auth_users_email", "auth_users", ["email"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_auth_users_email", table_name="auth_users")
    op.drop_table("auth_users")
