-- Formwise Phase 1-A commercial schema. Supabase/PostgreSQL source of truth.
create extension if not exists pgcrypto;

create or replace function public.is_system_admin()
returns boolean language sql stable security definer
set search_path = public, pg_catalog
as $$
  select coalesce((auth.jwt() -> 'app_metadata' ->> 'role') = 'system_admin', false)
      or coalesce((auth.jwt() ->> 'app_role') = 'system_admin', false);
$$;
revoke all on function public.is_system_admin() from public;
grant execute on function public.is_system_admin() to authenticated;

create table if not exists public.admin_api_keys (
  provider_name varchar(100) primary key,
  api_key_encrypted text not null,
  is_active boolean not null default true,
  updated_at timestamptz not null default now(),
  constraint admin_api_keys_provider_nonempty check (length(trim(provider_name)) > 0),
  constraint admin_api_keys_ciphertext_nonempty check (length(api_key_encrypted) > 0)
);
comment on table public.admin_api_keys is 'Application-layer encrypted AI provider credentials. Plaintext is forbidden.';
alter table public.admin_api_keys enable row level security;
alter table public.admin_api_keys force row level security;
grant select, insert, update on public.admin_api_keys to authenticated;
create policy admin_api_keys_select on public.admin_api_keys for select to authenticated using (public.is_system_admin());
create policy admin_api_keys_insert on public.admin_api_keys for insert to authenticated with check (public.is_system_admin());
create policy admin_api_keys_update on public.admin_api_keys for update to authenticated using (public.is_system_admin()) with check (public.is_system_admin());

create table if not exists public.dynamic_banners (
  banner_id uuid primary key default gen_random_uuid(),
  image_url text not null,
  target_link text,
  position varchar(50) not null,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  constraint dynamic_banners_position_nonempty check (length(trim(position)) > 0)
);
alter table public.dynamic_banners enable row level security;
alter table public.dynamic_banners force row level security;
grant select, insert, update, delete on public.dynamic_banners to authenticated;
grant select on public.dynamic_banners to anon;
create policy dynamic_banners_public_select on public.dynamic_banners for select to anon, authenticated using (is_active = true or public.is_system_admin());
create policy dynamic_banners_admin_insert on public.dynamic_banners for insert to authenticated with check (public.is_system_admin());
create policy dynamic_banners_admin_update on public.dynamic_banners for update to authenticated using (public.is_system_admin()) with check (public.is_system_admin());
create policy dynamic_banners_admin_delete on public.dynamic_banners for delete to authenticated using (public.is_system_admin());
create index if not exists ix_dynamic_banners_active_position on public.dynamic_banners (is_active, position, created_at desc);

create table if not exists public.multi_cloud_storage_nodes (
  node_id uuid primary key default gen_random_uuid(),
  provider varchar(40) not null,
  bucket_name text not null,
  status varchar(10) not null default 'ACTIVE',
  priority_order integer not null,
  constraint multi_cloud_provider_check check (provider in ('oracle_free','ibm_cos','azure_blob')),
  constraint multi_cloud_status_check check (status in ('ACTIVE','DOWN')),
  constraint multi_cloud_priority_check check (priority_order > 0),
  constraint multi_cloud_unique_priority unique (priority_order)
);
alter table public.multi_cloud_storage_nodes enable row level security;
alter table public.multi_cloud_storage_nodes force row level security;
grant select, insert, update, delete on public.multi_cloud_storage_nodes to authenticated;
create policy multi_cloud_admin_select on public.multi_cloud_storage_nodes for select to authenticated using (public.is_system_admin());
create policy multi_cloud_admin_insert on public.multi_cloud_storage_nodes for insert to authenticated with check (public.is_system_admin());
create policy multi_cloud_admin_update on public.multi_cloud_storage_nodes for update to authenticated using (public.is_system_admin()) with check (public.is_system_admin());
create policy multi_cloud_admin_delete on public.multi_cloud_storage_nodes for delete to authenticated using (public.is_system_admin());

