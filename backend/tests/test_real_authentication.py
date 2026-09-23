from datetime import datetime, timedelta
from unittest.mock import Mock

import jwt
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import auth_routes
from app.auth import issue_refresh_token
from app.auth_provider_service import InvalidProviderCredential, ProviderConfig, ProviderUnavailable, issue_session, rotate_session
from app.config import settings


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/v1/auth/provider/token", "headers": [] , "client": ("127.0.0.1", 1234), "scheme": "http", "server": ("testserver", 80)})


def test_provider_outage_falls_back_but_invalid_identity_does_not(monkeypatch):
    configs = [ProviderConfig("firebase", "Firebase", 1, True, ("token",), {}), ProviderConfig("supabase", "Supabase", 2, True, ("token",), {})]
    monkeypatch.setattr(auth_routes, "provider_configs", lambda db, method: configs)
    monkeypatch.setattr(auth_routes, "resolve_identity", lambda db, identity: "user-1")
    monkeypatch.setattr(auth_routes, "_session_response", lambda db, user_id, request: {"user_id": user_id, "access_token": "a", "refresh_token": "r"})
    verify = Mock(side_effect=[ProviderUnavailable("timeout"), {"provider": "supabase", "subject": "sub-1", "email": "u@example.com"}])
    monkeypatch.setattr(auth_routes, "verify_provider_token", verify)
    result = auth_routes.provider_token(auth_routes.ProviderTokenRequest(provider="auto", token="valid-provider-token"), _request(), Mock())
    assert result["user_id"] == "user-1"
    assert verify.call_count == 2

    verify.reset_mock(side_effect=True)
    verify.side_effect = InvalidProviderCredential("bad token")
    with pytest.raises(HTTPException) as exc:
        auth_routes.provider_token(auth_routes.ProviderTokenRequest(provider="auto", token="bad-provider-token-123456789"), _request(), Mock())
    assert exc.value.status_code == 401
    assert verify.call_count == 1


def test_account_linking_rejects_identity_owned_by_another_user(monkeypatch):
    config = ProviderConfig("clerk", "Clerk", 1, True, ("token",), {})
    monkeypatch.setattr(auth_routes, "provider_configs", lambda db, method: [config])
    monkeypatch.setattr(auth_routes, "verify_provider_token", lambda config, token: {"provider": "clerk", "subject": "external-1", "email": "other@example.com"})
    db = Mock()
    db.execute.return_value.scalar.return_value = "different-user"
    with pytest.raises(HTTPException) as exc:
        auth_routes.link_identity(auth_routes.LinkIdentityRequest(provider="clerk", token="valid-provider-token"), _request(), "current-user", db)
    assert exc.value.status_code == 409
    db.commit.assert_not_called()


def test_refresh_rotation_revokes_old_session(monkeypatch):
    db = Mock()
    db.execute.return_value.mappings.return_value.first.return_value = {
        "session_id": "session-1", "user_id": "user-1", "expires_at": datetime.utcnow() + timedelta(days=1), "revoked_at": None,
    }
    db.execute.return_value.scalar.return_value = None
    monkeypatch.setattr(settings, "jwt_secret", "a" * 48)
    refresh = issue_refresh_token("user-1")
    user_id, tokens = rotate_session(db, refresh)
    assert user_id == "user-1"
    assert tokens["refresh_token"] != refresh
    assert db.commit.call_count >= 1
    assert any("revoked_tokens" in str(call.args[0]) for call in db.execute.call_args_list)


def test_production_dev_token_is_disabled(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    with pytest.raises(HTTPException) as exc:
        auth_routes.dev_token(auth_routes.DevTokenRequest(user_id="user-1"))
    assert exc.value.status_code == 404
