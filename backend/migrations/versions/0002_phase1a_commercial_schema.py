"""Phase 1-A commercial schema table contract."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = "0002_phase1a_commercial_schema"
down_revision = "0001_profile_vault"
branch_labels = None
depends_on = None

def _pg():
    return op.get_bind().dialect.name == "postgresql"

def _auth():
    return _pg() and bool(op.get_bind().execute(sa.text("select to_regprocedure('auth.uid()') is not null")).scalar())

def _id():
    return postgresql.UUID(as_uuid=False) if _pg() else sa.String(36)

def _fk(col):
    return [sa.ForeignKeyConstraint([col], ["auth.users.id"], ondelete="CASCADE")] if _auth() else []

def upgrade():
    ident = _id()
    op.create_table("admin_api_keys", sa.Column("provider_name", sa.String(100), primary_key=True), sa.Column("api_key_encrypted", sa.Text(), nullable=False), sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table("dynamic_banners", sa.Column("banner_id", ident, primary_key=True), sa.Column("image_url", sa.Text(), nullable=False), sa.Column("target_link", sa.Text()), sa.Column("position", sa.String(50), nullable=False), sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table("multi_cloud_storage_nodes", sa.Column("node_id", ident, primary_key=True), sa.Column("provider", sa.String(40), nullable=False), sa.Column("bucket_name", sa.Text(), nullable=False), sa.Column("status", sa.String(10), nullable=False, server_default="ACTIVE"), sa.Column("priority_order", sa.Integer(), nullable=False), sa.CheckConstraint("provider in ('oracle_free','ibm_cos','azure_blob')", name="multi_cloud_provider_check"), sa.CheckConstraint("status in ('ACTIVE','DOWN')", name="multi_cloud_status_check"))
    op.create_table("user_wallets", sa.Column("user_id", ident, primary_key=True), sa.Column("balance_credits", sa.Numeric(20,6), nullable=False, server_default="0"), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.CheckConstraint("balance_credits >= 0", name="user_wallets_balance_nonnegative"), *_fk("user_id"))
    op.create_table("transactions", sa.Column("transaction_id", ident, primary_key=True), sa.Column("user_id", ident, nullable=False), sa.Column("amount_paid", sa.Numeric(20,2), nullable=False, server_default="0"), sa.Column("credits_added", sa.Numeric(20,6), nullable=False, server_default="0"), sa.Column("payment_gateway", sa.String(30), nullable=False), sa.Column("status", sa.String(10), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.CheckConstraint("payment_gateway = 'razorpay'", name="transactions_gateway_check"), sa.CheckConstraint("status in ('SUCCESS','FAILED')", name="transactions_status_check"), *_fk("user_id"))
