from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .credential_crypto import decrypt_admin_api_key
from .notification_service import BrevoNotificationService
from .payment_service import PaymentService, PaymentSettlementResult
from .razorpay_gateway import RazorpayGatewayService


class RazorpayWebhookError(RuntimeError):
    """Base webhook processing error."""


class RazorpayWebhookUnauthorized(RazorpayWebhookError):
    """Raised when the Razorpay webhook signature is invalid."""


class RazorpayWebhookMalformed(RazorpayWebhookError):
    """Raised when the signed payload or event metadata is invalid."""


class RazorpayWebhookConflict(RazorpayWebhookError):
    """Raised for an event that cannot safely transition its ledger state."""


@dataclass(frozen=True)
class RazorpayWebhookResult:
    event_id: str
    event_name: str
    duplicate: bool
    processed: bool
    transaction: PaymentSettlementResult | None


class RazorpayWebhookService:
    """Verify, atomically claim and settle Razorpay webhook events."""

    def __init__(self, db: Session, *, payment_service_factory: Callable[[Session], PaymentService] = PaymentService, notification_service: BrevoNotificationService | None = None, credential_decryptor: Callable[[Any], Any] = decrypt_admin_api_key) -> None:
        self.db = db
        self.payment_service_factory = payment_service_factory
        self.notification_service = notification_service
        self.credential_decryptor = credential_decryptor

    def verify_and_process_webhook(self, raw_payload: bytes | str, razorpay_signature_header: str, event_id: str) -> RazorpayWebhookResult:
        payload_bytes = raw_payload.encode("utf-8") if isinstance(raw_payload, str) else bytes(raw_payload)
        normalized_event_id = str(event_id).strip()
        signature = str(razorpay_signature_header).strip()
        if not normalized_event_id or not signature:
            raise RazorpayWebhookMalformed("Razorpay event id and signature are required")

        secret = self._load_webhook_secret()
        expected = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            self.db.rollback()
            raise RazorpayWebhookUnauthorized("invalid Razorpay webhook signature")

        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self.db.rollback()
            raise RazorpayWebhookMalformed("webhook payload must be valid UTF-8 JSON") from exc
        if not isinstance(payload, Mapping):
            self.db.rollback()
            raise RazorpayWebhookMalformed("webhook payload must be a JSON object")

        event_name = str(payload.get("event", "")).strip()
        if not event_name:
            self.db.rollback()
            raise RazorpayWebhookMalformed("webhook event name is required")
        payment_id = self._extract_payment_id(payload)
        payload_hash = hashlib.sha256(payload_bytes).hexdigest()

        duplicate = self._claim_event(event_id=normalized_event_id, payment_id=payment_id, event_name=event_name, payload_hash=payload_hash)
        if duplicate:
            self.db.rollback()
            return RazorpayWebhookResult(normalized_event_id, event_name, True, False, None)

        try:
            if event_name == "order.paid":
                order_id, payment_id, amount_paise = self._extract_order_paid_fields(payload)
                settlement = self.payment_service_factory(self.db).process_order_paid(
                    razorpay_order_id=order_id, razorpay_payment_id=payment_id, paid_amount_paise=amount_paise, commit=False
                )
            elif event_name == "payment.failed":
                order_id, payment_id = self._extract_failed_payment_fields(payload)
                self.payment_service_factory(self.db).process_payment_failed(
                    razorpay_order_id=order_id, razorpay_payment_id=payment_id, commit=False
                )
                settlement = None
            else:
                settlement = None

            self.db.execute(
                text("UPDATE processed_webhooks SET status = 'PROCESSED', processed_at = CURRENT_TIMESTAMP, last_error = NULL WHERE event_id = :event_id"),
                {"event_id": normalized_event_id},
            )
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            self._mark_event_failed(normalized_event_id, str(exc))
            raise

        if settlement is not None:
            self._send_receipt_best_effort(settlement)
        return RazorpayWebhookResult(normalized_event_id, event_name, False, True, settlement)

    def _claim_event(self, *, event_id: str, payment_id: str | None, event_name: str, payload_hash: str) -> bool:
        try:
            self.db.execute(
                text("INSERT INTO processed_webhooks (event_id, razorpay_payment_id, event_name, payload_sha256, status, first_received_at) VALUES (:event_id, :payment_id, :event_name, :payload_hash, 'PROCESSING', CURRENT_TIMESTAMP)"),
                {"event_id": event_id, "payment_id": payment_id, "event_name": event_name, "payload_hash": payload_hash},
            )
            return False
        except IntegrityError:
            self.db.rollback()
            existing = self.db.execute(
                text("SELECT status, payload_sha256, event_name, event_id FROM processed_webhooks WHERE event_id = :event_id OR (:payment_id IS NOT NULL AND razorpay_payment_id = :payment_id) ORDER BY first_received_at ASC LIMIT 1 FOR UPDATE"),
                {"event_id": event_id, "payment_id": payment_id},
            ).mappings().first()
            if not existing:
                raise RazorpayWebhookConflict("webhook idempotency row disappeared during conflict handling")
            if str(existing["payload_sha256"]) != payload_hash and str(existing["event_id"]) == event_id:
                raise RazorpayWebhookConflict("Razorpay event id was reused with a different payload")
            status = str(existing["status"])
            if status == "PROCESSED":
                return True
            if status == "PROCESSING":
                return True
            if status == "FAILED":
                self.db.execute(
                    text("UPDATE processed_webhooks SET status = 'PROCESSING', event_name = :event_name, razorpay_payment_id = :payment_id, last_error = NULL WHERE event_id = :event_id"),
                    {"event_id": existing["event_id"], "event_name": event_name, "payment_id": payment_id},
                )
                return False
            raise RazorpayWebhookConflict(f"unsupported webhook status: {status}")

    def _mark_event_failed(self, event_id: str, error: str) -> None:
        try:
            self.db.execute(text("UPDATE processed_webhooks SET status = 'FAILED', last_error = :last_error WHERE event_id = :event_id"), {"event_id": event_id, "last_error": str(error)[:1000]})
            self.db.commit()
        except Exception:
            self.db.rollback()

    def _send_receipt_best_effort(self, settlement: PaymentSettlementResult) -> None:
        if not self.notification_service or not settlement.user_email:
            return
        try:
            self.notification_service.send_receipt_invoice(settlement.user_email, settlement.transaction_id, settlement.amount_in_inr, settlement.credits_added)
        except Exception:
            return
        try:
            PaymentService(self.db).mark_receipt_sent(settlement.transaction_id)
        except Exception:
            self.db.rollback()

    def _load_webhook_secret(self) -> str:
        credentials = RazorpayGatewayService(self.db, credential_decryptor=self.credential_decryptor)._load_credentials()
        return credentials.webhook_secret

    @staticmethod
    def _extract_payment_id(payload: Mapping[str, Any]) -> str | None:
        try:
            payment_id = payload["payload"]["payment"]["entity"]["id"]
        except (KeyError, TypeError):
            return None
        normalized = str(payment_id).strip()
        return normalized or None

    @staticmethod
    def _extract_order_paid_fields(payload: Mapping[str, Any]) -> tuple[str, str, int]:
        try:
            entity = payload["payload"]["payment"]["entity"]
            order_id = str(entity["order_id"]).strip()
            payment_id = str(entity["id"]).strip()
            amount = int(entity["amount"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RazorpayWebhookMalformed("order.paid payload is missing required payment fields") from exc
        if not order_id or not payment_id or amount <= 0:
            raise RazorpayWebhookMalformed("order.paid payment fields are invalid")
        return order_id, payment_id, amount

    @staticmethod
    def _extract_failed_payment_fields(payload: Mapping[str, Any]) -> tuple[str, str]:
        try:
            entity = payload["payload"]["payment"]["entity"]
            order_id = str(entity["order_id"]).strip()
            payment_id = str(entity["id"]).strip()
        except (KeyError, TypeError, ValueError) as exc:
            raise RazorpayWebhookMalformed("payment.failed payload is missing required payment fields") from exc
        if not order_id or not payment_id:
            raise RazorpayWebhookMalformed("payment.failed payment fields are invalid")
        return order_id, payment_id
