from types import SimpleNamespace
from unittest.mock import Mock

from app.ai_provider_adapter import AIRequest, MultiAIProviderAdapter
from app.razorpay_gateway import RazorpayGatewayService
from app.website_health_service import WebsiteHealthService


def test_provider_policy_rejects_disabled_provider_before_network_call():
    db = Mock()
    db.execute.return_value.mappings.return_value.first.side_effect = [
        {"enabled": False, "daily_tokens": None, "monthly_tokens": None, "daily_cost": None, "monthly_cost": None, "requests_per_minute": None, "cooldown_seconds": 30}
    ]
    adapter = MultiAIProviderAdapter(db, credential_decryptor=lambda value: value)
    request = AIRequest(task="general", model="x", messages=[], provider_route=("openai",), metadata={"user_id": "u1"})
    assert adapter._provider_allowed("openai", request) is False


def test_razorpay_refund_uses_server_side_gateway_call():
    db = Mock()
    db.bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    db.execute.return_value.mappings.return_value.first.return_value = {"provider_name": "razorpay", "api_key_encrypted": "cipher", "is_active": True}
    client = Mock()
    client.payment.refund.return_value = {"id": "rfnd_123"}
    service = RazorpayGatewayService(db, credential_decryptor=lambda _: {"key_id": "id", "key_secret": "secret", "webhook_secret": "hook"}, client_factory=lambda auth: client)
    assert service.refund_payment(payment_id="pay_123", amount_in_paise=500) == "rfnd_123"
    client.payment.refund.assert_called_once()


def test_unverified_website_never_becomes_healthy_or_enabled():
    db = Mock()
    db.execute.return_value.mappings.return_value.first.return_value = {"website_id": "w1", "base_url": "https://example.com", "allowed_domains_json": '["example.com"]', "verified": False, "enabled": False, "failure_count": 0, "version": "1.0.0"}
    result = WebsiteHealthService(db).check("w1")
    assert result["status"] == "down"
    assert result["enabled"] is False
