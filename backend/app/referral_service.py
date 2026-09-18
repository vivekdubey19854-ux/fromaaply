from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


class ReferralError(RuntimeError):
    """Base referral business-logic error."""


class ReferralCodeInvalid(ReferralError):
    pass


class ReferralSelfReference(ReferralError):
    pass


class ReferralAlreadyProcessed(ReferralError):
    pass


class ReferralRewardUnavailable(ReferralError):
    pass


@dataclass(frozen=True)
class ReferralSignupResult:
    referrer_id: str
    referee_id: str
    referral_code: str
    reward_id: str
    status: str
    credits_awarded: Decimal


@dataclass(frozen=True)
class ReferralPayoutResult:
    reward_id: str
    referrer_id: str
    referee_id: str
    credits_awarded: Decimal
    wallet_balance_credits: Decimal
    status: str


class ReferralRewardEngine:
    """Concurrency-safe referral tracking and first-paid-transaction reward service."""

    def __init__(self, db: Session, *, reward_credits: Decimal | int | float = Decimal("100")) -> None:
        self.db = db
        self.reward_credits = self._decimal(reward_credits)
        if self.reward_credits <= 0:
            raise ValueError("reward_credits must be positive")

    def process_new_referral(self, referrer_code: str, new_user_id: str) -> ReferralSignupResult:
        code = str(referrer_code).strip()
        referee_id = str(new_user_id).strip()
        if not code or not referee_id:
            raise ValueError("referrer_code and new_user_id are required")

        try:
            existing = self.db.execute(
                text("SELECT referrer_id, referee_id, referral_code FROM referral_networks WHERE referee_id = :referee_id FOR UPDATE"),
                {"referee_id": referee_id},
            ).mappings().first()
            if existing:
                self.db.rollback()
                raise ReferralAlreadyProcessed("this user already has a referral attribution")

            matches = self.db.execute(
                text(
                    "SELECT referrer_id, referee_id, referral_code FROM referral_networks "
                    "WHERE referral_code = :code FOR UPDATE"
                ),
                {"code": code},
            ).mappings().all()
            if len(matches) != 1:
                self.db.rollback()
                raise ReferralCodeInvalid("referral code is invalid or ambiguous")
            referrer_id = str(matches[0]["referrer_id"])
            if referrer_id == referee_id:
                self.db.rollback()
                raise ReferralSelfReference("a user cannot refer itself")

            try:
                self.db.execute(
                    text(
                        "INSERT INTO referral_networks (referrer_id, referee_id, referral_code) "
                        "VALUES (:referrer_id, :referee_id, :referral_code)"
                    ),
                    {"referrer_id": referrer_id, "referee_id": referee_id, "referral_code": code},
                )
                reward = self.db.execute(
                    text(
                        "INSERT INTO referral_rewards "
                        "(user_id, credits_awarded, status, triggered_by_action) "
                        "VALUES (:user_id, :credits_awarded, 'PENDING', 'referral_first_paid_transaction') "
                        "RETURNING reward_id, user_id, credits_awarded, status"
                    ),
                    {"user_id": referrer_id, "credits_awarded": self.reward_credits},
                ).mappings().first()
            except IntegrityError as exc:
                self.db.rollback()
                raise ReferralAlreadyProcessed("referral attribution already exists") from exc

            if not reward:
                self.db.rollback()
                raise ReferralError("referral reward insert did not return a row")
            self.db.commit()
            return ReferralSignupResult(
                referrer_id=referrer_id,
                referee_id=referee_id,
                referral_code=code,
                reward_id=str(reward["reward_id"]),
                status=str(reward["status"]),
                credits_awarded=self._decimal(reward["credits_awarded"]),
            )
        except ReferralError:
            raise
        except Exception as exc:
            self.db.rollback()
            raise ReferralError("referral signup processing failed") from exc

    def trigger_referral_payout(self, new_user_id: str, *, auto_commit: bool = True) -> ReferralPayoutResult:
        referee_id = str(new_user_id).strip()
        if not referee_id:
            raise ValueError("new_user_id is required")

        try:
            successful_payment = self.db.execute(
                text(
                    "SELECT transaction_id FROM transactions "
                    "WHERE user_id = :user_id AND (status = 'SUCCESS' OR status = 'SUCCESSFUL') "
                    "AND amount_paid > 0 ORDER BY created_at ASC LIMIT 1 FOR UPDATE"
                ),
                {"user_id": referee_id},
            ).mappings().first()
            if not successful_payment:
                if auto_commit:
                    self.db.rollback()
                raise ReferralRewardUnavailable("referee has not completed a paid transaction")

            reward = self.db.execute(
                text(
                    "SELECT r.reward_id, r.user_id AS referrer_id, r.credits_awarded, r.status, "
                    "n.referee_id FROM referral_rewards r "
                    "JOIN referral_networks n ON n.referrer_id = r.user_id "
                    "WHERE n.referee_id = :referee_id AND r.status = 'PENDING' "
                    "AND r.triggered_by_action = 'referral_first_paid_transaction' "
                    "ORDER BY n.signed_up_at ASC, r.reward_id ASC LIMIT 1 FOR UPDATE"
                ),
                {"referee_id": referee_id},
            ).mappings().first()
            if not reward:
                already_claimed = self.db.execute(
                    text(
                        "SELECT r.reward_id FROM referral_rewards r "
                        "JOIN referral_networks n ON n.referrer_id = r.user_id "
                        "WHERE n.referee_id = :referee_id AND r.status = 'CLAIMED' "
                        "AND r.triggered_by_action = 'referral_first_paid_transaction' "
                        "LIMIT 1"
                    ),
                    {"referee_id": referee_id},
                ).mappings().first()
                if auto_commit:
                    self.db.rollback()
                if already_claimed:
                    raise ReferralAlreadyProcessed("referral reward has already been claimed")
                raise ReferralRewardUnavailable("no pending referral reward exists")

            wallet = self.db.execute(
                text(
                    "INSERT INTO user_wallets (user_id, balance_credits, updated_at) "
                    "VALUES (:user_id, :credits, CURRENT_TIMESTAMP) "
                    "ON CONFLICT (user_id) DO UPDATE SET "
                    "balance_credits = user_wallets.balance_credits + EXCLUDED.balance_credits, "
                    "updated_at = CURRENT_TIMESTAMP RETURNING balance_credits"
                ),
                {"user_id": reward["referrer_id"], "credits": reward["credits_awarded"]},
            ).mappings().first()
            if not wallet:
                if auto_commit:
                    self.db.rollback()
                raise ReferralError("referrer wallet update did not return a balance")

            self.db.execute(
                text("UPDATE referral_rewards SET status = 'CLAIMED' WHERE reward_id = :reward_id AND status = 'PENDING'"),
                {"reward_id": reward["reward_id"]},
            )
            if auto_commit:
                self.db.commit()
            return ReferralPayoutResult(
                reward_id=str(reward["reward_id"]),
                referrer_id=str(reward["referrer_id"]),
                referee_id=referee_id,
                credits_awarded=self._decimal(reward["credits_awarded"]),
                wallet_balance_credits=self._decimal(wallet["balance_credits"]),
                status="CLAIMED",
            )
        except ReferralError:
            raise
        except Exception as exc:
            if auto_commit:
                self.db.rollback()
            raise ReferralError("referral payout processing failed") from exc

    @staticmethod
    def _decimal(value: Any) -> Decimal:
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ReferralError("invalid referral credit amount") from exc
