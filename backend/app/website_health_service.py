from __future__ import annotations

import time
from datetime import datetime
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session


class WebsiteHealthService:
    def __init__(self, db: Session, *, timeout_seconds: float = 8.0) -> None:
        self.db = db
        self.timeout_seconds = timeout_seconds

    def check(self, website_id: str) -> dict[str, object]:
        row = self.db.execute(text("SELECT website_id, base_url, allowed_domains_json, verified, enabled, failure_count, version FROM website_registry WHERE website_id=:website_id FOR UPDATE"), {"website_id": website_id}).mappings().first()
        if not row:
            raise ValueError("website not found")
        parsed = urlparse(str(row["base_url"]))
        domains = set(__import__("json").loads(row["allowed_domains_json"] or "[]"))
        if parsed.scheme != "https" or not parsed.hostname or parsed.hostname.lower() not in domains or not row["verified"]:
            return self._record(row, "down", None, 0, "unverified or invalid official domain")
        started = time.monotonic()
        status = "healthy"
        http_status: int | None = None
        error: str | None = None
        try:
            response = httpx.get(str(row["base_url"]), timeout=self.timeout_seconds, follow_redirects=False, headers={"User-Agent": "Formwise-Registry-Health/1.0"})
            http_status = response.status_code
            if response.status_code >= 500:
                status = "down"
            elif response.status_code >= 400:
                status = "degraded"
        except httpx.HTTPError as exc:
            status, error = "down", type(exc).__name__
        return self._record(row, status, http_status, int((time.monotonic() - started) * 1000), error)

    def _record(self, row, status: str, http_status: int | None, latency_ms: int, error: str | None) -> dict[str, object]:
        failures = 0 if status == "healthy" else int(row["failure_count"] or 0) + 1
        enabled = bool(row["enabled"])
        # Safety policy: an unhealthy verified website is disabled only after three consecutive failures.
        if failures >= 3:
            enabled = False
        now = datetime.utcnow()
        self.db.execute(text("UPDATE website_registry SET health_status=:status, last_health_check=:now, failure_count=:failures, enabled=:enabled, updated_at=:now WHERE website_id=:website_id"), {"status": status, "now": now, "failures": failures, "enabled": enabled, "website_id": row["website_id"]})
        self.db.execute(text("INSERT INTO website_health_history(health_id,website_id,status,http_status,latency_ms,error_message,checked_at) VALUES (:id,:website_id,:status,:http_status,:latency,:error,:checked)"), {"id": str(uuid4()), "website_id": row["website_id"], "status": status, "http_status": http_status, "latency": latency_ms, "error": error, "checked": now})
        self.db.commit()
        return {"website_id": row["website_id"], "status": status, "enabled": enabled, "failure_count": failures, "latency_ms": latency_ms, "http_status": http_status}

    def check_all(self) -> list[dict[str, object]]:
        ids = [str(value) for value in self.db.execute(text("SELECT website_id FROM website_registry WHERE verified=true")).scalars().all()]
        return [self.check(website_id) for website_id in ids]
