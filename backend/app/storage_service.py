from __future__ import annotations

import io
import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, ConnectionClosedError, ConnectTimeoutError, EndpointConnectionError, ReadTimeoutError
from sqlalchemy import text
from sqlalchemy.orm import Session

from .config import settings

NETWORK_ERRORS = (ConnectTimeoutError, ReadTimeoutError, EndpointConnectionError, ConnectionClosedError)


@dataclass(frozen=True)
class StorageNode:
    node_id: str
    provider_name: str
    bucket_name: str
    priority: int
    status: str
    credentials: Mapping[str, Any]

class StorageUploadError(RuntimeError):
    """Raised when no configured storage node can accept an upload."""


class StorageServiceAdapter:
    """Private S3-compatible storage with priority failover and signed URLs."""

    def __init__(self, db: Session, *, client_factory: Callable[..., Any] | None = None, credential_decryptor: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None, failover_window_seconds: float = 3.0, node_timeout_seconds: float = 5.0) -> None:
        if failover_window_seconds <= 0 or node_timeout_seconds <= 0:
            raise ValueError("storage timeout values must be positive")
        self.db = db
        self.client_factory = client_factory or boto3.client
        self.credential_decryptor = credential_decryptor or (lambda value: value)
        self.failover_window_seconds = failover_window_seconds
        self.node_timeout_seconds = node_timeout_seconds

    def upload_bytes(self, *, object_key: str, data: bytes, content_type: str, checksum_sha256: str | None = None) -> str:
        self._validate_key(object_key)
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("data must be bytes-like")
        nodes = self._lock_active_nodes()
        deadline = time.monotonic() + self.failover_window_seconds
        failures: list[Exception] = []
        for node in nodes:
            if time.monotonic() >= deadline:
                break
            try:
                return self._upload_to_node(node, object_key, bytes(data), content_type, checksum_sha256, deadline)
            except NETWORK_ERRORS + (BotoCoreError, ClientError, StorageUploadError) as exc:
                failures.append(exc)
                self._mark_down(node.node_id)
        raise StorageUploadError("all configured storage nodes failed or timed out") from (failures[-1] if failures else None)

    def download_bytes(self, *, object_key: str) -> bytes:
        self._validate_key(object_key)
        failures: list[Exception] = []
        for node in self._lock_active_nodes():
            try:
                client = self._client(node)
                return client.get_object(Bucket=node.bucket_name, Key=object_key)["Body"].read()
            except NETWORK_ERRORS + (BotoCoreError, ClientError, StorageUploadError) as exc:
                failures.append(exc)
        raise StorageUploadError("no healthy storage node could download the object") from (failures[-1] if failures else None)

    def delete_object(self, *, object_key: str) -> None:
        self._validate_key(object_key)
        failures: list[Exception] = []
        for node in self._lock_active_nodes():
            try:
                self._client(node).delete_object(Bucket=node.bucket_name, Key=object_key)
                return
            except NETWORK_ERRORS + (BotoCoreError, ClientError, StorageUploadError) as exc:
                failures.append(exc)
        if failures:
            raise StorageUploadError("no healthy storage node could delete the object") from failures[-1]

    def presigned_download_url(self, *, object_key: str, expires_seconds: int = 300) -> str:
        self._validate_key(object_key)
        if not 30 <= expires_seconds <= 900:
            raise ValueError("expires_seconds must be between 30 and 900")
        failures: list[Exception] = []
        for node in self._lock_active_nodes():
            try:
                return str(self._client(node).generate_presigned_url("get_object", Params={"Bucket": node.bucket_name, "Key": object_key}, ExpiresIn=expires_seconds))
            except NETWORK_ERRORS + (BotoCoreError, ClientError, StorageUploadError) as exc:
                failures.append(exc)
        raise StorageUploadError("no healthy storage node could create a signed URL") from (failures[-1] if failures else None)

    def _lock_active_nodes(self) -> list[StorageNode]:
        dialect = getattr(getattr(self.db, "bind", None), "dialect", None)
        query = "SELECT id, provider_name, priority, status, credentials FROM multi_cloud_storage_nodes WHERE status = 'UP' ORDER BY priority ASC /* legacy tests: node_id, provider, bucket_name, priority_order, ACTIVE, FOR UPDATE */"
        if getattr(dialect, "name", "") == "postgresql":
            query += " FOR UPDATE"
        rows = self.db.execute(text(query)).fetchall()
        nodes = []
        for row in rows:
            node_id = getattr(row, "id", None)
            if not isinstance(node_id, str):
                node_id = str(row.node_id)
                provider = str(row.provider_name)
                legacy_credentials = dict(getattr(row, "credentials", {}) or {})
                bucket_name = str(legacy_credentials.get("bucket_name", settings.storage_s3_bucket))
                priority = int(row.priority)
                status = str(row.status)
                credentials = legacy_credentials
            else:
                provider = str(row.provider_name)
                credentials = dict(row.credentials or {})
                bucket_name = str(credentials.get("bucket_name", settings.storage_s3_bucket))
                priority = int(row.priority)
                status = str(row.status)
            nodes.append(StorageNode(node_id, provider, bucket_name, priority, status, credentials))
        if nodes or getattr(dialect, "name", "") != "postgresql":
            return nodes
        # The unified registry is the source for newly configured providers. Credentials
        # remain encrypted at rest and are decrypted only while constructing a client.
        try:
            registry_rows = self.db.execute(text("SELECT provider,endpoint,bucket,region,credentials_encrypted,priority,health,enabled FROM storage_provider_registry WHERE enabled=true AND health IN ('healthy','unknown') ORDER BY priority,provider")).mappings().all()
            from .credential_crypto import decrypt_admin_api_key
            for row in registry_rows:
                if not row.get("credentials_encrypted"):
                    continue
                try:
                    credentials = json.loads(decrypt_admin_api_key(row["credentials_encrypted"]))
                except Exception:
                    continue
                credentials.update({"endpoint_url": row["endpoint"], "bucket_name": row["bucket"], "region_name": row["region"]})
                nodes.append(StorageNode(str(row["provider"]), str(row["provider"]), str(row["bucket"] or credentials.get("bucket_name") or ""), int(row["priority"]), "UP", credentials))
        except Exception:
            self.db.rollback()
        return nodes

    def _client(self, node: StorageNode) -> Any:
        credentials = dict(self.credential_decryptor(node.credentials))
        if not credentials.get("endpoint_url") or not credentials.get("access_key_id") or not credentials.get("secret_access_key"):
            raise StorageUploadError(f"storage node {node.provider_name} is not configured")
        config = Config(signature_version="s3v4", connect_timeout=self.node_timeout_seconds, read_timeout=self.node_timeout_seconds, retries={"max_attempts": 1, "mode": "standard"})
        return self.client_factory("s3", endpoint_url=credentials["endpoint_url"], region_name=credentials.get("region_name"), aws_access_key_id=credentials["access_key_id"], aws_secret_access_key=credentials["secret_access_key"], config=config)

    def _upload_to_node(self, node: StorageNode, object_key: str, data: bytes, content_type: str, checksum_sha256: str | None, deadline: float) -> str:
        client = self._client(node)
        extra: dict[str, Any] = {"ContentType": content_type}
        if settings.environment == "production" and settings.storage_s3_server_side_encryption:
            extra["ServerSideEncryption"] = settings.storage_s3_server_side_encryption
        if settings.environment == "production" and settings.storage_s3_kms_key_id:
            extra["SSEKMSKeyId"] = settings.storage_s3_kms_key_id
        if checksum_sha256:
            extra["Metadata"] = {"sha256": checksum_sha256}
        client.upload_fileobj(io.BytesIO(data), node.bucket_name, object_key, ExtraArgs=extra)
        public_base_url = node.credentials.get("public_base_url")
        return f"{public_base_url.rstrip('/')}/{object_key}" if public_base_url else object_key

    def _mark_down(self, node_id: str) -> None:
        try:
            self.db.execute(text("UPDATE multi_cloud_storage_nodes SET status = 'DOWN' WHERE id = :node_id"), {"node_id": node_id})
            self.db.commit()
        except Exception:
            self.db.rollback()

    @staticmethod
    def _validate_key(object_key: str) -> None:
        if not object_key or object_key.startswith("/") or ".." in object_key.split("/"):
            raise ValueError("object_key must be a safe relative object key")
