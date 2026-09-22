from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from .referral_service import ReferralAlreadyProcessed, ReferralRewardEngine, ReferralRewardUnavailable


class PaymentServiceError(RuntimeError):
    """Base payment ledger error."""


class PaymentOrderNotFound(PaymentServiceError):
    pass


class PaymentStateConflict(PaymentServiceError):
    pass


class PaymentAmountMismatch(PaymentServiceError):
    pass


class UnsupportedPaymentEvent(PaymentServiceError):
    pass


@dataclass(frozen=True)
class PaymentSettlementResult:
    transaction_id: str
    user_id: str
    order_id: str
    payment_id: str
    amount_in_inr: Decimal
    credits_added: Decimal
    wallet_balance_credits: Decimal
    status: str
    referral_reward_claimed: bool
    user_email: str | None


class PaymentService:
    """Concurrency-safe Razorpay transaction state machine."""

    def __init__(self, db: Session, *, referral_reward_credits: Decimal | int | float = Decimal("100")) -> None:
        self.db = db
        self.referral_reward_credits = referral_reward_credits

    def process_order_paid(self, *, razorpay_order_id: str, razorpay_payment_id: str, paid_amount_paise: int, commit: bool = True) -> PaymentSettlementResult:
        order_id = str(razorpay_order_id).strip()
        payment_id = str(razorpay_payment_id).strip()
        if not order_id or not payment_id:
            raise ValueError("razorpay_order_id and razorpay_payment_id are required")
        if int(paid_amount_paise) <= 0:
            raise ValueError("paid_amount_paise must be positive")

        row = self.db.execute(
            text("SELECT transaction_id, user_id, amount_paid, credits_added, status, user_email, razorpay_payment_id FROM transactions WHERE razorpay_order_id = :order_id FOR UPDATE"),
            {"order_id": order_id},
        ).mappings().first()
        if not row:
            self._rollback_if_needed(commit)
            raise PaymentOrderNotFound("Razorpay order is not registered in the local ledger")

        status = str(row["status"])
        if status == "SUCCESS":
            existing_payment_id = str(row["razorpay_payment_id"] or "")
            if existing_payment_id == payment_id:
                wallet_balance = self._wallet_balance(str(row["user_id"]))
                if commit:
                    self.db.commit()
                return self._result_from_row(row, order_id, payment_id, wallet_balance, False)
            self._rollback_if_needed(commit)
            raise PaymentStateConflict("a successful transaction cannot be rebound to another payment id")
        if status == "FAILED":
            self._rollback_if_needed(commit)
            raise PaymentStateConflict("a failed transaction cannot be settled as paid")
        if status not in {"PENDING", "PROCESSING"}:
            self._rollback_if_needed(commit)
            raise PaymentStateConflict(f"unsupported transaction state: {status}")

        expected_paise = int((self._decimal(row["amount_paid"]) * Decimal("100")).to_integral_value())
        if expected_paise != int(paid_amount_paise):
            self._rollback_if_needed(commit)
            raise PaymentAmountMismatch("Razorpay payment amount does not match the registered order")

        self.db.execute(
            text("UPDATE transactions SET status = 'PROCESSING', razorpay_payment_id = :payment_id, updated_at = CURRENT_TIMESTAMP WHERE transaction_id = :transaction_id AND status IN ('PENDING','PROCESSING')"),
            {"payment_id": payment_id, "transaction_id": row["transaction_id"]},
        )
        wallet = self.db.execute(
            text("INSERT INTO user_wallets (user_id, balance_credits, updated_at) VALUES (:user_id, :credits, CURRENT_TIMESTAMP) ON CONFLICT (user_id) DO UPDATE SET balance_credits = user_wallets.balance_credits + EXCLUDED.balance_credits, updated_at = CURRENT_TIMESTAMP RETURNING balance_credits"),
            {"user_id": row["user_id"], "credits": row["credits_added"]},
        ).mappings().first()
        if not wallet:
            self._rollback_if_needed(commit)
            raise PaymentServiceError("destination wallet upsert did not return a balance")

        referral_claimed = False
        try:
            referral_result = ReferralRewardEngine(self.db, reward_credits=self.referral_reward_credits).trigger_referral_payout(str(row["user_id"]), auto_commit=False)
            referral_claimed = referral_result.status == "CLAIMED"
        except (ReferralRewardUnavailable, ReferralAlreadyProcessed):
            referral_claimed = False

        self.db.execute(
            text("UPDATE transactions SET status = 'SUCCESS', updated_at = CURRENT_TIMESTAMP WHERE transaction_id = :transaction_id AND status = 'PROCESSING'"),
            {"transaction_id": row["transaction_id"]},
        )
        if commit:
            self.db.commit()
        return PaymentSettlementResult(
            transaction_id=str(row["transaction_id"]), user_id=str(row["user_id"]), order_id=order_id, payment_id=payment_id,
            amount_in_inr=self._decimal(row["amount_paid"]), credits_added=self._decimal(row["credits_added"]),
            wallet_balance_credits=self._decimal(wallet["balance_credits"]), status="SUCCESS",
            referral_reward_claimed=referral_claimed, user_email=(str(row["user_email"]).strip() if row["user_email"] else None),
        )

    def process_payment_failed(self, *, razorpay_order_id: str, razorpay_payment_id: str | None = None, commit: bool = True) -> str:
        order_id = str(razorpay_order_id).strip()
        if not order_id:
            raise ValueError("razorpay_order_id is required")
        row = self.db.execute(
            text("SELECT transaction_id, status FROM transactions WHERE razorpay_order_id = :order_id FOR UPDATE"),
            {"order_id": order_id},
        ).mappings().first()
        if not row:
            self._rollback_if_needed(commit)
            raise PaymentOrderNotFound("Razorpay order is not registered in the local ledger")
        status = str(row["status"])
        if status == "SUCCESS":
            self._rollback_if_needed(commit)
            raise PaymentStateConflict("a successful transaction cannot transition to FAILED")
        if status == "FAILED":
            if commit:
                self.db.commit()
            return "FAILED"
        if status not in {"PENDING", "PROCESSING"}:
            self._rollback_if_needed(commit)
            raise PaymentStateConflict(f"unsupported transaction state: {status}")
        self.db.execute(
            text("UPDATE transactions SET status = 'FAILED', razorpay_payment_id = COALESCE(:payment_id, razorpay_payment_id), updated_at = CURRENT_TIMESTAMP WHERE transaction_id = :transaction_id AND status IN ('PENDING','PROCESSING')"),
            {"payment_id": razorpay_payment_id, "transaction_id": row["transaction_id"]},
        )
        if commit:
            self.db.commit()
        return "FAILED"

    def mark_expired_orders(self, *, older_than_minutes: int = 30) -> int:
        result = self.db.execute(text("UPDATE transactions SET status='EXPIRED', updated_at=CURRENT_TIMESTAMP WHERE status IN ('PENDING','PROCESSING') AND created_at < CURRENT_TIMESTAMP - (:minutes * INTERVAL '1 minute')"), {"minutes": older_than_minutes})
        self.db.commit()
        return int(result.rowcount or 0)

    def retry_payment(self, *, transaction_id: str) -> dict[str, Any]:
        row = self.db.execute(text("SELECT transaction_id, status, razorpay_order_id FROM transactions WHERE transaction_id=:transaction_id FOR UPDATE"), {"transaction_id": transaction_id}).mappings().first()
        if not row:
            raise PaymentOrderNotFound("transaction not found")
        if row["status"] not in {"FAILED", "EXPIRED"}:
            raise PaymentStateConflict("only failed or expired orders can be retried")
        self.db.execute(text("UPDATE transactions SET status='PENDING', razorpay_payment_id=NULL, updated_at=CURRENT_TIMESTAMP WHERE transaction_id=:transaction_id"), {"transaction_id": transaction_id})
        self.db.execute(text("INSERT INTO payment_attempts(attempt_id,transaction_id,status,created_at) VALUES (:id,:transaction_id,'RETRY_PENDING',CURRENT_TIMESTAMP)"), {"id": str(uuid4()), "transaction_id": transaction_id})
        self.db.commit()
        return {"transaction_id": str(transaction_id), "status": "PENDING", "razorpay_order_id": row["razorpay_order_id"]}

    def request_refund(self, *, transaction_id: str, admin_user_id: str, reason: str, amount_credits: Decimal | None = None) -> dict[str, Any]:
        row = self.db.execute(text("SELECT transaction_id, user_id, credits_added, status FROM transactions WHERE transaction_id=:transaction_id FOR UPDATE"), {"transaction_id": transaction_id}).mappings().first()
        if not row or row["status"] != "SUCCESS":
            raise PaymentStateConflict("only successful transactions can be refunded")
        amount = self._decimal(amount_credits if amount_credits is not None else row["credits_added"])
        already = self.db.execute(text("SELECT COALESCE(SUM(amount_credits),0) amount FROM payment_refunds WHERE transaction_id=:transaction_id AND status IN ('REQUESTED','SUCCESS')"), {"transaction_id": transaction_id}).mappings().first()
        if self._decimal(already["amount"] if already else 0) + amount > self._decimal(row["credits_added"]):
            raise PaymentStateConflict("refund exceeds credited amount")
        refund_id = str(uuid4())
        self.db.execute(text("INSERT INTO payment_refunds(refund_id,transaction_id,amount_credits,status,reason,created_by,created_at,updated_at) VALUES (:refund_id,:transaction_id,:amount,'REQUESTED',:reason,:admin,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"), {"refund_id": refund_id, "transaction_id": transaction_id, "amount": amount, "reason": reason[:500], "admin": admin_user_id})
        self.db.execute(text("INSERT INTO audit_logs(id,user_id,action,resource_type,resource_id,created_at,details) VALUES (:id,:user_id,'PAYMENT_REFUND_REQUESTED','payment_refund',:resource_id,CURRENT_TIMESTAMP,:details)"), {"id": str(uuid4()), "user_id": admin_user_id, "resource_id": refund_id, "details": '{"sensitive":false}'})
        self.db.commit()
        return {"refund_id": refund_id, "transaction_id": str(transaction_id), "status": "REQUESTED", "amount_credits": str(amount)}

    def reconcile_unmatched(self) -> int:
        result = self.db.execute(text("INSERT INTO payment_reconciliation(reconciliation_id,provider_event_id,transaction_id,status,details,created_at) SELECT :prefix || razorpay_order_id, razorpay_order_id, transaction_id, 'MATCHED', '{\"source\":\"ledger\"}', CURRENT_TIMESTAMP FROM transactions WHERE razorpay_order_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM payment_reconciliation r WHERE r.provider_event_id=transactions.razorpay_order_id)"), {"prefix": str(uuid4()) + '-'})
        self.db.commit()
        return int(result.rowcount or 0)

    def mark_receipt_sent(self, transaction_id: str) -> None:
        self.db.execute(text("UPDATE transactions SET receipt_sent_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE transaction_id = :transaction_id AND status = 'SUCCESS' AND receipt_sent_at IS NULL"), {"transaction_id": str(transaction_id)})
        self.db.commit()

    def _wallet_balance(self, user_id: str) -> Decimal:
        wallet = self.db.execute(text("SELECT balance_credits FROM user_wallets WHERE user_id = :user_id FOR UPDATE"), {"user_id": user_id}).mappings().first()
        return self._decimal(wallet["balance_credits"]) if wallet else Decimal("0")

    @staticmethod
    def _result_from_row(row: Any, order_id: str, payment_id: str, wallet_balance: Decimal, referral_claimed: bool) -> PaymentSettlementResult:
        return PaymentSettlementResult(
            transaction_id=str(row["transaction_id"]), user_id=str(row["user_id"]), order_id=order_id, payment_id=payment_id,
            amount_in_inr=PaymentService._decimal(row["amount_paid"]), credits_added=PaymentService._decimal(row["credits_added"]),
            wallet_balance_credits=wallet_balance, status="SUCCESS", referral_reward_claimed=referral_claimed,
            user_email=(str(row["user_email"]).strip() if row["user_email"] else None),
        )

    def _rollback_if_needed(self, commit: bool) -> None:
        if commit:
            self.db.rollback()

    @staticmethod
    def _decimal(value: Any) -> Decimal:
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise PaymentServiceError("invalid monetary or credit amount") from exc
