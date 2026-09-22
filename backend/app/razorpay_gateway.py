from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Callable, Mapping

from sqlalchemy import text
from sqlalchemy.orm import Session

from .credential_crypto import decrypt_admin_api_key


class RazorpayGatewayError(RuntimeError):
    """Base Razorpay gateway error."""


class RazorpayConfigurationError(RazorpayGatewayError):
    """Raised when the gateway is not configured safely."""


class RazorpaySignatureError(RazorpayGatewayError):
    """Raised when a checkout payment signature is invalid."""


@dataclass(frozen=True)
class RazorpayCredentials:
    key_id: str
    key_secret: str
    webhook_secret: str


@dataclass(frozen=True)
class RazorpayOrderResult:
    transaction_id: str
    razorpay_order_id: str
    amount_in_inr: Decimal
    amount_in_paise: int
    credits_added: Decimal
    status: str


class RazorpayGatewayService:
    """Server-side Razorpay Orders API wrapper with locked, encrypted credentials."""

    def __init__(
        self,
        db: Session,
        *,
        credential_decryptor: Callable[[Any], Any] = decrypt_admin_api_key,
        client_factory: Callable[[tuple[str, str]], Any] | None = None,
        credits_per_inr: Decimal | int | float = Decimal("1"),
    ) -> None:
        self.db = db
        self.credential_decryptor = credential_decryptor
        self.client_factory = client_factory or self._default_client_factory
        self.credits_per_inr = self._decimal(credits_per_inr)
        if self.credits_per_inr <= 0:
            raise ValueError("credits_per_inr must be positive")

    def create_order(self, user_id: str, amount_in_inr: Decimal | int | float) -> RazorpayOrderResult:
        normalized_user_id = str(user_id).strip()
        if not normalized_user_id:
            raise ValueError("user_id is required")
        amount = self._decimal(amount_in_inr).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if amount <= 0:
            raise ValueError("amount_in_inr must be positive")
        amount_paise = int((amount * Decimal("100")).to_integral_value(rounding=ROUND_HALF_UP))
        credits = (amount * self.credits_per_inr).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)

        credentials = self._load_credentials()
        client = self.client_factory((credentials.key_id, credentials.key_secret))
        receipt = f"fw_{uuid.uuid4().hex}"
        try:
            response = client.order.create(
                data={
                    "amount": amount_paise,
                    "currency": "INR",
                    "receipt": receipt,
                }
            )
        except Exception as exc:
            raise RazorpayGatewayError("Razorpay order creation failed") from exc

        order_id = str(response.get("id", "")).strip() if isinstance(response, Mapping) else ""
        if not order_id:
            raise RazorpayGatewayError("Razorpay did not return an order id")

        transaction_id = str(uuid.uuid4())
        try:
            try:
                email_row = self.db.execute(
                    text("SELECT email FROM auth_users WHERE user_id = :user_id"),
                    {"user_id": normalized_user_id},
                ).mappings().first()
            except Exception:
                # Legacy Supabase deployments used auth.users. New production
                # deployments use the first-party auth_users migration.
                self.db.rollback()
                email_row = self.db.execute(
                    text("SELECT email FROM auth.users WHERE id = :user_id"),
                    {"user_id": normalized_user_id},
                ).mappings().first()
            user_email = str(email_row["email"]).strip() if email_row and email_row.get("email") else None
            self.db.execute(
                text(
                    "INSERT INTO transactions "
                    "(transaction_id, user_id, amount_paid, credits_added, payment_gateway, status, "
                    "razorpay_order_id, user_email, created_at, updated_at) "
                    "VALUES (:transaction_id, :user_id, :amount_paid, :credits_added, 'razorpay', 'PENDING', "
                    ":razorpay_order_id, :user_email, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {
                    "transaction_id": transaction_id,
                    "user_id": normalized_user_id,
                    "amount_paid": amount,
                    "credits_added": credits,
                    "razorpay_order_id": order_id,
                    "user_email": user_email,
                },
            )
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            raise RazorpayGatewayError("Razorpay order was created but local ledger registration failed") from exc

        return RazorpayOrderResult(
            transaction_id=transaction_id,
            razorpay_order_id=order_id,
            amount_in_inr=amount,
            amount_in_paise=amount_paise,
            credits_added=credits,
            status="PENDING",
        )

    def verify_payment_signature(self, *, order_id: str, payment_id: str, signature: str) -> bool:
        normalized_order_id = str(order_id).strip()
        normalized_payment_id = str(payment_id).strip()
        normalized_signature = str(signature).strip()
        if not normalized_order_id or not normalized_payment_id or not normalized_signature:
            raise RazorpaySignatureError("Razorpay checkout signature fields are required")
        credentials = self._load_credentials()
        client = self.client_factory((credentials.key_id, credentials.key_secret))
        try:
            client.utility.verify_payment_signature(
                {
                    "razorpay_order_id": normalized_order_id,
                    "razorpay_payment_id": normalized_payment_id,
                    "razorpay_signature": normalized_signature,
                }
            )
        except Exception as exc:
            raise RazorpaySignatureError("invalid Razorpay checkout signature") from exc
        return True

    def refund_payment(self, *, payment_id: str, amount_in_paise: int, notes: Mapping[str, str] | None = None) -> str:
        payment_id = str(payment_id).strip()
        if not payment_id or int(amount_in_paise) <= 0:
            raise ValueError("payment_id and positive refund amount are required")
        credentials = self._load_credentials()
        client = self.client_factory((credentials.key_id, credentials.key_secret))
        try:
            response = client.payment.refund(payment_id, {"amount": int(amount_in_paise), "notes": dict(notes or {})})
        except Exception as exc:
            raise RazorpayGatewayError("Razorpay refund request failed") from exc
        refund_id = str(response.get("id", "")).strip() if isinstance(response, Mapping) else ""
        if not refund_id:
            raise RazorpayGatewayError("Razorpay did not return a refund id")
        return refund_id

    def _load_credentials(self) -> RazorpayCredentials:
        dialect = getattr(getattr(self.db, "bind", None), "dialect", None)
        query = "SELECT provider_name, api_key_encrypted, is_active FROM admin_api_keys WHERE provider_name = :provider"
        if getattr(dialect, "name", "") == "postgresql":
            query += " FOR UPDATE"
        row = self.db.execute(text(query), {"provider": "razorpay"}).mappings().first()
        if not row or not row["is_active"]:
            raise RazorpayConfigurationError("Razorpay credentials are not active")
        decrypted = self.credential_decryptor(row["api_key_encrypted"])
        payload: Mapping[str, Any]
        if isinstance(decrypted, Mapping):
            payload = decrypted
        else:
            try:
                parsed = json.loads(str(decrypted))
            except (TypeError, ValueError) as exc:
                raise RazorpayConfigurationError("Razorpay credential payload must be JSON") from exc
            if not isinstance(parsed, Mapping):
                raise RazorpayConfigurationError("Razorpay credential payload must be an object")
            payload = parsed
        key_id = str(payload.get("key_id", "")).strip()
        key_secret = str(payload.get("key_secret", "")).strip()
        webhook_secret = str(payload.get("webhook_secret", "")).strip()
        if not key_id or not key_secret or not webhook_secret:
            raise RazorpayConfigurationError("Razorpay key_id, key_secret and webhook_secret are required")
        return RazorpayCredentials(key_id=key_id, key_secret=key_secret, webhook_secret=webhook_secret)

    @staticmethod
    def _default_client_factory(auth: tuple[str, str]) -> Any:
        try:
            import razorpay
        except ImportError as exc:
            raise RazorpayConfigurationError("razorpay package is not installed") from exc
        return razorpay.Client(auth=auth)

    @staticmethod
    def _decimal(value: Any) -> Decimal:
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError("invalid decimal amount") from exc
