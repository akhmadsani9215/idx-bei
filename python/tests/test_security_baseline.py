"""Cluster 13 — operator authorization, rate limiting, security headers."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from idx.api import app
from idx.security import LIMITER, SlidingWindowLimiter, security_status


@pytest.fixture
def client(monkeypatch):
    for var in (
        "RITELINSIGHT_ENV",
        "RITELINSIGHT_ADMIN_TOKEN",
        "RITELINSIGHT_RATE_LIMIT_ENABLED",
        "RITELINSIGHT_RATE_LIMIT_PER_MIN",
        "RITELINSIGHT_RATE_LIMIT_HEAVY_PER_MIN",
    ):
        monkeypatch.delenv(var, raising=False)
    LIMITER.reset()
    yield TestClient(app)
    LIMITER.reset()


def test_security_headers_present(client):
    r = client.get("/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "Strict-Transport-Security" not in r.headers  # dev: TLS not asserted


def test_hsts_only_in_production(client, monkeypatch):
    monkeypatch.setenv("RITELINSIGHT_ENV", "production")
    monkeypatch.setenv("RITELINSIGHT_RATE_LIMIT_ENABLED", "0")
    assert "Strict-Transport-Security" in client.get("/health").headers


def test_broadcast_requires_operator_token_when_configured(client, monkeypatch):
    monkeypatch.setenv("RITELINSIGHT_ADMIN_TOKEN", "s3cret-test-token")
    assert client.post("/api/broadcast", json={"type": "x"}).status_code == 401
    bad = client.post("/api/broadcast", json={"type": "x"}, headers={"X-Ritel-Admin-Token": "nope"})
    assert bad.status_code == 401
    ok = client.post(
        "/api/broadcast", json={"type": "x"}, headers={"X-Ritel-Admin-Token": "s3cret-test-token"}
    )
    assert ok.status_code == 200


def test_operator_routes_fail_closed_in_production_without_token(client, monkeypatch):
    monkeypatch.setenv("RITELINSIGHT_ENV", "production")
    monkeypatch.setenv("RITELINSIGHT_RATE_LIMIT_ENABLED", "0")
    r = client.post("/api/system/trigger-ingestion", json={"job_type": "daily"})
    assert r.status_code == 503
    assert "NOT_CONFIGURED" in r.json()["detail"]


def test_rate_limit_returns_429_with_retry_after(client, monkeypatch):
    monkeypatch.setenv("RITELINSIGHT_RATE_LIMIT_ENABLED", "1")
    monkeypatch.setenv("RITELINSIGHT_RATE_LIMIT_PER_MIN", "3")
    codes = [client.get("/api/schema").status_code for _ in range(4)]
    assert codes[:3] == [200, 200, 200]
    assert codes[3] == 429
    limited = client.get("/api/schema")
    assert int(limited.headers["Retry-After"]) >= 1
    assert client.get("/health").status_code == 200  # exempt


def test_limiter_window_unit():
    lim = SlidingWindowLimiter()
    assert lim.hit("k", 2) is None
    assert lim.hit("k", 2) is None
    assert lim.hit("k", 2) is not None
    assert lim.hit("other", 2) is None


def test_security_status_is_honest(monkeypatch):
    monkeypatch.delenv("RITELINSIGHT_ADMIN_TOKEN", raising=False)
    st = security_status()
    assert st["operator_token"] == "NOT_CONFIGURED"
    assert st["idp"].startswith("NOT_CONFIGURED")
    assert st["tls"].startswith("EXTERNAL")
