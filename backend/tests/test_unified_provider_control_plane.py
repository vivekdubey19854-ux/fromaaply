from unittest.mock import MagicMock, Mock

from app.ai_provider_adapter import AIRequest, MultiAIProviderAdapter, PROVIDER_CATALOG


def test_catalog_supports_more_than_twenty_extensible_providers():
    names = {item["provider"] for item in PROVIDER_CATALOG}
    assert len(names) >= 20
    assert {"gemini", "omniroute", "deepseek", "xai", "qwen", "moonshot", "sambanova"}.issubset(names)


def test_generic_provider_uses_openai_compatible_dispatch(monkeypatch):
    db = Mock()
    db.bind.dialect.name = "postgresql"
    db.execute.return_value.mappings.return_value.first.return_value = {"provider_name": "deepinfra", "api_key_encrypted": "secret", "is_active": True}
    adapter = MultiAIProviderAdapter(db, credential_decryptor=lambda value: {"api_key": value, "base_url": "https://provider.example/v1"})
    response = Mock()
    response.json.return_value = {"choices": [{"message": {"content": "ok"}}], "usage": {"total_tokens": 2}}
    response.raise_for_status.return_value = None
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.post.return_value = response
    monkeypatch.setattr(adapter, "_http_client_factory", lambda **kwargs: client)
    result = adapter.execute(AIRequest(task="general", model="model", messages=[{"role": "user", "content": "hello"}], provider_route=("deepinfra",)))
    assert result.provider == "deepinfra"
    client.post.assert_called_once()


def test_provider_secret_is_never_returned_by_admin_contract():
    # The admin API returns only configured/masked metadata; encrypted values are never
    # represented by the provider catalog contract.
    assert "api_key" not in {key for item in PROVIDER_CATALOG for key in item}
