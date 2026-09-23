"""Add durable sessions, provider OAuth state and phone OTP challenges."""
from alembic import op
import sqlalchemy as sa

revision = "0017_real_authentication"
down_revision = "0016_unified_provider_control_plane"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("auth_provider_registry", sa.Column("credentials_encrypted", sa.Text(), nullable=True))
    op.add_column("auth_provider_registry", sa.Column("client_id", sa.String(255), nullable=True))
    op.add_column("auth_provider_registry", sa.Column("issuer", sa.String(500), nullable=True))
    op.add_column("auth_provider_registry", sa.Column("jwks_url", sa.String(500), nullable=True))
    op.add_column("auth_provider_registry", sa.Column("authorize_url", sa.String(500), nullable=True))
    op.add_column("auth_provider_registry", sa.Column("token_url", sa.String(500), nullable=True))
    op.add_column("auth_provider_registry", sa.Column("userinfo_url", sa.String(500), nullable=True))
    op.add_column("auth_provider_registry", sa.Column("otp_request_url", sa.String(500), nullable=True))
    op.add_column("auth_provider_registry", sa.Column("otp_verify_url", sa.String(500), nullable=True))
    op.create_table(
        "auth_sessions",
        sa.Column("session_id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False, index=True),
        sa.Column("refresh_jti_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
    )
    op.create_table(
        "auth_oauth_states",
        sa.Column("state_hash", sa.String(64), primary_key=True),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("nonce", sa.String(128), nullable=False),
        sa.Column("redirect_uri", sa.String(500), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "auth_otp_challenges",
        sa.Column("challenge_id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("phone_hash", sa.String(64), nullable=False, index=True),
        sa.Column("provider_reference", sa.String(255), nullable=True),
        sa.Column("user_id", sa.String(64), nullable=True, index=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_auth_sessions_active_user", "auth_sessions", ["user_id", "revoked_at"])
    op.execute(sa.text("INSERT INTO auth_provider_registry(provider,display_name,priority,enabled,methods_json,authorize_url,token_url,userinfo_url) VALUES ('google','Google OAuth',10,true,:methods,'https://accounts.google.com/o/oauth2/v2/auth','https://oauth2.googleapis.com/token','https://openidconnect.googleapis.com/v1/userinfo') ON CONFLICT(provider) DO NOTHING"), {"methods": '["oauth","google"]'})
    op.execute(sa.text("UPDATE auth_provider_registry SET methods_json=:methods WHERE provider IN ('firebase','supabase','clerk','stytch','descope')"), {"methods": '["password","google","phone_otp","token","oauth"]'})


def downgrade() -> None:
    op.drop_index("ix_auth_sessions_active_user", table_name="auth_sessions")
    op.drop_table("auth_otp_challenges")
    op.drop_table("auth_oauth_states")
    op.drop_table("auth_sessions")
    for column in ("otp_verify_url", "otp_request_url", "userinfo_url", "token_url", "authorize_url", "jwks_url", "issuer", "client_id", "credentials_encrypted"):
        op.drop_column("auth_provider_registry", column)
