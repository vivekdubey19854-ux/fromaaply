"""Add the Phase 3-A global pricing configuration singleton."""

from alembic import op
import sqlalchemy as sa

revision = "0006_phase3a_admin_config"
down_revision = "0005_phase1b_multi_cloud_storage"
branch_labels = None
depends_on = None


SQL = """
create table if not exists public.admin_pricing_config (
    config_id integer primary key,
    credits_per_currency_unit numeric(20,6) not null,
    default_form_fill_cost_credits numeric(20,6) not null,
    currency_credit_ratios text not null,
    updated_by varchar(128) not null,
    updated_at timestamptz not null default now(),
    constraint admin_pricing_singleton check (config_id = 1),
    constraint admin_pricing_credits_positive check (credits_per_currency_unit > 0),
    constraint admin_pricing_fill_cost_positive check (default_form_fill_cost_credits > 0),
    constraint admin_pricing_ratios_nonempty check (length(trim(currency_credit_ratios)) > 0)
);

alter table public.admin_pricing_config enable row level security;
alter table public.admin_pricing_config force row level security;
grant select, insert, update on public.admin_pricing_config to authenticated;
drop policy if exists admin_pricing_admin_all on public.admin_pricing_config;
create policy admin_pricing_admin_all on public.admin_pricing_config
for all to authenticated using (public.is_system_admin()) with check (public.is_system_admin());
"""


def _auth():
    bind = op.get_bind()
    return bind.dialect.name == "postgresql" and bool(
        bind.execute(sa.text("select to_regprocedure('auth.uid()') is not null")).scalar()
    )


def upgrade():
    if _auth():
        op.execute(sa.text(SQL))


def downgrade():
    if _auth():
        op.execute(sa.text("drop table if exists public.admin_pricing_config"))
