from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .ai_provider_adapter import MultiAIProviderAdapter
from .auth import require_user_id
from .credential_crypto import decrypt_admin_api_key
from .database import get_db
from .notification_service import BrevoNotificationService
from .payment_webhook_service import RazorpayWebhookService, RazorpayWebhookError, RazorpayWebhookUnauthorized
from .razorpay_gateway import RazorpayGatewayError, RazorpayGatewayService

router = APIRouter(prefix="/payments", tags=["payments"])


class CreatePaymentOrderRequest(BaseModel):
    amount_in_inr: Decimal = Field(gt=Decimal("0"), max_digits=12, decimal_places=2)


@router.post("/orders")
def create_payment_order(
    body: CreatePaymentOrderRequest,
    db: Session = Depends(get_db),
    user_id: str = Depends(require_user_id),
) -> dict[str, Any]:
    try:
        result = RazorpayGatewayService(db).create_order(user_id, body.amount_in_inr)
    except (ValueError, RazorpayGatewayError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "transaction_id": result.transaction_id,
        "razorpay_order_id": result.razorpay_order_id,
        "amount_in_inr": str(result.amount_in_inr),
        "amount_in_paise": result.amount_in_paise,
        "credits_added": str(result.credits_added),
        "status": result.status,
        "currency": "INR",
    }


@router.post("/razorpay/webhook", status_code=200)
async def razorpay_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_razorpay_signature: str | None = Header(default=None),
    x_razorpay_event_id: str | None = Header(default=None),
) -> dict[str, Any]:
    if not x_razorpay_signature or not x_razorpay_event_id:
        raise HTTPException(status_code=400, detail="Razorpay webhook signature and event id are required")

    provider_adapter = MultiAIProviderAdapter(db, credential_decryptor=decrypt_admin_api_key)
    notification_service = BrevoNotificationService(provider_adapter)
    service = RazorpayWebhookService(
        db,
        notification_service=notification_service,
        credential_decryptor=decrypt_admin_api_key,
    )
    raw_payload = await request.body()
    try:
        result = service.verify_and_process_webhook(
            raw_payload,
            x_razorpay_signature,
            x_razorpay_event_id,
        )
    except RazorpayWebhookUnauthorized as exc:
        notification_service.close()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RazorpayWebhookError as exc:
        notification_service.close()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        notification_service.close()
        raise HTTPException(status_code=500, detail="payment webhook processing failed") from exc
    finally:
        notification_service.close()

    return {
        "status": "ok",
        "event_id": result.event_id,
        "event": result.event_name,
        "duplicate": result.duplicate,
        "processed": result.processed,
        "transaction_id": result.transaction.transaction_id if result.transaction else None,
    }
