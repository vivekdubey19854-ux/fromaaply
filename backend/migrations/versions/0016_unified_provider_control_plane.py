"""Add extensible AI, storage and authentication provider control-plane registries."""
import json
from alembic import op
import sqlalchemy as sa

revision = "0016_unified_provider_control_plane"
down_revision = "0015_final_production_controls"
branch_labels = None
depends_on = None

AI_PROVIDERS = [
    ("gemini", "Google Gemini / AI Studio", "direct"), ("groq", "Groq", "direct"), ("openai", "OpenAI", "direct"), ("anthropic", "Anthropic", "direct"),
    ("deepseek", "DeepSeek", "direct"), ("xai", "xAI / Grok", "openai_compatible"), ("openrouter", "OpenRouter", "gateway"), ("huggingface", "Hugging Face", "direct"),
    ("mistral", "Mistral", "direct"), ("cerebras", "Cerebras", "direct"), ("nvidia_nim", "NVIDIA NIM", "openai_compatible"), ("together", "Together AI", "direct"),
    ("fireworks_ai", "Fireworks AI", "direct"), ("cohere", "Cohere", "direct"), ("perplexity", "Perplexity", "openai_compatible"), ("qwen", "Qwen / Alibaba", "openai_compatible"),
    ("deepinfra", "DeepInfra", "openai_compatible"), ("novita", "Novita AI", "openai_compatible"), ("siliconflow", "SiliconFlow", "openai_compatible"), ("hyperbolic", "Hyperbolic", "openai_compatible"),
    ("zai", "Z.ai / GLM", "openai_compatible"), ("moonshot", "Moonshot / Kimi", "openai_compatible"), ("minimax", "MiniMax", "openai_compatible"), ("sambanova", "SambaNova", "openai_compatible"),
    ("omniroute", "OmniRoute Gateway", "gateway"),
]


def upgrade() -> None:
    op.create_table("ai_provider_registry",
        sa.Column("provider", sa.String(80), primary_key=True), sa.Column("display_name", sa.String(160), nullable=False), sa.Column("adapter_type", sa.String(40), nullable=False),
        sa.Column("capabilities_json", sa.Text(), nullable=False, server_default='["general"]'), sa.Column("reasoning", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("free_tier", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("endpoint", sa.String(500)), sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("priority", sa.Integer(), nullable=False, server_default="100"), sa.Column("fallback_order", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("last_error", sa.String(500)), sa.Column("last_success_at", sa.DateTime()), sa.Column("last_test_at", sa.DateTime()), sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")), sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")))
    op.create_table("ai_model_registry",
        sa.Column("model_id", sa.String(180), primary_key=True), sa.Column("provider", sa.String(80), nullable=False), sa.Column("model_name", sa.String(160), nullable=False), sa.Column("capabilities_json", sa.Text(), nullable=False, server_default='["general"]'), sa.Column("reasoning", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("last_discovered_at", sa.DateTime()), sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"))
    op.create_table("storage_provider_registry",
        sa.Column("provider", sa.String(80), primary_key=True), sa.Column("display_name", sa.String(160), nullable=False), sa.Column("adapter_type", sa.String(40), nullable=False, server_default="s3"), sa.Column("endpoint", sa.String(500)), sa.Column("bucket", sa.String(255)), sa.Column("region", sa.String(80)), sa.Column("credentials_encrypted", sa.Text()), sa.Column("capacity_bytes", sa.BigInteger()), sa.Column("free_quota_bytes", sa.BigInteger()), sa.Column("usage_bytes", sa.BigInteger(), nullable=False, server_default="0"), sa.Column("priority", sa.Integer(), nullable=False, server_default="100"), sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("health", sa.String(30), nullable=False, server_default="unknown"), sa.Column("last_test_at", sa.DateTime()), sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")))
    op.create_table("auth_provider_registry",
        sa.Column("provider", sa.String(80), primary_key=True), sa.Column("display_name", sa.String(160), nullable=False), sa.Column("priority", sa.Integer(), nullable=False, server_default="100"), sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("methods_json", sa.Text(), nullable=False, server_default='["password"]'), sa.Column("credentials_encrypted", sa.Text()), sa.Column("health", sa.String(30), nullable=False, server_default="unknown"), sa.Column("last_test_at", sa.DateTime()), sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")))
    op.create_table("auth_identity_mappings",
        sa.Column("mapping_id", sa.String(36), primary_key=True), sa.Column("user_id", sa.String(64), nullable=False), sa.Column("provider", sa.String(80), nullable=False), sa.Column("subject", sa.String(255), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")), sa.UniqueConstraint("provider", "subject", name="uq_auth_identity_provider_subject"))
    for provider, name, adapter in AI_PROVIDERS:
        op.execute(sa.text("INSERT INTO ai_provider_registry(provider,display_name,adapter_type,capabilities_json,reasoning,free_tier,priority,fallback_order) VALUES (:provider,:name,:adapter,:capabilities,:reasoning,:free,:priority,:fallback) ON CONFLICT(provider) DO NOTHING"), {"provider": provider, "name": name, "adapter": adapter, "capabilities": json.dumps(["general", "reasoning", "coding", "structured_output"] if provider in {"deepseek", "qwen", "zai", "moonshot"} else ["general", "coding", "structured_output"]), "reasoning": provider in {"deepseek", "qwen", "zai", "moonshot", "anthropic"}, "free": provider in {"gemini", "groq", "cerebras", "huggingface", "deepseek"}, "priority": 10 if provider in {"gemini", "groq", "cerebras"} else 100, "fallback": 10 if provider != "omniroute" else 90})
    for provider, name in (("oracle_cloud", "Oracle Object Storage"), ("cloudflare_r2", "Cloudflare R2"), ("backblaze_b2", "Backblaze B2"), ("firebase_storage", "Firebase Storage"), ("supabase_storage", "Supabase Storage")):
        op.execute(sa.text("INSERT INTO storage_provider_registry(provider,display_name) VALUES (:provider,:name) ON CONFLICT(provider) DO NOTHING"), {"provider": provider, "name": name})
    for provider, name, methods in (("firebase", "Firebase Authentication", ["password", "google", "phone_otp", "token", "oauth"]), ("supabase", "Supabase Auth", ["password", "google", "phone_otp", "token", "oauth"]), ("clerk", "Clerk", ["password", "google", "phone_otp", "token", "oauth"]), ("stytch", "Stytch", ["password", "google", "phone_otp", "token", "oauth"]), ("descope", "Descope", ["password", "google", "phone_otp", "token", "oauth"])):
        op.execute(sa.text("INSERT INTO auth_provider_registry(provider,display_name,methods_json) VALUES (:provider,:name,:methods) ON CONFLICT(provider) DO NOTHING"), {"provider": provider, "name": name, "methods": json.dumps(methods)})


def downgrade() -> None:
    for table in ("auth_identity_mappings", "auth_provider_registry", "storage_provider_registry", "ai_model_registry", "ai_provider_registry"):
        op.drop_table(table)
