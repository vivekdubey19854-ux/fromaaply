from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from .ai_provider_adapter import MultiAIProviderAdapter
from .auth import require_user_id
from .credential_crypto import decrypt_admin_api_key
from .database import get_db
from .notification_service import BrevoNotificationService
from .payment_webhook_service import RazorpayWebhookService, RazorpayWebhookError, RazorpayWebhookUnauthorized
from .payment_service import PaymentService
from .razorpay_gateway import RazorpayGatewayError, RazorpayGatewayService

router = APIRouter(prefix="/payments", tags=["payments"])


class CreatePaymentOrderRequest(BaseModel):
    amount_in_inr: Decimal = Field(gt=Decimal("0"), max_digits=12, decimal_places=2)


class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str = Field(min_length=5, max_length=100)
    razorpay_payment_id: str = Field(min_length=5, max_length=100)
    razorpay_signature: str = Field(min_length=20, max_length=256)
    amount_in_paise: int = Field(gt=0)


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


@router.post("/verify")
def verify_payment(body: VerifyPaymentRequest, db: Session = Depends(get_db), user_id: str = Depends(require_user_id)) -> dict[str, Any]:
    try:
        owner = db.execute(text("SELECT user_id FROM transactions WHERE razorpay_order_id = :order_id"), {"order_id": body.razorpay_order_id}).scalar()
        if str(owner) != user_id:
            raise HTTPException(status_code=403, detail="payment does not belong to this account")
        RazorpayGatewayService(db).verify_payment_signature(order_id=body.razorpay_order_id, payment_id=body.razorpay_payment_id, signature=body.razorpay_signature)
        result = PaymentService(db).process_order_paid(razorpay_order_id=body.razorpay_order_id, razorpay_payment_id=body.razorpay_payment_id, paid_amount_paise=body.amount_in_paise)
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="payment verification or settlement failed") from exc
    return {"status": result.status, "transaction_id": result.transaction_id, "credits_added": str(result.credits_added), "wallet_balance": str(result.wallet_balance_credits)}


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
