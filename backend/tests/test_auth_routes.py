from fastapi.testclient import TestClient

from app.main import app


def test_dev_token_endpoint_returns_bearer_in_development():
    with TestClient(app) as client:
        response = client.post("/v1/auth/dev-token", json={"user_id": "demo-auth-user"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["token_type"] == "bearer"
        assert payload["access_token"]
