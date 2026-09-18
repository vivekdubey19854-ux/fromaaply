from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import jwt
from cryptography.fernet import Fernet
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.admin_routes import AdminContext, require_system_admin
from app.credential_crypto import decrypt_admin_api_key
from app.database import get_db
from app.main import app
from app.config import settings


@dataclass
class FakeResult:
    value: Any = None

    def first(self):
        return self.value

    def scalar(self):
        return self.value


class FakeDB:
    def __init__(self, existing_provider: bool = False):
        self.existing_provider = existing_provider
        self.executed: list[tuple[str, dict[str, Any]]] = []
        self.committed = False
        self.rolled_back = False

    @contextmanager
    def begin(self):
        yield self
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def execute(self, statement, params=None):
        sql = str(statement)
        self.executed.append((sql, params or {}))
        if "select provider_name from admin_api_keys" in sql:
            return FakeResult(("openai",) if self.existing_provider else None)
        if "returning coupon_id" in sql:
            return FakeResult("coupon-test-id")
        return FakeResult(None)


def make_token(user_id: str) -> str:
    return jwt.encode(
        {"sub": user_id, "exp": 4102444800, "app_role": "system_admin"},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def override_standard_user():
    raise HTTPException(status_code=403, detail="system admin privileges required")


def override_system_admin():
    return AdminContext("admin-user-001")


def test_standard_user_is_rejected_for_openai_key_update():
    db = FakeDB()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_system_admin] = override_standard_user
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/admin/keys/update",
                json={"provider_name": "openai", "api_key": "sk-standard-user-must-fail"},
                headers={"Authorization": "Bearer invalid-user-token"},
            )
        assert response.status_code == 403
        assert db.executed == []
    finally:
        app.dependency_overrides.clear()


def test_standard_user_is_rejected_for_gemini_key_update():
    db = FakeDB()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_system_admin] = override_standard_user
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/admin/keys/update",
                json={"provider_name": "gemini", "api_key": "AIza-standard-user-must-fail"},
                headers={"Authorization": "Bearer invalid-user-token"},
            )
        assert response.status_code == 403
        assert db.executed == []
    finally:
        app.dependency_overrides.clear()


def test_system_admin_encrypts_and_updates_provider_key(monkeypatch):
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("FORMWISE_CREDENTIAL_ENCRYPTION_KEY", key)

    db = FakeDB(existing_provider=False)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_system_admin] = override_system_admin
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/admin/keys/update",
                json={"provider_name": "openai", "api_key": "sk-real-secret-test"},
                headers={"Authorization": f"Bearer {make_token('admin-user-001')}"},
            )

        assert response.status_code == 200
        assert response.json() == {"status": "updated", "provider_name": "openai"}
        insert_calls = [params for sql, params in db.executed if "insert into admin_api_keys" in sql]
        assert len(insert_calls) == 1
        ciphertext = insert_calls[0]["ciphertext"]
        assert ciphertext != "sk-real-secret-test"
        assert decrypt_admin_api_key(ciphertext) == "sk-real-secret-test"
        assert db.committed is True
        assert any("ADMIN_API_KEY_UPDATED" in params.get("action", "") for _, params in db.executed if params)
    finally:
        app.dependency_overrides.clear()


def test_system_admin_updates_existing_provider_key(monkeypatch):
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("FORMWISE_CREDENTIAL_ENCRYPTION_KEY", key)

    db = FakeDB(existing_provider=True)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_system_admin] = override_system_admin
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/admin/keys/update",
                json={"provider_name": "openai", "api_key": "sk-rotated-secret-test"},
                headers={"Authorization": f"Bearer {make_token('admin-user-001')}"},
            )

        assert response.status_code == 200
        update_calls = [params for sql, params in db.executed if "update admin_api_keys" in sql]
        assert len(update_calls) == 1
        assert decrypt_admin_api_key(update_calls[0]["ciphertext"]) == "sk-rotated-secret-test"
        assert db.committed is True
    finally:
        app.dependency_overrides.clear()


def test_system_admin_pricing_config_is_transactional():
    db = FakeDB()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[require_system_admin] = override_system_admin
    try:
        with TestClient(app) as client:
            response = client.post(
                "/v1/admin/pricing/config",
                json={
                    "credits_per_currency_unit": "10",
                    "default_form_fill_cost_credits": "2.5",
                    "currency_credit_ratios": {"INR": "1", "USD": "83.2"},
                },
                headers={"Authorization": f"Bearer {make_token('admin-user-001')}"},
            )
        assert response.status_code == 200
        assert db.committed is True
        assert any("ADMIN_PRICING_CONFIG_UPDATED" in params.get("action", "") for _, params in db.executed if params)
    finally:
        app.dependency_overrides.clear()