create table if not exists public.user_wallets (
  user_id uuid primary key references auth.users(id) on delete cascade,
  balance_credits numeric(20,6) not null default 0,
  updated_at timestamptz not null default now(),
  constraint user_wallets_balance_nonnegative check (balance_credits >= 0)
);
create table if not exists public.transactions (
  transaction_id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  amount_paid numeric(20,2) not null default 0,
  credits_added numeric(20,6) not null default 0,
  payment_gateway varchar(30) not null,
  status varchar(10) not null,
  created_at timestamptz not null default now(),
  constraint transactions_gateway_check check (payment_gateway = 'razorpay'),
  constraint transactions_status_check check (status in ('SUCCESS','FAILED')),
  constraint transactions_amount_nonnegative check (amount_paid >= 0),
  constraint transactions_credits_nonnegative check (credits_added >= 0)
);
alter table public.user_wallets enable row level security;
alter table public.user_wallets force row level security;
alter table public.transactions enable row level security;
alter table public.transactions force row level security;
grant select, insert, update on public.user_wallets to authenticated;
grant select on public.transactions to authenticated;
create policy user_wallets_self_select on public.user_wallets for select to authenticated using (auth.uid() = user_id or public.is_system_admin());
create policy user_wallets_admin_insert on public.user_wallets for insert to authenticated with check (public.is_system_admin());
create policy user_wallets_admin_update on public.user_wallets for update to authenticated using (public.is_system_admin()) with check (public.is_system_admin());
create policy transactions_self_select on public.transactions for select to authenticated using (auth.uid() = user_id or public.is_system_admin());
create index if not exists ix_transactions_user_created on public.transactions (user_id, created_at desc);

create table if not exists public.coupons (
  coupon_id uuid primary key default gen_random_uuid(),
  code varchar(100) not null unique,
  discount_type varchar(20) not null,
  discount_value numeric(20,6) not null,
  max_uses integer,
  current_uses integer not null default 0,
  expiry_date timestamptz,
  is_active boolean not null default true,
  constraint coupons_type_check check (discount_type in ('fixed_amount','percentage','free_credits')),
  constraint coupons_value_check check (discount_value >= 0),
  constraint coupons_max_uses_check check (max_uses is null or max_uses > 0),
  constraint coupons_current_uses_check check (current_uses >= 0),
  constraint coupons_use_limit_check check (max_uses is null or current_uses <= max_uses)
);
create table if not exists public.coupon_redemptions (
  redemption_id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  coupon_id uuid not null references public.coupons(coupon_id) on delete restrict,
  redeemed_at timestamptz not null default now(),
  constraint coupon_redemptions_unique_user_coupon unique (user_id, coupon_id)
);
alter table public.coupons enable row level security;
alter table public.coupons force row level security;
alter table public.coupon_redemptions enable row level security;
alter table public.coupon_redemptions force row level security;
grant select, insert, update, delete on public.coupons to authenticated;
grant select, insert on public.coupon_redemptions to authenticated;
create policy coupons_admin_all on public.coupons for all to authenticated using (public.is_system_admin()) with check (public.is_system_admin());
create policy coupon_redemptions_self_select on public.coupon_redemptions for select to authenticated using (auth.uid() = user_id or public.is_system_admin());
create policy coupon_redemptions_valid_insert on public.coupon_redemptions for insert to authenticated
  with check (auth.uid() = user_id and exists (
    select 1 from public.coupons c where c.coupon_id = coupon_id and c.is_active
      and (c.expiry_date is null or c.expiry_date > now())
      and (c.max_uses is null or c.current_uses < c.max_uses)
  ));

create or replace function public.validate_and_increment_coupon_redemption()
returns trigger language plpgsql security definer
set search_path = public, pg_catalog
as $$
declare c public.coupons%rowtype;
begin
  select * into c from public.coupons where coupon_id = new.coupon_id for update;
  if not found then raise exception 'COUPON_NOT_FOUND' using errcode = 'P0001'; end if;
  if not c.is_active or (c.expiry_date is not null and c.expiry_date <= now())
     or (c.max_uses is not null and c.current_uses >= c.max_uses)
  then raise exception 'COUPON_UNAVAILABLE' using errcode = 'P0001'; end if;
  update public.coupons set current_uses = current_uses + 1 where coupon_id = c.coupon_id;
  return new;
