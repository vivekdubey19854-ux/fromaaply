from __future__ import annotations

import io
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, ConnectionClosedError, ConnectTimeoutError, EndpointConnectionError, ReadTimeoutError
from sqlalchemy import text
from sqlalchemy.orm import Session

NETWORK_ERRORS = (ConnectTimeoutError, ReadTimeoutError, EndpointConnectionError, ConnectionClosedError)

@dataclass(frozen=True)
class StorageNode:
    node_id: str
    provider_name: str
    priority: int
    status: str
    credentials: Mapping[str, Any]

class StorageUploadError(RuntimeError):
    """Raised when no configured storage node can accept an upload."""

class StorageServiceAdapter:
    """Upload to the highest-priority healthy S3-compatible node with failover."""
    def __init__(self, db: Session, *, client_factory: Callable[..., Any] | None = None, credential_decryptor: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None, failover_window_seconds: float = 3.0, node_timeout_seconds: float = 1.0) -> None:
        if failover_window_seconds <= 0 or node_timeout_seconds <= 0:
            raise ValueError("storage timeout values must be positive")
        self.db = db
        self.client_factory = client_factory or boto3.client
        self.credential_decryptor = credential_decryptor or (lambda value: value)
        self.failover_window_seconds = failover_window_seconds
        self.node_timeout_seconds = node_timeout_seconds

    def upload_bytes(self, *, object_key: str, data: bytes, content_type: str) -> str:
        if not object_key or object_key.startswith("/"):
            raise ValueError("object_key must be a relative object key")
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("data must be bytes-like")
        nodes = self._lock_active_nodes()
        deadline = time.monotonic() + self.failover_window_seconds
        failures: list[Exception] = []
        for node in nodes:
            if time.monotonic() >= deadline:
                break
            try:
                return self._upload_to_node(node, object_key, bytes(data), content_type, deadline)
            except NETWORK_ERRORS as exc:
                failures.append(exc)
                self._mark_down(node.node_id)
            except ClientError as exc:
                failures.append(exc)
                if self._is_transient_provider_error(exc):
                    self._mark_down(node.node_id)
                else:
                    raise StorageUploadError(f"storage provider rejected upload: {node.provider_name}") from exc
            except BotoCoreError as exc:
                failures.append(exc)
                self._mark_down(node.node_id)
        raise StorageUploadError("all configured storage nodes failed or timed out") from (failures[-1] if failures else None)

    def presigned_download_url(self, *, object_key: str, expires_seconds: int = 300) -> str:
        """Return a short-lived private URL; never construct a permanent public URL."""
        if not object_key or object_key.startswith("/"):
            raise ValueError("object_key must be a relative object key")
        if not 30 <= expires_seconds <= 900:
            raise ValueError("expires_seconds must be between 30 and 900")
        nodes = self._lock_active_nodes()
        if not nodes:
            raise StorageUploadError("no healthy storage node is configured")
        failures: list[Exception] = []
        for node in nodes:
            try:
                credentials = dict(self.credential_decryptor(node.credentials))
                required = ("endpoint_url", "bucket_name", "access_key_id", "secret_access_key")
                missing = [key for key in required if not credentials.get(key)]
                if missing:
                    raise StorageUploadError(f"storage node {node.provider_name} is not configured: {', '.join(missing)}")
                client = self.client_factory("s3", endpoint_url=credentials["endpoint_url"], region_name=credentials.get("region_name"), aws_access_key_id=credentials["access_key_id"], aws_secret_access_key=credentials["secret_access_key"], config=Config(signature_version="s3v4"))
                return str(client.generate_presigned_url("get_object", Params={"Bucket": credentials["bucket_name"], "Key": object_key}, ExpiresIn=expires_seconds))
            except NETWORK_ERRORS as exc:
                failures.append(exc)
            except (BotoCoreError, ClientError) as exc:
                failures.append(exc)
        raise StorageUploadError("no healthy storage node could create a signed URL") from (failures[-1] if failures else None)

    def _lock_active_nodes(self) -> list[StorageNode]:
        result = self.db.execute(text("SELECT id, provider_name, priority, status, credentials FROM multi_cloud_storage_nodes WHERE status = 'UP' ORDER BY priority ASC FOR UPDATE"))
        return [StorageNode(str(row.id), str(row.provider_name), int(row.priority), str(row.status), row.credentials or {}) for row in result.fetchall()]

    def _upload_to_node(self, node: StorageNode, object_key: str, data: bytes, content_type: str, deadline: float) -> str:
        credentials = dict(self.credential_decryptor(node.credentials))
        required = ("endpoint_url", "bucket_name", "access_key_id", "secret_access_key")
        missing = [key for key in required if not credentials.get(key)]
        if missing:
            raise StorageUploadError(f"storage node {node.provider_name} is not configured: {', '.join(missing)}")
        remaining = min(self.node_timeout_seconds, max(0.1, deadline - time.monotonic()))
        client = self.client_factory("s3", endpoint_url=credentials["endpoint_url"], region_name=credentials.get("region_name"), aws_access_key_id=credentials["access_key_id"], aws_secret_access_key=credentials["secret_access_key"], config=Config(connect_timeout=remaining, read_timeout=remaining, retries={"max_attempts": 1, "mode": "standard"}))
        client.upload_fileobj(io.BytesIO(data), credentials["bucket_name"], object_key, ExtraArgs={"ContentType": content_type})
        base_url = credentials.get("public_base_url") or f"{credentials['endpoint_url'].rstrip('/')}/{credentials['bucket_name']}"
        return f"{base_url.rstrip('/')}/{object_key.lstrip('/')}"

    def _mark_down(self, node_id: str) -> None:
        try:
            self.db.execute(text("UPDATE multi_cloud_storage_nodes SET status = 'DOWN' WHERE id = :node_id"), {"node_id": node_id})
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    @staticmethod
    def _is_transient_provider_error(exc: ClientError) -> bool:
        status = (exc.response or {}).get("ResponseMetadata", {}).get("HTTPStatusCode")
        return status is None or int(status) >= 500
