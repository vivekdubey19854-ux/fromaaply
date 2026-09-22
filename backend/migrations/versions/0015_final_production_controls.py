"""Add provider policy, payment lifecycle, registry health and admin action controls."""
import sqlalchemy as sa
from alembic import op

revision = "0015_final_production_controls"
down_revision = "0014_registry_production"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("razorpay_order_id", sa.String(120), unique=True))
    op.add_column("transactions", sa.Column("razorpay_payment_id", sa.String(120)))
    op.add_column("transactions", sa.Column("user_email", sa.String(320)))
    op.add_column("transactions", sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")))
    op.add_column("transactions", sa.Column("receipt_sent_at", sa.DateTime()))
    try:
        op.drop_constraint("transactions_status_check", "transactions", type_="check")
    except Exception:
        pass
    op.create_check_constraint("transactions_status_check", "transactions", "status in ('PENDING','PROCESSING','SUCCESS','FAILED','EXPIRED','REFUNDED','PARTIALLY_REFUNDED')")
    op.create_table(
        "ai_provider_policy",
        sa.Column("provider", sa.String(80), primary_key=True), sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("daily_tokens", sa.BigInteger()), sa.Column("monthly_tokens", sa.BigInteger()),
        sa.Column("daily_cost", sa.Numeric(18, 8)), sa.Column("monthly_cost", sa.Numeric(18, 8)), sa.Column("requests_per_minute", sa.Integer()), sa.Column("cooldown_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("updated_by", sa.String(64)), sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "ai_provider_health",
        sa.Column("provider", sa.String(80), primary_key=True), sa.Column("status", sa.String(30), nullable=False, server_default="unknown"), sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("error_rate", sa.Numeric(8, 5), nullable=False, server_default="0"), sa.Column("last_success_at", sa.DateTime()), sa.Column("last_failure_at", sa.DateTime()), sa.Column("cooldown_until", sa.DateTime()), sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "website_health_history",
        sa.Column("health_id", sa.String(36), primary_key=True), sa.Column("website_id", sa.String(36), nullable=False), sa.Column("status", sa.String(30), nullable=False), sa.Column("http_status", sa.Integer()), sa.Column("latency_ms", sa.Integer()), sa.Column("error_message", sa.String(500)), sa.Column("checked_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_website_health_history_website_checked", "website_health_history", ["website_id", "checked_at"])
    op.add_column("website_registry", sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"))
    op.create_table(
        "payment_attempts",
        sa.Column("attempt_id", sa.String(36), primary_key=True), sa.Column("transaction_id", sa.String(36), nullable=False), sa.Column("provider_payment_id", sa.String(120)), sa.Column("status", sa.String(30), nullable=False), sa.Column("failure_code", sa.String(120)), sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "payment_refunds",
        sa.Column("refund_id", sa.String(36), primary_key=True), sa.Column("transaction_id", sa.String(36), nullable=False), sa.Column("provider_refund_id", sa.String(120), unique=True), sa.Column("amount_credits", sa.Numeric(20, 6), nullable=False), sa.Column("status", sa.String(30), nullable=False), sa.Column("reason", sa.String(500)), sa.Column("created_by", sa.String(64), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")), sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "payment_reconciliation",
        sa.Column("reconciliation_id", sa.String(36), primary_key=True), sa.Column("provider_event_id", sa.String(120), unique=True), sa.Column("transaction_id", sa.String(36)), sa.Column("status", sa.String(30), nullable=False), sa.Column("details", sa.Text()), sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "admin_action_previews",
        sa.Column("preview_id", sa.String(36), primary_key=True), sa.Column("admin_user_id", sa.String(64), nullable=False), sa.Column("action", sa.String(80), nullable=False), sa.Column("payload_json", sa.Text(), nullable=False), sa.Column("status", sa.String(30), nullable=False, server_default="PENDING"), sa.Column("expires_at", sa.DateTime(), nullable=False), sa.Column("confirmed_at", sa.DateTime()), sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )


def downgrade() -> None:
    for table in ("admin_action_previews", "payment_reconciliation", "payment_refunds", "payment_attempts", "website_health_history", "ai_provider_health", "ai_provider_policy"):
        op.drop_table(table)
    op.drop_column("website_registry", "failure_count")
