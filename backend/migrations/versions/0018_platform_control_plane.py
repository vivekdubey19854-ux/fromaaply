"""Add durable platform settings for branding and controlled marketing configuration."""
from alembic import op
import sqlalchemy as sa

revision = "0018_platform_control_plane"
down_revision = "0017_real_authentication"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_settings",
        sa.Column("setting_key", sa.String(120), primary_key=True),
        sa.Column("setting_value_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("updated_by", sa.String(64)),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_platform_settings_updated_at", "platform_settings", ["updated_at"])


def downgrade() -> None:
    op.drop_index("ix_platform_settings_updated_at", table_name="platform_settings")
    op.drop_table("platform_settings")
