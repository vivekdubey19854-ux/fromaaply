"""Phase 1-A coupon and referral tables."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = "0003_phase1a_coupon_referral"
down_revision = "0002_phase1a_commercial_schema"
branch_labels = None
depends_on = None

def _pg(): return op.get_bind().dialect.name == "postgresql"
def _auth(): return _pg() and bool(op.get_bind().execute(sa.text("select to_regprocedure('auth.uid()') is not null")).scalar())
def _id(): return postgresql.UUID(as_uuid=False) if _pg() else sa.String(36)
def _fk(col): return [sa.ForeignKeyConstraint([col],["auth.users.id"],ondelete="CASCADE")] if _auth() else []

def upgrade():
    ident=_id()
    op.create_table("coupons",
        sa.Column("coupon_id",ident,primary_key=True),sa.Column("code",sa.String(100),nullable=False,unique=True),
        sa.Column("discount_type",sa.String(20),nullable=False),sa.Column("discount_value",sa.Numeric(20,6),nullable=False),
        sa.Column("max_uses",sa.Integer()),sa.Column("current_uses",sa.Integer(),nullable=False,server_default="0"),
        sa.Column("expiry_date",sa.DateTime(timezone=True)),sa.Column("is_active",sa.Boolean(),nullable=False,server_default=sa.true()),
        sa.CheckConstraint("discount_type in ('fixed_amount','percentage','free_credits')",name="coupons_type_check"),
        sa.CheckConstraint("discount_value >= 0",name="coupons_value_check"),sa.CheckConstraint("max_uses is null or max_uses > 0",name="coupons_max_uses_check"),
        sa.CheckConstraint("current_uses >= 0",name="coupons_current_uses_check"))
    op.create_table("coupon_redemptions",
        sa.Column("redemption_id",ident,primary_key=True),sa.Column("user_id",ident,nullable=False),sa.Column("coupon_id",ident,nullable=False),
        sa.Column("redeemed_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.UniqueConstraint("user_id","coupon_id",name="coupon_redemptions_unique_user_coupon"),*_fk("user_id"),
        sa.ForeignKeyConstraint(["coupon_id"],["coupons.coupon_id"],ondelete="RESTRICT"))
    op.create_table("referral_networks",
        sa.Column("referrer_id",ident,nullable=False),sa.Column("referee_id",ident,primary_key=True),sa.Column("referral_code",sa.String(100),nullable=False),
        sa.Column("signed_up_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.CheckConstraint("referrer_id <> referee_id",name="referral_networks_not_self"),*_fk("referrer_id"),*_fk("referee_id"))
    op.create_table("referral_rewards",
        sa.Column("reward_id",ident,primary_key=True),sa.Column("user_id",ident,nullable=False),sa.Column("credits_awarded",sa.Numeric(20,6),nullable=False),
        sa.Column("status",sa.String(10),nullable=False,server_default="PENDING"),sa.Column("triggered_by_action",sa.String(120),nullable=False),
        sa.CheckConstraint("credits_awarded >= 0",name="referral_rewards_credit_check"),sa.CheckConstraint("status in ('PENDING','CLAIMED')",name="referral_rewards_status_check"),*_fk("user_id"))
    op.create_index("ix_coupon_redemptions_user_redeemed","coupon_redemptions",["user_id","redeemed_at"])
    op.create_index("ix_referral_networks_referrer","referral_networks",["referrer_id","signed_up_at"])
    op.create_index("ix_referral_rewards_user_status","referral_rewards",["user_id","status"])

def downgrade():
    for n,t in [("ix_referral_rewards_user_status","referral_rewards"),("ix_referral_networks_referrer","referral_networks"),("ix_coupon_redemptions_user_redeemed","coupon_redemptions")]: op.drop_index(n,table_name=t)
    for t in ("referral_rewards","referral_networks","coupon_redemptions","coupons"): op.drop_table(t)
