"""Production readiness / security regression tests (Agen 6)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from idx.auth_session import (
    clear_sessions_for_tests,
    create_session,
    invalidate_session,
    require_session,
    resolve_session,
    strip_client_identity_fields,
)
from idx.cors_config import resolve_cors_origins
from idx.providers import AIProvider, NotificationProvider, PaymentProvider
from idx.public_static import PUBLIC_DATA_FILES, resolve_public_data_path
from idx.ticker_safe import sanitize_ticker
from idx import watchlist_store as wl


@pytest.fixture
def client(tmp_path, monkeypatch):
    clear_sessions_for_tests()
    wl.reset_store_for_tests(str(tmp_path / "wl.json"))
    from idx.trading_plan import reset_store_for_tests

    reset_store_for_tests(str(tmp_path / "tj.json"))
    from idx.api import app

    return TestClient(app, raise_server_exceptions=False)


def test_sanitize_ticker_rejects_injection():
    assert sanitize_ticker("bbca") == "BBCA"
    with pytest.raises(ValueError):
        sanitize_ticker("BBCA'; DROP TABLE x;--")
    with pytest.raises(ValueError):
        sanitize_ticker("../etc/passwd")
    with pytest.raises(ValueError):
        sanitize_ticker("")


def test_public_data_allowlist_blocks_private_and_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr("idx.public_static.DATA_DIR", str(tmp_path))
    # private store name
    (tmp_path / ".ritelinsight_watchlists.json").write_text("{}", encoding="utf-8")
    assert resolve_public_data_path(".ritelinsight_watchlists.json") is None
    assert resolve_public_data_path("../secrets.txt") is None
    assert resolve_public_data_path("foo/bar.json") is None
    # allowlisted but missing
    assert "network_alpha_data.json" in PUBLIC_DATA_FILES
    assert resolve_public_data_path("network_alpha_data.json") is None
    # allowlisted present
    (tmp_path / "network_alpha_data.json").write_text('{"companies":[]}', encoding="utf-8")
    path = resolve_public_data_path("network_alpha_data.json")
    assert path is not None
    assert Path(path).name == "network_alpha_data.json"


def test_data_route_blocks_private_stores(client, tmp_path, monkeypatch):
    # Even if a private file somehow existed under DATA_DIR, route must 404.
    resp = client.get("/data/.ritelinsight_watchlists.json")
    assert resp.status_code == 404
    resp2 = client.get("/data/../python/src/idx/api.py")
    assert resp2.status_code in (404, 400)


def test_cors_dev_wildcard_disables_credentials():
    dev = resolve_cors_origins(env="development", origins_env=None)
    assert "*" in dev["allow_origins"]
    assert dev["allow_credentials"] is False
    prod = resolve_cors_origins(
        env="production", origins_env="https://app.ritelinsight.example"
    )
    assert prod["allow_credentials"] is True
    assert "*" not in prod["allow_origins"]


def test_session_expiry_and_logout(monkeypatch):
    clear_sessions_for_tests()
    monkeypatch.setenv("RITELINSIGHT_SESSION_TTL_SECONDS", "3600")
    created = create_session(label="t")
    sid = created["session_id"]
    assert require_session(sid).session_id == sid
    assert invalidate_session(sid) is True
    assert resolve_session(sid) is None
    with pytest.raises(PermissionError):
        require_session(sid)


def test_session_ttl_expires(monkeypatch):
    clear_sessions_for_tests()
    monkeypatch.setenv("RITELINSIGHT_SESSION_TTL_SECONDS", "1")
    created = create_session()
    sid = created["session_id"]
    # Force last_seen into the past via internal store
    import idx.auth_session as auth

    with auth._LOCK:
        auth._SESSIONS[sid]["last_seen"] = 0.0
        auth._SESSIONS[sid]["created_ts"] = 0.0
    assert resolve_session(sid) is None


def test_strip_client_identity_fields():
    cleaned = strip_client_identity_fields(
        {"ticker": "BBCA", "user_id": "attacker", "subject": "x", "notes": "ok"}
    )
    assert "user_id" not in cleaned
    assert "subject" not in cleaned
    assert cleaned["ticker"] == "BBCA"
    assert cleaned["notes"] == "ok"


def test_cross_session_watchlist_and_plan_isolation(client):
    s1 = client.post("/api/auth/session").json()["session_id"]
    s2 = client.post("/api/auth/session").json()["session_id"]
    assert (
        client.post(
            "/api/watchlist",
            json={"ticker": "ADRO", "user_id": "should-be-ignored"},
            headers={"X-Ritel-Session": s1},
        ).status_code
        == 200
    )
    listed_b = client.get("/api/watchlist", headers={"X-Ritel-Session": s2}).json()
    assert listed_b["count"] == 0
    assert client.get("/api/watchlist").status_code == 401
    assert client.get("/api/watchlist", headers={"X-Ritel-Session": "bogus"}).status_code == 401

    plan = client.post(
        "/api/trading-plan",
        json={"id": "p1", "tf_1d": "Bullish", "user_id": "evil"},
        headers={"X-Ritel-Session": s1},
    )
    assert plan.status_code == 200
    other = client.get("/api/trading-plan", headers={"X-Ritel-Session": s2}).json()
    assert other["plans"] == []

    j = client.post(
        "/api/journal",
        json={"id": "j1", "entry_price": 100, "exit_price": 110, "lots": 1, "user_id": "x"},
        headers={"X-Ritel-Session": s1},
    )
    assert j.status_code == 200
    other_j = client.get("/api/journal", headers={"X-Ritel-Session": s2}).json()
    assert other_j["journals"] == []


def test_logout_invalidates_token(client):
    s = client.post("/api/auth/session").json()["session_id"]
    assert client.get("/api/watchlist", headers={"X-Ritel-Session": s}).status_code == 200
    out = client.post("/api/auth/logout", headers={"X-Ritel-Session": s})
    assert out.status_code == 200
    assert out.json()["logged_out"] is True
    assert client.get("/api/watchlist", headers={"X-Ritel-Session": s}).status_code == 401


def test_invalid_ticker_returns_400(client):
    bad = client.get("/api/stock/BBCA%27%3BDROP%20TABLE%20x%3B--/broker")
    assert bad.status_code == 400


def test_payment_webhook_never_grants(client):
    resp = client.post(
        "/api/payment/webhook",
        content=b'{"paid":true,"user_id":"x"}',
        headers={"X-Signature": "forged"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] is False
    assert body["paid"] is False
    assert body["entitlement"] is None
    assert body["status"] == "NOT_CONFIGURED"


def test_ai_and_telegram_no_fake_success(client, monkeypatch):
    monkeypatch.delenv("RITELINSIGHT_AI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("RITELINSIGHT_TELEGRAM_BOT_TOKEN", raising=False)
    assert AIProvider().status().status == "NOT_CONFIGURED"
    gen = client.post("/api/ai/generate", json={"prompt": "hi"}).json()
    assert gen["is_ai_generated"] is False
    assert gen["text"] is None
    # Key present but adapter disabled
    monkeypatch.setenv("RITELINSIGHT_AI_API_KEY", "sk-test-not-real")
    st = AIProvider().status()
    assert st.status == "PARTIAL"
    gen2 = AIProvider().generate("secret prompt")
    assert gen2["is_ai_generated"] is False
    assert "disabled" in (gen2.get("error") or "").lower() or gen2["status"] == "NOT_CONFIGURED"

    monkeypatch.setenv("RITELINSIGHT_TELEGRAM_BOT_TOKEN", "123:ABC")
    enq = NotificationProvider().enqueue("alert", {"x": 1})
    assert enq["sent"] is False
    assert enq["delivery_status"] in ("QUEUED_LOCAL", "NOT_CONFIGURED")


def test_ready_and_ops_and_smoke(client, monkeypatch):
    monkeypatch.delenv("RITELINSIGHT_ENV", raising=False)
    assert client.get("/health").status_code == 200
    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["ready"] is True
    ops = client.get("/api/ops/status")
    assert ops.status_code == 200
    body = ops.json()
    assert "integrations" in body
    assert body["integrations"]["realtime"] == "NOT_CONFIGURED"
    # secret keys must not appear
    dump = str(body)
    assert "sk-" not in dump
    assert "BOT_TOKEN" not in dump or "RITELINSIGHT_TELEGRAM" not in dump

    for path in (
        "/api/schema",
        "/api/integrations",
        "/api/screener?timeframe=swing&limit=1",
        "/api/big-money",
        "/api/strategy",
        "/api/realtime/status",
        "/api/ai/status",
        "/api/notifications/status",
        "/api/payment/status",
    ):
        r = client.get(path)
        assert r.status_code < 500, path
        if r.headers.get("content-type", "").startswith("application/json"):
            text = r.text
            assert "Traceback" not in text
            assert "NaN" not in text


def test_production_ready_requires_cors(monkeypatch):
    monkeypatch.setenv("RITELINSIGHT_ENV", "production")
    monkeypatch.delenv("RITELINSIGHT_CORS_ORIGINS", raising=False)
    from idx.ops_status import readiness

    payload = readiness()
    assert payload["ready"] is False
    assert payload["blockers"]


def test_payment_provider_status():
    assert PaymentProvider().status().status == "NOT_CONFIGURED"
    assert PaymentProvider().webhook(headers={}, body=b"{}")["paid"] is False
