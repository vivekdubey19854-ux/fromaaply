import pytest
from fastapi import HTTPException
from app.auth import issue_dev_token, require_user_id
from app.config import settings

def test_dev_legacy_header(monkeypatch):
    monkeypatch.setattr(settings,'environment','development'); monkeypatch.setattr(settings,'allow_legacy_user_header',True)
    assert require_user_id(None,'user-1')=='user-1'

def test_production_rejects_legacy_header(monkeypatch):
    monkeypatch.setattr(settings,'environment','production'); monkeypatch.setattr(settings,'allow_legacy_user_header',True)
    with pytest.raises(HTTPException): require_user_id(None,'user-1')

def test_jwt_subject(monkeypatch):
    monkeypatch.setattr(settings,'environment','development')
    assert require_user_id('Bearer '+issue_dev_token('user-42',60),None)=='user-42'

def test_expired_or_invalid_token_rejected(monkeypatch):
    monkeypatch.setattr(settings,'environment','development')
    with pytest.raises(HTTPException) as exc: require_user_id('Bearer not-a-token',None)
    assert exc.value.status_code==401
