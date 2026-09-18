import pytest
from app.universal_research import discover_target

@pytest.mark.asyncio
async def test_user_provided_url_becomes_verified_target_without_web_search():
    result=await discover_target("a private company application", "https://example.com/apply")
    assert result["status"]=="ready"
    assert result["application_form_url"]=="https://example.com/apply"
    assert result["verification_required"] is True

@pytest.mark.asyncio
async def test_unsafe_user_url_is_rejected():
    result=await discover_target("application", "javascript:alert(1)")
    assert result["needs_user_url"] is True

# Keep the universal path explicit: no site-specific domain is required when a user supplies a URL.
