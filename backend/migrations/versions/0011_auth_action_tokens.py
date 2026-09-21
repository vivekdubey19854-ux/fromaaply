"""Store one-time verification and password-reset tokens as hashes."""

import sqlalchemy as sa
from alembic import op

revision = "0011_auth_action_tokens"
down_revision = "0010_website_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_action_tokens",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(length=40), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_index("ix_auth_action_tokens_user_id", "auth_action_tokens", ["user_id"], unique=False)
    op.create_index("ix_auth_action_tokens_purpose", "auth_action_tokens", ["purpose"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_auth_action_tokens_purpose", table_name="auth_action_tokens")
    op.drop_index("ix_auth_action_tokens_user_id", table_name="auth_action_tokens")
    op.drop_table("auth_action_tokens")
