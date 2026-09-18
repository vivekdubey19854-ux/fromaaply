from __future__ import annotations

import time
from unittest.mock import Mock

import pytest

from app.ai_provider_adapter import (
    AIRequest,
    AIProviderExhausted,
    MultiAIProviderAdapter,
)


class FakeResult:
    def __init__(self, text: str):
        self.output_text = text
        self.usage = {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}


def _adapter(rows, *, routes=None, decryptor=None, audit=None, budget=1.8):
    db = Mock()
    db.bind.dialect.name = "postgresql"
    db.execute.return_value.mappings.return_value.first.side_effect = rows
    audit_sink = audit.append if audit is not None else (lambda event: None)
    return MultiAIProviderAdapter(
        db,
        credential_decryptor=decryptor or (lambda value: value),
        routes=routes or {"vision_form_reading": ("openai", "gemini")},
        audit_sink=audit_sink,
        failover_budget_seconds=budget,
    ), db


def _request():
    return AIRequest(
        task="vision_form_reading",
        model="gpt-4o",
        messages=[{"role": "user", "content": "Read the form fields and return JSON."}],
        provider_route=("openai", "gemini"),
        timeout_seconds=0.5,
    )


def test_429_on_openai_falls_back_to_gemini_and_returns_form_tokens(monkeypatch):
    rows = [
        {"provider_name": "openai", "api_key_encrypted": "enc-openai", "is_active": True},
        {"provider_name": "gemini", "api_key_encrypted": "enc-gemini", "is_active": True},
    ]
    audit = []
    adapter, db = _adapter(rows, audit=audit)

    class RateLimitError(Exception):
        pass

    openai_client = Mock()
    openai_client.responses.create.side_effect = RateLimitError("429")
    gemini_response = Mock(text='{"form_tokens":{"full_name":{"value":"A"},"email":{"value":"a@example.com"}}}')
    gemini_client = Mock()
    gemini_client.models.generate_content.return_value = gemini_response

    monkeypatch.setattr("openai.OpenAI", Mock(return_value=openai_client), raising=False)
    monkeypatch.setattr("google.genai.Client", Mock(return_value=gemini_client), raising=False)

    result = adapter.execute(_request())

    assert result.provider == "gemini"
    assert result.form_tokens == {
        "full_name": {"value": "A"},
        "email": {"value": "a@example.com"},
    }
    openai_client.responses.create.assert_called_once()
    gemini_client.models.generate_content.assert_called_once()
    assert any(event["event"] == "provider.failure" and event["provider"] == "openai" for event in audit)
    assert any(event["event"] == "provider.success" and event["provider"] == "gemini" for event in audit)
    assert db.execute.call_count == 2
    assert "FOR UPDATE" in str(db.execute.call_args_list[0].args[0])


def test_decrypted_credentials_are_only_used_at_client_initialization(monkeypatch):
    rows = [{"provider_name": "openai", "api_key_encrypted": "ciphertext", "is_active": True}]
    calls = []
    db = Mock()
    db.bind.dialect.name = "postgresql"
    db.execute.return_value.mappings.return_value.first.return_value = rows[0]

    def decrypt(value):
        calls.append(value)
        return "plain-secret"

    fake = Mock()
    fake.responses.create.return_value = FakeResult('{"form_tokens":{}}')
    openai_ctor = Mock(return_value=fake)
    monkeypatch.setattr("openai.OpenAI", openai_ctor, raising=False)

    adapter = MultiAIProviderAdapter(db, credential_decryptor=decrypt)
    result = adapter.execute(AIRequest(task="general", model="gpt-4o", messages=[{"role": "user", "content": "x"}], provider_route=("openai",)))

    assert result.provider == "openai"
    assert calls == ["ciphertext"]
    assert openai_ctor.call_args.kwargs["api_key"] == "plain-secret"


def test_all_transient_failures_raise_exhausted_and_emit_audit(monkeypatch):
    rows = [
        {"provider_name": "openai", "api_key_encrypted": "a", "is_active": True},
        {"provider_name": "gemini", "api_key_encrypted": "b", "is_active": True},
    ]
    audit = []
    adapter, _ = _adapter(rows, audit=audit)

    openai_client = Mock()
    gemini_client = Mock()
    timeout_error = TimeoutError("network timeout")
    openai_client.responses.create.side_effect = timeout_error
    gemini_client.models.generate_content.side_effect = timeout_error
    monkeypatch.setattr("openai.OpenAI", Mock(return_value=openai_client), raising=False)
    monkeypatch.setattr("google.genai.Client", Mock(return_value=gemini_client), raising=False)

    started = time.monotonic()
    with pytest.raises(AIProviderExhausted):
        adapter.execute(_request())
    assert time.monotonic() - started < 2.0
    assert [event["provider"] for event in audit if event["event"] == "provider.failure"] == ["openai", "gemini"]


def test_never_exposes_dom_or_submission_capabilities():
    adapter, _ = _adapter([{"provider_name": "openai", "api_key_encrypted": "a", "is_active": True}])
    forbidden = {"click", "submit", "evaluate", "goto", "dom", "page"}
    assert forbidden.isdisjoint(set(dir(adapter)))
