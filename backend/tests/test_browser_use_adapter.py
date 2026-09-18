import pytest

import app.browser_use_agent as browser_use_agent
from app.browser_use_agent import BrowserUseUnavailable, run_browser_use_task
from app.verified_data_service import VerifiedDataResult, VerifiedDataStatus


@pytest.mark.asyncio
async def test_browser_use_adapter_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("FORMWISE_BROWSER_USE_ENABLED", raising=False)
    with pytest.raises(BrowserUseUnavailable):
        await run_browser_use_task("inspect the form", allowed_url="https://example.com/form")


@pytest.mark.asyncio
async def test_browser_use_adapter_requires_url(monkeypatch):
    monkeypatch.setenv("FORMWISE_BROWSER_USE_ENABLED", "true")
    with pytest.raises(ValueError):
        await run_browser_use_task("inspect the form")


@pytest.mark.asyncio
async def test_browser_use_requests_only_the_explicit_field(monkeypatch):
    monkeypatch.delenv("FORMWISE_BROWSER_USE_ENABLED", raising=False)
    calls: list[tuple[str, str, str | None]] = []

    async def fake_request_verified_field(user_id: str, field_key: str, *, session_id: str | None = None):
        calls.append((user_id, field_key, session_id))
        return VerifiedDataResult(VerifiedDataStatus.VERIFIED, field_key, "Demo User", source="profiles")

    monkeypatch.setattr(browser_use_agent, "request_verified_field", fake_request_verified_field)
    with pytest.raises(BrowserUseUnavailable):
        await run_browser_use_task(
            "inspect the form",
            allowed_url="https://example.com/form",
            user_id="u1",
            session_id="s1",
            requested_field="full_name",
        )

    assert calls == [("u1", "full_name", "s1")]
