import jwt
import pytest

from app.auth import hash_password, issue_access_token, require_user_id, verify_password
from app.config import settings


def test_password_hash_is_salted_and_verifiable():
    first = hash_password("correct horse battery staple")
    second = hash_password("correct horse battery staple")
    assert first != second
    assert verify_password("correct horse battery staple", first)
    assert not verify_password("wrong password", first)


def test_password_policy_rejects_short_passwords():
    with pytest.raises(ValueError):
        hash_password("too-short")


def test_access_token_contains_user_subject_and_role():
    token = issue_access_token("user-123")
    claims = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    assert claims["sub"] == "user-123"
    assert claims["role"] == "user"


def test_refresh_role_cannot_authenticate_as_user(monkeypatch):
    from app.auth import issue_refresh_token
    token = issue_refresh_token("user-123")
    with pytest.raises(Exception):
        require_user_id(f"Bearer {token}")
