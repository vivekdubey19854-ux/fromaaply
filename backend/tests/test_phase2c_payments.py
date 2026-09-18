from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from app.payment_webhook_service import RazorpayWebhookService, RazorpayWebhookUnauthorized
from app.razorpay_gateway import RazorpayGatewayService


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


class PaymentFakeDB:
    """Small stateful SQL session double focused on the Phase 2-C SQL contract."""

    bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    def __init__(self):
        self.transaction = {
            "transaction_id": "tx-1",
            "user_id": "user-1",
            "amount_paid": Decimal("100.00"),
            "credits_added": Decimal("100.000000"),
            "status": "PENDING",
            "user_email": "user@example.com",
            "razorpay_payment_id": None,
        }
        self.wallet_balance = Decimal("0")
        self.admin_secret = {
            "key_id": "rzp_test_id",
            "key_secret": "rzp_test_secret",
            "webhook_secret": "unit-test-webhook-secret",
        }
        self.events: dict[str, dict[str, str | None]] = {}
        self.calls: list[tuple[str, object]] = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, statement, params=None):
        sql = str(statement)
        normalized = " ".join(sql.split()).lower()
        self.calls.append((sql, params))

        if "from admin_api_keys" in normalized:
            return Result(row={"provider_name": "razorpay", "api_key_encrypted": "ciphertext", "is_active": True})
        if normalized.startswith("insert into processed_webhooks"):
            event_id = params["event_id"]
            if event_id in self.events:
                raise IntegrityError("INSERT", params, Exception("duplicate event_id"))
            self.events[event_id] = {
                "event_id": event_id,
                "status": "PROCESSING",
                "payload_sha256": params["payload_hash"],
                "event_name": params["event_name"],
                "payment_id": params.get("payment_id"),
            }
            return Result(row=None)
        if "from processed_webhooks where event_id" in normalized:
            event = self.events.get(params["event_id"])
            return Result(row=event)
        if normalized.startswith("update processed_webhooks set status = 'processed'"):
            self.events[params["event_id"]]["status"] = "PROCESSED"
            return Result(row=None)
        if normalized.startswith("update processed_webhooks set status = 'failed'"):
            self.events[params["event_id"]]["status"] = "FAILED"
            return Result(row=None)
        if normalized.startswith("update processed_webhooks set status = 'processing'"):
            self.events[params["event_id"]]["status"] = "PROCESSING"
            return Result(row=None)
        if "from transactions" in normalized and "where razorpay_order_id" in normalized:
            return Result(row=dict(self.transaction))
        if normalized.startswith("update transactions set status = 'processing'"):
            self.transaction["status"] = "PROCESSING"
            self.transaction["razorpay_payment_id"] = params["payment_id"]
            return Result(row=None)
        if normalized.startswith("update transactions set status = 'success'"):
            self.transaction["status"] = "SUCCESS"
            return Result(row=None)
        if normalized.startswith("insert into user_wallets"):
            self.wallet_balance += Decimal(str(params["credits"]))
            return Result(row={"balance_credits": self.wallet_balance})
        if "select balance_credits from user_wallets" in normalized:
            return Result(row={"balance_credits": self.wallet_balance})
        if "from transactions" in normalized and (
            "status = 'success' or status = 'successful'" in normalized
            or "status in ('success','successful')" in normalized
        ):
            # Phase 2-B referral logic accepts both legacy SUCCESSFUL and current SUCCESS
            # states. Returning the durable payment row keeps the Phase 2-C fixture compatible
            # with both state spellings while allowing the referral reward query to remain empty
            # when this user has no referral attribution.
            return Result(row={"transaction_id": self.transaction["transaction_id"]})
        if "from referral_rewards" in normalized:
            return Result(row=None)
        if normalized.startswith("insert into transactions"):
            return Result(row=None)
        if "from auth.users" in normalized:
            return Result(row={"email": "user@example.com"})
        raise AssertionError(f"Unhandled SQL in Phase 2-C fake: {sql}")

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _webhook_payload(payment_id: str = "pay_123", order_id: str = "order_123", amount: int = 10000) -> bytes:
    return json.dumps(
        {
            "entity": "event",
            "event": "order.paid",
            "payload": {
                "payment": {
                    "entity": {
                        "id": payment_id,
                        "order_id": order_id,
                        "amount": amount,
                    }
                }
            },
        },
        separators=(",", ":"),
    ).encode()


