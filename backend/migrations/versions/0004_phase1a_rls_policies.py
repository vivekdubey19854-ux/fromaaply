"""Install Phase 1-A RLS when running against Supabase PostgreSQL."""
from alembic import op
import sqlalchemy as sa
revision = "0004_phase1a_rls_policies"
down_revision = "0003_phase1a_coupon_referral"
branch_labels = None
depends_on = None

def _auth():
    b=op.get_bind()
    return b.dialect.name=="postgresql" and bool(b.execute(sa.text("select to_regprocedure('auth.uid()') is not null")).scalar())

SQL="""
create or replace function public.is_system_admin() returns boolean
language sql stable security definer set search_path=public,pg_catalog as $$
select coalesce((auth.jwt()->'app_metadata'->>'role')='system_admin',false)
   or coalesce((auth.jwt()->>'app_role')='system_admin',false)$$;
revoke all on function public.is_system_admin() from public;
grant execute on function public.is_system_admin() to authenticated;

alter table public.admin_api_keys enable row level security;
alter table public.admin_api_keys force row level security;
alter table public.dynamic_banners enable row level security;
alter table public.dynamic_banners force row level security;
alter table public.multi_cloud_storage_nodes enable row level security;
alter table public.multi_cloud_storage_nodes force row level security;
alter table public.user_wallets enable row level security;
alter table public.user_wallets force row level security;
alter table public.transactions enable row level security;
alter table public.transactions force row level security;
alter table public.coupons enable row level security;
alter table public.coupons force row level security;
alter table public.coupon_redemptions enable row level security;
alter table public.coupon_redemptions force row level security;
alter table public.referral_networks enable row level security;
alter table public.referral_networks force row level security;
alter table public.referral_rewards enable row level security;
alter table public.referral_rewards force row level security;

grant select,insert,update on public.admin_api_keys to authenticated;
drop policy if exists admin_api_keys_select on public.admin_api_keys;
drop policy if exists admin_api_keys_insert on public.admin_api_keys;
drop policy if exists admin_api_keys_update on public.admin_api_keys;
create policy admin_api_keys_select on public.admin_api_keys for select to authenticated using(public.is_system_admin());
create policy admin_api_keys_insert on public.admin_api_keys for insert to authenticated with check(public.is_system_admin());
create policy admin_api_keys_update on public.admin_api_keys for update to authenticated using(public.is_system_admin()) with check(public.is_system_admin());

grant select on public.dynamic_banners to anon,authenticated;
grant insert,update,delete on public.dynamic_banners to authenticated;
drop policy if exists dynamic_banners_public_select on public.dynamic_banners;
drop policy if exists dynamic_banners_admin_write on public.dynamic_banners;
create policy dynamic_banners_public_select on public.dynamic_banners for select to anon,authenticated using(is_active or public.is_system_admin());
create policy dynamic_banners_admin_write on public.dynamic_banners for all to authenticated using(public.is_system_admin()) with check(public.is_system_admin());

grant select,insert,update,delete on public.multi_cloud_storage_nodes to authenticated;
drop policy if exists multi_cloud_admin on public.multi_cloud_storage_nodes;
create policy multi_cloud_admin on public.multi_cloud_storage_nodes for all to authenticated using(public.is_system_admin()) with check(public.is_system_admin());

grant select,insert,update on public.user_wallets to authenticated;
grant select on public.transactions to authenticated;
drop policy if exists user_wallets_self on public.user_wallets;
drop policy if exists user_wallets_admin_write on public.user_wallets;
drop policy if exists transactions_self on public.transactions;
create policy user_wallets_self on public.user_wallets for select to authenticated using(auth.uid()=user_id or public.is_system_admin());
create policy user_wallets_admin_write on public.user_wallets for all to authenticated using(public.is_system_admin()) with check(public.is_system_admin());
create policy transactions_self on public.transactions for select to authenticated using(auth.uid()=user_id or public.is_system_admin());

grant select,insert,update,delete on public.coupons to authenticated;
grant select,insert on public.coupon_redemptions to authenticated;
drop policy if exists coupons_admin on public.coupons;
drop policy if exists coupon_redemptions_self on public.coupon_redemptions;
drop policy if exists coupon_redemptions_insert on public.coupon_redemptions;
create policy coupons_admin on public.coupons for all to authenticated using(public.is_system_admin()) with check(public.is_system_admin());
create policy coupon_redemptions_self on public.coupon_redemptions for select to authenticated using(auth.uid()=user_id or public.is_system_admin());
create policy coupon_redemptions_insert on public.coupon_redemptions for insert to authenticated with check(auth.uid()=user_id and exists(select 1 from public.coupons c where c.coupon_id=coupon_id and c.is_active and (c.expiry_date is null or c.expiry_date>now()) and (c.max_uses is null or c.current_uses<c.max_uses)));

grant select,insert on public.referral_networks to authenticated;
grant select on public.referral_rewards to authenticated;
drop policy if exists referral_networks_select on public.referral_networks;
drop policy if exists referral_networks_insert on public.referral_networks;
drop policy if exists referral_rewards_select on public.referral_rewards;
drop policy if exists referral_rewards_admin on public.referral_rewards;
create policy referral_networks_select on public.referral_networks for select to authenticated using(auth.uid()=referrer_id or auth.uid()=referee_id or public.is_system_admin());
create policy referral_networks_insert on public.referral_networks for insert to authenticated with check(auth.uid()=referee_id and auth.uid()<>referrer_id);
create policy referral_rewards_select on public.referral_rewards for select to authenticated using(auth.uid()=user_id or public.is_system_admin());
create policy referral_rewards_admin on public.referral_rewards for all to authenticated using(public.is_system_admin()) with check(public.is_system_admin());
"""

def upgrade():
    if _auth(): op.execute(sa.text(SQL))

def downgrade():
    if _auth():
        for t in ("referral_rewards","referral_networks","coupon_redemptions","coupons","transactions","user_wallets","multi_cloud_storage_nodes","dynamic_banners","admin_api_keys"):
            op.execute(sa.text(f"alter table public.{t} disable row level security"))
        op.execute(sa.text("drop function if exists public.is_system_admin()"))
