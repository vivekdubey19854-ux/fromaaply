"""Add durable task, browser-session, event and lock lifecycle tables."""

import sqlalchemy as sa
from alembic import op

revision = "0012_durable_task_runtime"
down_revision = "0011_auth_action_tokens"
branch_labels = None
depends_on = None


def _indexes(table: str, columns: list[str]) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column], unique=False)


def upgrade() -> None:
    op.create_table(
        "form_tasks",
        sa.Column("task_id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("workflow_id", sa.String(36)), sa.Column("website_id", sa.String(36)),
        sa.Column("state", sa.String(40), nullable=False, server_default="queued"), sa.Column("current_step", sa.String(100)),
        sa.Column("target_url", sa.String(500)), sa.Column("browser_session_id", sa.String(100)),
        sa.Column("error_code", sa.String(80)), sa.Column("error_message", sa.String(1000)),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("idempotency_key", sa.String(160), unique=True),
        sa.Column("resume_reference", sa.String(200)), sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")), sa.Column("started_at", sa.DateTime()),
        sa.Column("completed_at", sa.DateTime()), sa.Column("paused_at", sa.DateTime()),
    )
    op.create_table(
        "task_steps",
        sa.Column("step_id", sa.String(36), primary_key=True), sa.Column("task_id", sa.String(36), nullable=False), sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("step_name", sa.String(100), nullable=False), sa.Column("state", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"), sa.Column("error_code", sa.String(80)),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")), sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "browser_sessions",
        sa.Column("browser_session_id", sa.String(100), primary_key=True), sa.Column("task_id", sa.String(36), nullable=False), sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("state", sa.String(30), nullable=False, server_default="created"), sa.Column("target_url", sa.String(500)),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")), sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")), sa.Column("expires_at", sa.DateTime()),
    )
    op.create_table(
        "browser_session_events",
        sa.Column("event_id", sa.String(36), primary_key=True), sa.Column("browser_session_id", sa.String(100), nullable=False), sa.Column("task_id", sa.String(36), nullable=False), sa.Column("user_id", sa.String(64), nullable=False), sa.Column("event_type", sa.String(80), nullable=False), sa.Column("details", sa.Text()), sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "workflow_events",
        sa.Column("event_id", sa.String(36), primary_key=True), sa.Column("task_id", sa.String(36), nullable=False), sa.Column("workflow_id", sa.String(36)), sa.Column("user_id", sa.String(64), nullable=False), sa.Column("event_type", sa.String(80), nullable=False), sa.Column("from_state", sa.String(40)), sa.Column("to_state", sa.String(40)), sa.Column("details", sa.Text()), sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "task_locks",
        sa.Column("task_id", sa.String(36), primary_key=True), sa.Column("owner_id", sa.String(120), nullable=False), sa.Column("locked_until", sa.DateTime(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    for table, columns in {
        "form_tasks": ["user_id", "workflow_id", "website_id", "state", "browser_session_id"],
        "task_steps": ["task_id", "user_id"],
        "browser_sessions": ["task_id", "user_id"],
        "browser_session_events": ["browser_session_id", "task_id", "user_id"],
        "workflow_events": ["task_id", "workflow_id", "user_id"],
        "task_locks": ["locked_until"],
    }.items():
        _indexes(table, columns)


def downgrade() -> None:
    for table, columns in {
        "task_locks": ["locked_until"], "workflow_events": ["task_id", "workflow_id", "user_id"],
        "browser_session_events": ["browser_session_id", "task_id", "user_id"], "browser_sessions": ["task_id", "user_id"],
        "task_steps": ["task_id", "user_id"], "form_tasks": ["user_id", "workflow_id", "website_id", "state", "browser_session_id"],
    }.items():
        for column in columns:
            op.drop_index(f"ix_{table}_{column}", table_name=table)
    for table in ("task_locks", "workflow_events", "browser_session_events", "browser_sessions", "task_steps", "form_tasks"):
        op.drop_table(table)