end;
$$;
revoke all on function public.validate_and_increment_coupon_redemption() from public;
drop trigger if exists trg_validate_coupon_redemption on public.coupon_redemptions;
create trigger trg_validate_coupon_redemption before insert on public.coupon_redemptions
for each row execute function public.validate_and_increment_coupon_redemption();
create index if not exists ix_coupon_redemptions_user_redeemed on public.coupon_redemptions (user_id, redeemed_at desc);

create table if not exists public.referral_networks (
  referrer_id uuid not null references auth.users(id) on delete cascade,
  referee_id uuid primary key references auth.users(id) on delete cascade,
  referral_code varchar(100) not null,
  signed_up_at timestamptz not null default now(),
  constraint referral_networks_not_self check (referrer_id <> referee_id)
);
create table if not exists public.referral_rewards (
  reward_id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  credits_awarded numeric(20,6) not null,
  status varchar(10) not null default 'PENDING',
  triggered_by_action varchar(120) not null,
  constraint referral_rewards_credit_check check (credits_awarded >= 0),
  constraint referral_rewards_status_check check (status in ('PENDING','CLAIMED'))
);
alter table public.referral_networks enable row level security;
alter table public.referral_networks force row level security;
alter table public.referral_rewards enable row level security;
alter table public.referral_rewards force row level security;
grant select, insert on public.referral_networks to authenticated;
grant select on public.referral_rewards to authenticated;
create policy referral_networks_participant_select on public.referral_networks for select to authenticated
  using (auth.uid() = referrer_id or auth.uid() = referee_id or public.is_system_admin());
create policy referral_networks_referee_insert on public.referral_networks for insert to authenticated
  with check (auth.uid() = referee_id and auth.uid() <> referrer_id);
create policy referral_networks_admin_write on public.referral_networks for update to authenticated
  using (public.is_system_admin()) with check (public.is_system_admin());
create policy referral_rewards_self_select on public.referral_rewards for select to authenticated
  using (auth.uid() = user_id or public.is_system_admin());
create policy referral_rewards_admin_insert on public.referral_rewards for insert to authenticated
  with check (public.is_system_admin());
create policy referral_rewards_admin_update on public.referral_rewards for update to authenticated
  using (public.is_system_admin()) with check (public.is_system_admin());
create policy referral_rewards_admin_delete on public.referral_rewards for delete to authenticated using (public.is_system_admin());
create index if not exists ix_referral_networks_referrer on public.referral_networks (referrer_id, signed_up_at desc);
create index if not exists ix_referral_rewards_user_status on public.referral_rewards (user_id, status);

create or replace function public.claim_referral_reward(p_reward_id uuid)
returns public.referral_rewards language plpgsql security definer
set search_path = public, pg_catalog
as $$
declare reward public.referral_rewards%rowtype;
begin
  select * into reward from public.referral_rewards where reward_id = p_reward_id and user_id = auth.uid() for update;
  if not found then raise exception 'REWARD_NOT_FOUND' using errcode = 'P0001'; end if;
  if reward.status <> 'PENDING' then raise exception 'REWARD_ALREADY_CLAIMED' using errcode = 'P0001'; end if;
  insert into public.user_wallets(user_id, balance_credits, updated_at)
    values (reward.user_id, reward.credits_awarded, now())
    on conflict (user_id) do update set balance_credits = public.user_wallets.balance_credits + excluded.balance_credits, updated_at = now();
  update public.referral_rewards set status = 'CLAIMED' where reward_id = reward.reward_id;
  select * into reward from public.referral_rewards where reward_id = reward.reward_id;
  return reward;
end;
$$;
revoke all on function public.claim_referral_reward(uuid) from public;
grant execute on function public.claim_referral_reward(uuid) to authenticated;
