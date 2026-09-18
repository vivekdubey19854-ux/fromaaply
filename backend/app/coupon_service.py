from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


class CouponError(RuntimeError):
    """Base coupon business-logic error."""


class CouponNotFound(CouponError):
    pass


class CouponUnavailable(CouponError):
    pass


class CouponAlreadyRedeemed(CouponError):
    pass


class CouponTenantViolation(CouponError):
    """Raised when a tenant/user attempts to redeem another tenant's redemption."""


class CouponRedemptionError(CouponError):
    pass


@dataclass(frozen=True)
class CouponRedemptionResult:
    coupon_id: str
    user_id: str
    code: str
    discount_type: str
    discount_value: Decimal
    balance_credits_added: Decimal
    wallet_balance_credits: Decimal


class CouponValidationEngine:
    """Atomic, row-locked coupon validator and wallet crediting service.

    Percentage coupons require a caller-provided credit base because the schema exposes
    no purchase amount on ``redeem_coupon_code``. The base defaults to 100 credits and
    should be overridden by the commercial plan when percentage coupons are enabled.
    """

    def __init__(self, db: Session, *, percentage_base_credits: Decimal | int | float = Decimal("100")) -> None:
        self.db = db
        self.percentage_base_credits = Decimal(str(percentage_base_credits))
        if self.percentage_base_credits < 0:
            raise ValueError("percentage_base_credits cannot be negative")

    def redeem_coupon_code(self, user_id: str, coupon_code_string: str) -> CouponRedemptionResult:
        user_id = str(user_id).strip()
        code = str(coupon_code_string).strip()
        if not user_id or not code:
            raise ValueError("user_id and coupon_code_string are required")

        self._ensure_transaction_boundary()
        try:
            coupon = self._lock_coupon(code)
            if coupon is None:
                self.db.rollback()
                raise CouponNotFound("coupon does not exist")
            if not coupon["is_active"] or self._expired(coupon["expiry_date"]):
                self.db.rollback()
                raise CouponUnavailable("coupon is inactive or expired")
            if coupon["max_uses"] is not None and coupon["current_uses"] >= coupon["max_uses"]:
                self.db.rollback()
                raise CouponUnavailable("coupon usage limit reached")

            prior = self.db.execute(
                text(
                    "SELECT redemption_id FROM coupon_redemptions "
                    "WHERE user_id = :user_id AND coupon_id = :coupon_id FOR UPDATE"
                ),
                {"user_id": user_id, "coupon_id": coupon["coupon_id"]},
            ).mappings().first()
            if prior:
                self.db.rollback()
                raise CouponAlreadyRedeemed("this user has already redeemed this coupon")

            credit_amount = self._calculate_credits(coupon["discount_type"], coupon["discount_value"])
            if credit_amount <= 0:
                self.db.rollback()
                raise CouponUnavailable("coupon has no positive credit value")

            self.db.execute(
                text("UPDATE coupons SET current_uses = current_uses + 1 WHERE coupon_id = :coupon_id"),
                {"coupon_id": coupon["coupon_id"]},
            )
            try:
                self.db.execute(
                    text(
                        "INSERT INTO coupon_redemptions (user_id, coupon_id) "
                        "VALUES (:user_id, :coupon_id)"
                    ),
                    {"user_id": user_id, "coupon_id": coupon["coupon_id"]},
                )
            except IntegrityError as exc:
                self.db.rollback()
                message = str(exc).lower()
                if "unique" in message or "duplicate" in message:
                    raise CouponAlreadyRedeemed("this user has already redeemed this coupon") from exc
                raise CouponTenantViolation("coupon redemption was rejected by tenant policy") from exc

            wallet = self.db.execute(
                text(
                    "INSERT INTO user_wallets (user_id, balance_credits, updated_at) "
                    "VALUES (:user_id, :credits, CURRENT_TIMESTAMP) "
                    "ON CONFLICT (user_id) DO UPDATE SET "
                    "balance_credits = user_wallets.balance_credits + EXCLUDED.balance_credits, "
                    "updated_at = CURRENT_TIMESTAMP "
                    "RETURNING balance_credits"
                ),
                {"user_id": user_id, "credits": credit_amount},
            ).mappings().first()
            if not wallet:
                self.db.rollback()
                raise CouponRedemptionError("wallet update did not return a balance")

            self.db.commit()
            return CouponRedemptionResult(
                coupon_id=str(coupon["coupon_id"]),
                user_id=user_id,
                code=str(coupon["code"]),
                discount_type=str(coupon["discount_type"]),
                discount_value=self._decimal(coupon["discount_value"]),
                balance_credits_added=credit_amount,
                wallet_balance_credits=self._decimal(wallet["balance_credits"]),
            )
        except CouponError:
            raise
        except Exception as exc:
            self.db.rollback()
            raise CouponRedemptionError("coupon redemption transaction failed") from exc

    def _lock_coupon(self, code: str) -> Mapping[str, Any] | None:
        query = (
            "SELECT coupon_id, code, discount_type, discount_value, max_uses, current_uses, "
            "expiry_date, is_active FROM coupons WHERE code = :code FOR UPDATE"
        )
        return self.db.execute(text(query), {"code": code}).mappings().first()

    def _calculate_credits(self, discount_type: str, discount_value: Any) -> Decimal:
        value = self._decimal(discount_value)
        if discount_type in {"fixed_amount", "free_credits"}:
            return value
        if discount_type == "percentage":
            return (self.percentage_base_credits * value / Decimal("100")).quantize(Decimal("0.000001"))
        raise CouponUnavailable(f"unsupported coupon type: {discount_type}")

    @staticmethod
    def _decimal(value: Any) -> Decimal:
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise CouponRedemptionError("invalid coupon numeric value") from exc

    @staticmethod
    def _expired(value: Any) -> bool:
        if value is None:
            return False
        current = datetime.now(timezone.utc)
        if getattr(value, "tzinfo", None) is None:
            value = value.replace(tzinfo=timezone.utc)
        return current > value

    def _ensure_transaction_boundary(self) -> None:
        """Document that caller-visible changes are committed only after wallet crediting succeeds."""
        if not hasattr(self.db, "commit") or not hasattr(self.db, "rollback"):
            raise TypeError("db must be a SQLAlchemy Session-compatible object")
