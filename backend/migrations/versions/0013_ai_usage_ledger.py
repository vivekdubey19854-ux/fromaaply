"""Add durable AI usage ledger and quota configuration."""
import sqlalchemy as sa
from alembic import op

revision = "0013_ai_usage_ledger"
down_revision = "0012_durable_task_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_usage_ledger",
        sa.Column("usage_id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("model", sa.String(160), nullable=False),
        sa.Column("request_id", sa.String(80), nullable=False),
        sa.Column("task_name", sa.String(100), nullable=False),
        sa.Column("user_id", sa.String(64)),
        sa.Column("task_id", sa.String(36)),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("fallback_from", sa.String(80)),
        sa.Column("estimated_cost", sa.Numeric(18, 8), nullable=False, server_default="0"),
        sa.Column("error_type", sa.String(120)),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    for column in ("provider", "user_id", "task_id", "status", "created_at"):
        op.create_index(f"ix_ai_usage_ledger_{column}", "ai_usage_ledger", [column])
    op.create_table(
        "ai_quota_config",
        sa.Column("quota_id", sa.Integer(), primary_key=True),
        sa.Column("scope_type", sa.String(20), nullable=False),
        sa.Column("scope_key", sa.String(160), nullable=False),
        sa.Column("daily_tokens", sa.BigInteger()),
        sa.Column("monthly_tokens", sa.BigInteger()),
        sa.Column("daily_cost", sa.Numeric(18, 8)),
        sa.Column("monthly_cost", sa.Numeric(18, 8)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("scope_type", "scope_key", name="uq_ai_quota_scope"),
    )


def downgrade() -> None:
    op.drop_table("ai_quota_config")
    for column in ("provider", "user_id", "task_id", "status", "created_at"):
        op.drop_index(f"ix_ai_usage_ledger_{column}", table_name="ai_usage_ledger")
    op.drop_table("ai_usage_ledger")
