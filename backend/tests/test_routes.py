from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app import routes
from app.storage import PrivateStorage


engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def override_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_profile_and_user_isolation(tmp_path: Path):
    Base.metadata.create_all(engine)
    app.dependency_overrides[get_db] = override_db
    routes.storage = PrivateStorage(str(tmp_path))
    client = TestClient(app)
    try:
        response = client.get("/v1/profile", headers={"X-User-ID": "user-a"})
        assert response.status_code == 200
        assert response.json()["user_id"] == "user-a"

        response = client.put(
            "/v1/profile",
            headers={"X-User-ID": "user-a"},
            json={"full_name": "User A", "email": "a@example.com"},
        )
        assert response.status_code == 200
        assert response.json()["full_name"] == "User A"

        response = client.get("/v1/profile", headers={"X-User-ID": "user-b"})
        assert response.status_code == 200
        assert response.json()["full_name"] is None
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_document_upload_download_and_idor_protection(tmp_path: Path):
    Base.metadata.create_all(engine)
    app.dependency_overrides[get_db] = override_db
    routes.storage = PrivateStorage(str(tmp_path))
    client = TestClient(app)
    try:
        upload = client.post(
            "/v1/documents",
            headers={"X-User-ID": "user-a"},
            files={"file": ("pan.pdf", b"private-document", "application/pdf")},
        )
        assert upload.status_code == 201
        document = upload.json()
        document_id = document["id"]
        assert document["original_filename"] == "pan.pdf"
        assert document["size_bytes"] == len(b"private-document")

        own_download = client.get(
            f"/v1/documents/{document_id}/download",
            headers={"X-User-ID": "user-a"},
        )
        assert own_download.status_code == 200
        assert own_download.content == b"private-document"

        foreign_download = client.get(
            f"/v1/documents/{document_id}/download",
            headers={"X-User-ID": "user-b"},
        )
        assert foreign_download.status_code == 404

        foreign_delete = client.delete(
            f"/v1/documents/{document_id}",
            headers={"X-User-ID": "user-b"},
        )
        assert foreign_delete.status_code == 404

        own_delete = client.delete(
            f"/v1/documents/{document_id}",
            headers={"X-User-ID": "user-a"},
        )
        assert own_delete.status_code == 200
        assert own_delete.json() == {"deleted": True}

        missing = client.get(
            f"/v1/documents/{document_id}/download",
            headers={"X-User-ID": "user-a"},
        )
        assert missing.status_code == 404
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
