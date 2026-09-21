"""Add admin-managed website registry."""

import sqlalchemy as sa
from alembic import op

revision = "0010_website_registry"
down_revision = "0009_revoked_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "website_registry",
        sa.Column("website_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column("allowed_domains_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("config_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("website_id"),
    )


def downgrade() -> None:
    op.drop_table("website_registry")
