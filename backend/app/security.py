from __future__ import annotations

import hashlib
import ipaddress
from pathlib import Path
from urllib.parse import urlparse

from app.config import settings

ALLOWED_CONTENT_TYPES = {"application/pdf": {".pdf"}, "image/jpeg": {".jpg", ".jpeg"}, "image/png": {".png"}, "image/webp": {".webp"}}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_upload(filename: str, content_type: str, size_bytes: int, max_size: int) -> None:
    if not filename or Path(filename).name != filename:
        raise ValueError("invalid filename")
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise ValueError("unsupported document type")
    if Path(filename).suffix.lower() not in ALLOWED_CONTENT_TYPES[content_type]:
        raise ValueError("file extension does not match content type")
    if size_bytes <= 0 or size_bytes > max_size:
        raise ValueError("document size is outside the allowed range")


def validate_target_url(url: str, *, allowed_domains: set[str] | None = None) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("target URL must use HTTP(S) and include a hostname")
    host = parsed.hostname.lower().rstrip(".")
    if allowed_domains and host not in {domain.lower().rstrip(".") for domain in allowed_domains}:
        raise ValueError("target domain is not approved")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if settings.browser_block_private_networks and address and (address.is_private or address.is_loopback or address.is_link_local or address.is_reserved):
        if not (settings.environment != "production" and settings.browser_allow_local_demo_target and host in {"127.0.0.1", "localhost"}):
            raise ValueError("private network targets are blocked")


def validate_production_security() -> None:
    if settings.environment == "production":
        if settings.jwt_secret == "change-me-in-production" or len(settings.jwt_secret) < 32:
            raise RuntimeError("FORMWISE_JWT_SECRET must be a strong secret of at least 32 characters")
        if settings.allow_legacy_user_header:
            raise RuntimeError("legacy X-User-ID authentication must be disabled in production")
        if settings.database_url.startswith("sqlite"):
            raise RuntimeError("production requires PostgreSQL; SQLite is development/test only")
        if settings.storage_provider != "s3":
            raise RuntimeError("production requires private S3-compatible object storage")
        if not settings.redis_url.startswith(("rediss://", "redis://")):
            raise RuntimeError("production Redis URL is invalid")
        if not settings.redis_tls and settings.redis_url.startswith("redis://"):
            raise RuntimeError("production Redis must use TLS (rediss:// or FORMWISE_REDIS_TLS=true)")
        if not settings.cors_origins or "*" in settings.cors_origins:
            raise RuntimeError("production CORS must be an explicit allow-list")
        if not settings.secure_cookies:
            raise RuntimeError("production secure cookies must be enabled")
        if settings.browser_allow_local_demo_target:
            raise RuntimeError("local browser demo target must be disabled in production")
