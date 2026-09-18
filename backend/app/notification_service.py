from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Any, Mapping

import httpx

from .ai_provider_adapter import MultiAIProviderAdapter

BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"


class NotificationServiceError(RuntimeError):
    """Base notification service error."""


class NotificationConfigurationError(NotificationServiceError):
    """Brevo credentials or sender configuration is missing."""


class BrevoNotificationError(NotificationServiceError):
    """Brevo rejected or failed a transactional email request."""


@dataclass(frozen=True)
class BrevoSender:
    email: str
    name: str = "Formwise"


class BrevoNotificationService:
    """Thread-safe REST client for Brevo transactional email delivery."""

    def __init__(
        self,
        provider_adapter: MultiAIProviderAdapter,
        *,
        sender: BrevoSender | None = None,
        timeout_seconds: float = 5.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.provider_adapter = provider_adapter
        self.sender = sender or BrevoSender(
            email=os.getenv("BREVO_SENDER_EMAIL", ""),
            name=os.getenv("BREVO_SENDER_NAME", "Formwise"),
        )
        self.timeout_seconds = timeout_seconds
        self._client = http_client or httpx.Client(timeout=timeout_seconds)
        self._lock = threading.RLock()

    def send_welcome_email(self, user_email: str, name: str) -> Mapping[str, Any]:
        safe_name = name.strip() or "there"
        return self._send(
            user_email,
            recipient_name=safe_name,
            subject="Welcome to Formwise",
            html_content=(
                f"<html><body><h2>Welcome, {self._escape(safe_name)}!</h2>"
                "<p>Your Formwise account is ready. Thank you for joining us.</p></body></html>"
            ),
            text_content=f"Welcome, {safe_name}! Your Formwise account is ready.",
        )

    def send_otp_alert(self, user_email: str, otp_code: str) -> Mapping[str, Any]:
        normalized_otp = str(otp_code).strip()
        if not normalized_otp:
            raise ValueError("otp_code cannot be empty")
        return self._send(
            user_email,
            subject="Your Formwise verification code",
            html_content=(
                "<html><body><p>Your Formwise verification code is:</p>"
                f"<h1>{self._escape(normalized_otp)}</h1>"
                "<p>This code should be used only for your current sign-in or verification attempt.</p></body></html>"
            ),
            text_content=f"Your Formwise verification code is {normalized_otp}.",
        )

    def send_receipt_invoice(self, user_email: str, transaction_id: str, amount: Any, credits: Any) -> Mapping[str, Any]:
        transaction = str(transaction_id).strip()
        if not transaction:
            raise ValueError("transaction_id cannot be empty")
        return self._send(
            user_email,
            subject="Formwise payment receipt",
            html_content=(
                "<html><body><h2>Payment receipt</h2>"
                f"<p><strong>Transaction:</strong> {self._escape(transaction)}</p>"
                f"<p><strong>Amount:</strong> {self._escape(str(amount))}</p>"
                f"<p><strong>Credits:</strong> {self._escape(str(credits))}</p></body></html>"
            ),
            text_content=(
                f"Formwise payment receipt. Transaction: {transaction}. "
                f"Amount: {amount}. Credits: {credits}."
            ),
        )

    def _send(
        self,
        user_email: str,
        *,
        subject: str,
        html_content: str,
        text_content: str,
        recipient_name: str | None = None,
    ) -> Mapping[str, Any]:
        email = str(user_email).strip()
        if not email or "@" not in email:
            raise ValueError("user_email must be a valid email address")
        payload = self._credential_payload()
        api_key = payload["api_key"]
        sender = BrevoSender(
            email=payload.get("sender_email") or self.sender.email,
            name=payload.get("sender_name") or self.sender.name,
        )
        if not sender.email:
            raise NotificationConfigurationError("Brevo sender email is not configured")

        body = {
            "sender": {"email": sender.email, "name": sender.name},
            "to": [{"email": email, **({"name": recipient_name} if recipient_name else {})}],
            "subject": subject,
            "htmlContent": html_content,
            "textContent": text_content,
        }
        headers = {
            "accept": "application/json",
            "api-key": api_key,
            "content-type": "application/json",
        }
        with self._lock:
            try:
                response = self._client.post(BREVO_SEND_URL, headers=headers, json=body, timeout=self.timeout_seconds)
            except httpx.HTTPError as exc:
                raise BrevoNotificationError("Brevo request failed") from exc

        if response.status_code != 201:
            detail = response.text[:500]
            raise BrevoNotificationError(f"Brevo returned HTTP {response.status_code}: {detail}")
        try:
            data = response.json()
        except ValueError as exc:
            raise BrevoNotificationError("Brevo returned a non-JSON success response") from exc
        return data

    def _credential_payload(self) -> dict[str, Any]:
        credentials = self.provider_adapter._load_credentials("brevo")
        payload = credentials.payload
        if isinstance(payload, Mapping):
            return dict(payload)
        api_key = str(payload).strip()
        if not api_key:
            raise NotificationConfigurationError("Brevo API key is empty")
        return {"api_key": api_key}

    @staticmethod
    def _escape(value: str) -> str:
        return (
            value.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#x27;")
        )

    def close(self) -> None:
        with self._lock:
            self._client.close()
