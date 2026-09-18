from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from app.coupon_service import CouponAlreadyRedeemed, CouponTenantViolation, CouponValidationEngine
from app.notification_service import BrevoNotificationService, BrevoSender
from app.referral_service import ReferralRewardEngine


class Result:
    def __init__(self, *, row=None, rows=None):
        self._row = row
        self._rows = rows if rows is not None else ([] if row is None else [row])

    def mappings(self):
        return self

    def first(self):
        return self._row

    def all(self):
        return self._rows


class FakeDB:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params))
        value = next(self.results)
        if isinstance(value, Exception):
            raise value
        return value

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_brevo_201_payload_and_dynamic_key():
    adapter = MagicMock()
    adapter._load_credentials.return_value = SimpleNamespace(
        payload={
            "api_key": "xkeysib-test",
            "sender_email": "no-reply@formwise.example",
            "sender_name": "Formwise",
        }
    )
    client = MagicMock()
    response = MagicMock()
    response.status_code = 201
    response.json.return_value = {"messageId": "<message@example>"}
    client.post.return_value = response

    service = BrevoNotificationService(adapter, http_client=client, sender=BrevoSender("unused@example"))
    result = service.send_receipt_invoice("user@example.com", "tx-123", "499.00", "500")

    assert result["messageId"] == "<message@example>"
    adapter._load_credentials.assert_called_once_with("brevo")
    client.post.assert_called_once()
    args = client.post.call_args
    assert args.args[0] == "https://api.brevo.com/v3/smtp/email"
    assert args.kwargs["headers"]["api-key"] == "xkeysib-test"
    assert args.kwargs["headers"]["content-type"] == "application/json"
    assert args.kwargs["json"]["to"] == [{"email": "user@example.com"}]
    assert args.kwargs["json"]["sender"] == {
        "email": "no-reply@formwise.example",
        "name": "Formwise",
    }


def test_brevo_non_201_is_strict_failure():
    adapter = MagicMock()
    adapter._load_credentials.return_value = SimpleNamespace(payload="xkeysib-test")
    client = MagicMock()
    client.post.return_value = SimpleNamespace(status_code=401, text="unauthorized")
    service = BrevoNotificationService(adapter, sender=BrevoSender("no-reply@formwise.example"), http_client=client)

    with pytest.raises(Exception, match="HTTP 401"):
        service.send_otp_alert("user@example.com", "123456")


def test_coupon_redeem_locks_coupon_and_credits_wallet():
    coupon = {
        "coupon_id": "coupon-1",
        "code": "WELCOME50",
        "discount_type": "free_credits",
        "discount_value": Decimal("50"),
        "max_uses": 10,
        "current_uses": 0,
        "expiry_date": None,
        "is_active": True,
    }
    wallet = {"balance_credits": Decimal("75")}
    db = FakeDB(
        [
            Result(row=coupon),
            Result(row=None),
            Result(row=None),  # UPDATE coupons
            Result(row=None),  # INSERT coupon_redemptions
            Result(row=wallet),
        ]
    )

    result = CouponValidationEngine(db).redeem_coupon_code("user-1", "WELCOME50")

    assert result.balance_credits_added == Decimal("50")
    assert result.wallet_balance_credits == Decimal("75")
    assert db.commits == 1
    assert any("FOR UPDATE" in sql and "coupons" in sql for sql, _ in db.calls)
    assert any("UPDATE coupons" in sql for sql, _ in db.calls)
    assert any("INSERT INTO coupon_redemptions" in sql for sql, _ in db.calls)


def test_coupon_double_redemption_rolls_back_and_raises_strict_error():
    coupon = {
        "coupon_id": "coupon-1",
        "code": "WELCOME50",
        "discount_type": "free_credits",
        "discount_value": Decimal("50"),
        "max_uses": 10,
        "current_uses": 1,
        "expiry_date": None,
        "is_active": True,
    }
    db = FakeDB([Result(row=coupon), Result(row={"redemption_id": "redemption-1"})])

    with pytest.raises(CouponAlreadyRedeemed):
        CouponValidationEngine(db).redeem_coupon_code("user-1", "WELCOME50")
    assert db.rollbacks == 1
    assert db.commits == 0


def test_coupon_cross_tenant_conflict_is_strict_and_rolls_back():
    coupon = {
        "coupon_id": "coupon-1",
        "code": "TENANT",
        "discount_type": "free_credits",
        "discount_value": Decimal("10"),
        "max_uses": 10,
        "current_uses": 0,
        "expiry_date": None,
        "is_active": True,
    }
    duplicate_or_policy_error = IntegrityError("INSERT", {}, Exception("row level security policy denied"))
    db = FakeDB([Result(row=coupon), Result(row=None), Result(row=None), duplicate_or_policy_error])

    with pytest.raises(CouponTenantViolation):
        CouponValidationEngine(db).redeem_coupon_code("user-in-another-tenant", "TENANT")
    assert db.rollbacks == 1
    assert db.commits == 0


def test_referral_signup_inserts_pending_reward_atomically():
    code_owner = {"referrer_id": "referrer-1", "referee_id": "legacy-user", "referral_code": "REF123"}
    reward = {
        "reward_id": "reward-1",
        "user_id": "referrer-1",
        "credits_awarded": Decimal("100"),
        "status": "PENDING",
    }
    db = FakeDB(
        [
            Result(row=None),
            Result(rows=[code_owner]),
            Result(row=None),  # INSERT referral_networks
            Result(row=reward),
        ]
    )

    result = ReferralRewardEngine(db).process_new_referral("REF123", "new-user")

    assert result.referrer_id == "referrer-1"
    assert result.referee_id == "new-user"
    assert result.status == "PENDING"
    assert result.credits_awarded == Decimal("100")
    assert db.commits == 1


def test_referral_payout_requires_successful_paid_transaction_and_claims_once():
    transaction = {"transaction_id": "tx-1"}
    reward = {
        "reward_id": "reward-1",
        "referrer_id": "referrer-1",
        "credits_awarded": Decimal("100"),
        "status": "PENDING",
        "referee_id": "referee-1",
    }
    wallet = {"balance_credits": Decimal("300")}
    db = FakeDB([Result(row=transaction), Result(row=reward), Result(row=wallet), Result(row=None)])

    result = ReferralRewardEngine(db).trigger_referral_payout("referee-1")

    assert result.status == "CLAIMED"
    assert result.referrer_id == "referrer-1"
    assert result.credits_awarded == Decimal("100")
    assert result.wallet_balance_credits == Decimal("300")
    assert db.commits == 1
    assert any("status = 'SUCCESS'" in sql and "amount_paid > 0" in sql for sql, _ in db.calls)
    assert any("status = 'PENDING'" in sql and "FOR UPDATE" in sql for sql, _ in db.calls)
