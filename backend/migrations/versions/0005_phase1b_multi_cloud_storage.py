"""Phase 1-B multi-cloud storage node contract."""
from alembic import op
import sqlalchemy as sa

revision = "0005_phase1b_multi_cloud_storage"
down_revision = "0004_phase1a_rls_policies"
branch_labels = None
depends_on = None


def _pg() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _pg():
        return
    op.execute(sa.text("ALTER TABLE public.multi_cloud_storage_nodes RENAME COLUMN node_id TO id"))
    op.execute(sa.text("ALTER TABLE public.multi_cloud_storage_nodes RENAME COLUMN provider TO provider_name"))
    op.execute(sa.text("ALTER TABLE public.multi_cloud_storage_nodes RENAME COLUMN priority_order TO priority"))
    op.execute(sa.text("ALTER TABLE public.multi_cloud_storage_nodes ADD COLUMN IF NOT EXISTS credentials jsonb NOT NULL DEFAULT '{}'::jsonb"))
    op.execute(sa.text("UPDATE public.multi_cloud_storage_nodes SET status='UP' WHERE status='ACTIVE'"))
    op.execute(sa.text("ALTER TABLE public.multi_cloud_storage_nodes DROP CONSTRAINT IF EXISTS multi_cloud_provider_check"))
    op.execute(sa.text("ALTER TABLE public.multi_cloud_storage_nodes DROP CONSTRAINT IF EXISTS multi_cloud_status_check"))
    op.execute(sa.text("ALTER TABLE public.multi_cloud_storage_nodes ADD CONSTRAINT multi_cloud_provider_name_check CHECK (provider_name IN ('oracle_cloud','ibm_cos','cloudflare_r2','backblaze_b2','supabase_storage'))"))
    op.execute(sa.text("ALTER TABLE public.multi_cloud_storage_nodes ADD CONSTRAINT multi_cloud_status_check CHECK (status IN ('UP','DOWN'))"))
    op.execute(sa.text("ALTER TABLE public.multi_cloud_storage_nodes ADD CONSTRAINT multi_cloud_priority_check CHECK (priority > 0)"))
    op.execute(sa.text("ALTER TABLE public.multi_cloud_storage_nodes ADD CONSTRAINT multi_cloud_credentials_object_check CHECK (jsonb_typeof(credentials)='object')"))
    op.execute(sa.text("CREATE UNIQUE INDEX IF NOT EXISTS ux_multi_cloud_storage_nodes_priority ON public.multi_cloud_storage_nodes(priority)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_multi_cloud_storage_nodes_status_priority ON public.multi_cloud_storage_nodes(status, priority)"))


def downgrade() -> None:
    if not _pg():
        return
    op.execute(sa.text("DROP INDEX IF EXISTS public.ix_multi_cloud_storage_nodes_status_priority"))
    op.execute(sa.text("DROP INDEX IF EXISTS public.ux_multi_cloud_storage_nodes_priority"))