def _sign(payload: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def _decrypt_razorpay(_ciphertext):
    return json.dumps(
        {
            "key_id": "rzp_test_id",
            "key_secret": "rzp_test_secret",
            "webhook_secret": "unit-test-webhook-secret",
        }
    )


def test_successful_order_paid_verifies_signature_and_credits_wallet_once():
    db = PaymentFakeDB()
    payload = _webhook_payload()
    signature = _sign(payload, db.admin_secret["webhook_secret"])
    service = RazorpayWebhookService(db, credential_decryptor=_decrypt_razorpay)

    first = service.verify_and_process_webhook(payload, signature, "evt_123")

    assert first.processed is True
    assert first.duplicate is False
    assert first.transaction is not None
    assert first.transaction.status == "SUCCESS"
    assert db.transaction["status"] == "SUCCESS"
    assert db.wallet_balance == Decimal("100.000000")
    assert db.events["evt_123"]["status"] == "PROCESSED"
    assert db.commits == 1


def test_duplicate_event_id_is_dropped_without_second_wallet_credit():
    db = PaymentFakeDB()
    payload = _webhook_payload()
    signature = _sign(payload, db.admin_secret["webhook_secret"])
    service = RazorpayWebhookService(db, credential_decryptor=_decrypt_razorpay)

    first = service.verify_and_process_webhook(payload, signature, "evt_duplicate")
    second = service.verify_and_process_webhook(payload, signature, "evt_duplicate")

    assert first.duplicate is False
    assert second.duplicate is True
    assert second.processed is False
    assert db.wallet_balance == Decimal("100.000000")
    assert db.transaction["status"] == "SUCCESS"


def test_invalid_webhook_signature_fails_before_processing():
    db = PaymentFakeDB()
    payload = _webhook_payload()
    service = RazorpayWebhookService(db, credential_decryptor=_decrypt_razorpay)

    with pytest.raises(RazorpayWebhookUnauthorized):
        service.verify_and_process_webhook(payload, "bad-signature", "evt_bad")

    assert db.events == {}
    assert db.wallet_balance == Decimal("0")
    assert db.transaction["status"] == "PENDING"


def test_event_id_cannot_be_reused_with_different_payload():
    db = PaymentFakeDB()
    first_payload = _webhook_payload(amount=10000)
    second_payload = _webhook_payload(amount=9000)
    service = RazorpayWebhookService(db, credential_decryptor=_decrypt_razorpay)

    first_signature = _sign(first_payload, db.admin_secret["webhook_secret"])
    second_signature = _sign(second_payload, db.admin_secret["webhook_secret"])
    service.verify_and_process_webhook(first_payload, first_signature, "evt_reuse")

    with pytest.raises(Exception, match="different payload"):
        service.verify_and_process_webhook(second_payload, second_signature, "evt_reuse")

    assert db.wallet_balance == Decimal("100.000000")


def test_razorpay_order_creation_uses_paise_and_registers_pending_ledger():
    db = PaymentFakeDB()
    client = MagicMock()
    client.order.create.return_value = {"id": "order_created_1"}
    gateway = RazorpayGatewayService(
        db,
        credential_decryptor=_decrypt_razorpay,
        client_factory=lambda auth: client,
        credits_per_inr=Decimal("2"),
    )

    result = gateway.create_order("user-1", Decimal("250.50"))

    assert result.razorpay_order_id == "order_created_1"
    assert result.amount_in_paise == 25050
    assert result.credits_added == Decimal("501.000000")
    client.order.create.assert_called_once_with(
        data={"amount": 25050, "currency": "INR", "receipt": client.order.create.call_args.kwargs["data"]["receipt"]}
    )
    assert db.commits == 1
    assert any("INSERT INTO transactions" in sql and "PENDING" in sql for sql, _ in db.calls)
