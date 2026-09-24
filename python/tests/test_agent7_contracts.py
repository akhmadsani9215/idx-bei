"""Agent 7 — production integration contract / honesty regression tests."""

from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient

from idx import watchlist_store as wl
from idx.auth_session import clear_sessions_for_tests


@pytest.fixture
def client(tmp_path, monkeypatch):
    clear_sessions_for_tests()
    wl.reset_store_for_tests(str(tmp_path / "wl.json"))
    from idx.trading_plan import reset_store_for_tests

    reset_store_for_tests(str(tmp_path / "tj.json"))
    from idx.api import app

    return TestClient(app, raise_server_exceptions=False)


def _assert_json_no_nan(resp):
    assert resp.status_code < 500
    if resp.headers.get("content-type", "").startswith("application/json"):
        text = resp.text
        assert "NaN" not in text
        assert "Infinity" not in text
        assert "Traceback" not in text
        body = resp.json()
        _walk_finite(body)


def _walk_finite(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            _walk_finite(v)
    elif isinstance(obj, list):
        for v in obj:
            _walk_finite(v)
    elif isinstance(obj, float):
        assert math.isfinite(obj)


def test_schema_aliases(client):
    for path in ("/api/schema", "/schema"):
        r = client.get(path)
        assert r.status_code == 200, path
        body = r.json()
        assert body.get("DATA_SCHEMA_VERSION") == "1.0.0"
        assert "supported" in body


def test_data_status_alias(client):
    r = client.get("/api/data-status")
    assert r.status_code == 200
    body = r.json()
    assert "inventory" in body or "status" in body
    _assert_json_no_nan(r)


def test_provider_status_aliases(client, monkeypatch):
    monkeypatch.delenv("RITELINSIGHT_AI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("RITELINSIGHT_TELEGRAM_BOT_TOKEN", raising=False)
    for path in ("/api/ai", "/api/ai/status", "/api/notifications", "/api/payment"):
        r = client.get(path)
        assert r.status_code == 200, path
        body = r.json()
        assert body.get("status") == "NOT_CONFIGURED" or body.get("provider")
        _assert_json_no_nan(r)


def test_stock_ownership_and_signals_honest(client):
    own = client.get("/api/stock/BBCA/ownership")
    assert own.status_code == 200
    ob = own.json()
    assert ob["ticker"] == "BBCA"
    assert ob.get("fast_in_fast_out") == "UNAVAILABLE"
    assert ob.get("status") in ("UNAVAILABLE", "PARTIAL", "AVAILABLE", "ok")
    assert "ownership" in ob
    _assert_json_no_nan(own)

    sig = client.get("/api/stock/BBCA/signals")
    assert sig.status_code == 200
    sb = sig.json()
    assert sb["ticker"] == "BBCA"
    assert sb.get("realtime") == "NOT_CONFIGURED"
    _assert_json_no_nan(sig)


def test_stock_broker_injection_rejected(client):
    bad = client.get("/api/stock/BBCA';DROP/broker")
    assert bad.status_code == 400


def test_blocks_whale_null_not_zero(client, monkeypatch):
    """When ticker missing from dataset → 404; when present whale must be null."""
    import pandas as pd

    df = pd.DataFrame(
        {
            "Date": ["2026-01-05"],
            "StockCode": ["ZZZZ"],
            "Close": [1000.0],
            "Value": [1e9],
            "Volume": [1e6],
            # Intentionally omit ForeignBuy / VWAP / NonRegular*
        }
    )

    monkeypatch.setattr(
        "idx.api.query_dataset",
        lambda *a, **k: df,
    )
    r = client.get("/api/stock/ZZZZ/blocks")
    assert r.status_code == 200
    body = r.json()
    assert body["broker_blocks_available"] is False
    assert body["blocks"] == []
    assert body["total_whale_value_rp"] is None
    assert body["smart_accumulation_ratio"] is None
    assert body["foreign_buy_shares"] is None
    assert body["foreign_sell_shares"] is None
    assert body["net_foreign_flow_rp"] is None
    assert body.get("vwap_status") == "UNAVAILABLE"
    assert body["vwap_price"] is None
    _assert_json_no_nan(r)


def test_realtime_not_configured(client):
    r = client.get("/api/realtime/status")
    assert r.status_code == 200
    assert r.json()["realtime"] == "NOT_CONFIGURED"


def test_smoke_matrix_no_nan(client):
    paths = [
        "/health",
        "/ready",
        "/api/schema",
        "/api/data-status",
        "/api/screener?timeframe=swing&limit=1",
        "/api/big-money",
        "/api/strategy",
        "/api/integrations",
        "/api/realtime/status",
        "/api/stock/BBCA/broker",
        "/api/stock/BBCA/ownership",
        "/api/stock/BBCA/signals",
        "/api/ai",
        "/api/notifications",
        "/api/payment",
    ]
    for path in paths:
        r = client.get(path)
        assert r.status_code < 500, f"{path} -> {r.status_code}"
        _assert_json_no_nan(r)
