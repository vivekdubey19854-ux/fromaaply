from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SUPABASE_SQL = (ROOT / "supabase" / "migrations" / "20260913140000_phase1a_commercial_schema_upgrade.sql").read_text(encoding="utf-8")
HEARTBEAT_SQL = (ROOT / "supabase" / "migrations" / "20260913140100_phase1a_supabase_heartbeat.sql").read_text(encoding="utf-8")

TABLES = (
    "admin_api_keys", "dynamic_banners", "multi_cloud_storage_nodes",
    "user_wallets", "transactions", "coupons", "coupon_redemptions",
    "referral_networks", "referral_rewards",
)


REQUESTED_PROVIDERS = {
    "OpenAI", "Gemini", "Claude", "Azure Document Intelligence", "AWS Bedrock",
    "Groq", "DeepSeek", "NVIDIA NIM", "Cerebras", "Together AI", "Fireworks",
    "Lepton", "OpenRouter", "HuggingFace", "Novita", "Perplexity", "Cohere",
    "Mistral", "Base64.ai",
}


def test_all_phase1a_tables_enable_and_force_rls():
    for table in TABLES:
        assert f"alter table public.{table} enable row level security" in SUPABASE_SQL
        assert f"alter table public.{table} force row level security" in SUPABASE_SQL


def test_admin_api_keys_are_system_admin_only():
    block = SUPABASE_SQL[SUPABASE_SQL.index("create table if not exists public.admin_api_keys"):SUPABASE_SQL.index("create table if not exists public.dynamic_banners")]
    assert "api_key_encrypted text not null" in block
    policies = re.findall(r"create policy admin_api_keys_[^\n]+", block)
    assert len(policies) == 3
    assert all("public.is_system_admin()" in policy for policy in policies)
    assert "auth.uid() =" not in block


def test_user_wallet_and_transaction_reads_are_tenant_scoped():
    wallet = SUPABASE_SQL[SUPABASE_SQL.index("create table if not exists public.user_wallets"):SUPABASE_SQL.index("create table if not exists public.coupons")]
    assert "auth.uid() = user_id" in wallet
    assert "create policy user_wallets_self_select" in wallet
    assert "create policy transactions_self_select" in wallet
    assert "create policy user_wallets_admin_update" in wallet


def test_banners_are_public_read_only_when_active():
    block = SUPABASE_SQL[SUPABASE_SQL.index("create table if not exists public.dynamic_banners"):SUPABASE_SQL.index("create table if not exists public.multi_cloud_storage_nodes")]
    assert "grant select on public.dynamic_banners to anon" in block
    assert "using (is_active = true or public.is_system_admin())" in block
    assert "create policy dynamic_banners_admin_insert" in block
    assert "create policy dynamic_banners_admin_update" in block
    assert "create policy dynamic_banners_admin_delete" in block


def test_coupon_redemption_has_row_lock_and_max_use_validation():
    assert "for update" in SUPABASE_SQL[SUPABASE_SQL.index("create or replace function public.validate_and_increment_coupon_redemption"):SUPABASE_SQL.index("create table if not exists public.referral_networks")]
    assert "current_uses + 1" in SUPABASE_SQL
    assert "current_uses < c.max_uses" in SUPABASE_SQL
    assert "unique (user_id, coupon_id)" in SUPABASE_SQL


def test_referral_reads_are_participant_scoped():
    block = SUPABASE_SQL[SUPABASE_SQL.index("create table if not exists public.referral_networks"):]
    assert "auth.uid() = referrer_id or auth.uid() = referee_id" in block
    assert "auth.uid() = referee_id" in block
    assert "referrer_id <> referee_id" in block
    assert "grant select on public.referral_rewards to authenticated" in block


def test_requested_provider_set_is_documented_without_limiting_future_20_plus_support():
    # The table intentionally accepts future provider names (subject to non-empty validation)
    # rather than freezing the schema at the 19 names listed in the launch request.
    assert len(REQUESTED_PROVIDERS) == 19
    assert "provider_name varchar(100) primary key" in SUPABASE_SQL
    assert "admin_api_keys_provider_nonempty" in SUPABASE_SQL or "length(trim(provider_name)) > 0" in SUPABASE_SQL


def test_heartbeat_is_daily_and_explicitly_not_claimed_as_a_platform_bypass():
    assert "'0 2 * * *'" in HEARTBEAT_SQL
    assert "formwise-daily-db-heartbeat" in HEARTBEAT_SQL
    assert "NOT a guaranteed anti-pause bypass" in HEARTBEAT_SQL


def test_no_plaintext_api_key_column_is_added():
    assert "api_key text" not in SUPABASE_SQL.lower()
    assert "api_key_encrypted text not null" in SUPABASE_SQL
