"""Completion-pass tests: screener harden, auth watchlist, trading plan, providers."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from idx import watchlist_store as wl
from idx.auth_session import clear_sessions_for_tests
from idx.big_money import build_big_money
from idx.providers import AIProvider, MarketDataProvider, NotificationProvider, PaymentProvider
from idx.schema_version import (
    DATA_SCHEMA_VERSION,
    classify_schema_version,
    normalize_company_record,
)
from idx.screener.contract import MIN_RR
from idx.screener.engine import run_screener
from idx.screener.historical import compute_historical_stats
from idx.screener.structure import enrich_structure
from idx.strategy_lab import list_strategies, run_strategy_lab
from idx.trading_plan import (
    compute_confirm_score,
    compute_journal_pl,
    compute_result_auto,
    compute_rr,
    enrich_plan,
)


def _bars(code: str, n: int = 80, start: float = 1000.0) -> pd.DataFrame:
    rng = np.random.default_rng(abs(hash(code)) % (2**32))
    dates = pd.bdate_range("2025-01-02", periods=n)
    closes = start + np.cumsum(rng.normal(1.5, 4, n))
    closes = np.maximum(closes, 50)
    highs = closes + rng.uniform(5, 40, n)
    lows = closes - rng.uniform(5, 40, n)
    highs[-12] = closes[-12] + 90
    lows[-18] = closes[-18] - 70
    return pd.DataFrame(
        {
            "Date": dates,
            "StockCode": code,
            "OpenPrice": closes,
            "High": highs,
            "Low": lows,
            "Close": closes,
            "Previous": np.concatenate([[closes[0]], closes[:-1]]),
            "Volume": rng.integers(1e6, 5e6, n).astype(float),
            "Value": closes * 2e6,
            "ForeignBuy": rng.integers(0, 1e5, n).astype(float),
            "ForeignSell": rng.integers(0, 8e4, n).astype(float),
        }
    )


@pytest.fixture
def client(tmp_path, monkeypatch):
    clear_sessions_for_tests()
    wl.reset_store_for_tests(str(tmp_path / "wl.json"))
    from idx.trading_plan import reset_store_for_tests

    reset_store_for_tests(str(tmp_path / "tj.json"))
    from idx.api import app

    return TestClient(app)


def test_cluster_a_causal_and_rr_for_representative_tickers():
    frames = [_bars("ADRO", start=2000), _bars("BBCA", start=9000), _bars("PTBA", start=3000)]
    stock = pd.concat(frames, ignore_index=True)
    # Impossible RR row injection check on ADRO last bar levels
    for code in ("ADRO", "BBCA", "PTBA"):
        out = run_screener(
            timeframe="swing",
            ticker=code,
            stock_df=stock,
            company_meta={},
            include_not_qualified=True,
            max_universe=10,
        )
        assert out["meta"]["network_alpha_required"] is False
        assert out["meta"]["universe_scanned"] >= 1
        assert len(out["results"]) >= 1
        row = out["results"][0]
        if row.get("tp1") is not None and row.get("cl1") is not None and row.get("entry_zone"):
            assert row["rr1"] is None or row["rr1"] >= MIN_RR


def test_cluster_a_poisoned_future_bar_not_in_levels():
    raw = _bars("BBCA", n=60)
    raw.loc[raw.index[-1], "High"] = 99_999_999
    enriched = enrich_structure(raw)
    assert enriched.iloc[-1]["HIGH_5D"] != 99_999_999


def test_cluster_a_insufficient_sample_status():
    enriched = enrich_structure(_bars("PTBA", n=25))
    stats = compute_historical_stats(enriched, signal_fn=lambda r: True, min_sample=30, min_rr=1.0)
    assert stats["stats_status"] == "INSUFFICIENT_SAMPLE"


def test_watchlist_auth_isolation(client):
    s1 = client.post("/api/auth/session").json()["session_id"]
    s2 = client.post("/api/auth/session").json()["session_id"]
    r = client.post(
        "/api/watchlist",
        json={"ticker": "ADRO", "company": "Adaro"},
        headers={"X-Ritel-Session": s1},
    )
    assert r.status_code == 200
    # User B cannot see User A
    listed = client.get("/api/watchlist", headers={"X-Ritel-Session": s2}).json()
    assert listed["count"] == 0
    # Unauthorized
    assert client.get("/api/watchlist").status_code == 401
    # Duplicate
    dup = client.post(
        "/api/watchlist",
        json={"ticker": "ADRO"},
        headers={"X-Ritel-Session": s1},
    )
    assert dup.status_code == 400
    # Delete missing
    assert client.delete("/api/watchlist/ZZZZ", headers={"X-Ritel-Session": s1}).status_code == 404
    # Delete ok
    assert client.delete("/api/watchlist/ADRO", headers={"X-Ritel-Session": s1}).status_code == 200
    empty = client.get("/api/watchlist", headers={"X-Ritel-Session": s1}).json()
    assert empty["count"] == 0


def test_trading_plan_excel_semantics():
    plan = {
        "tf_1d": "Bullish",
        "tf_15m": "Bullish",
        "tf_5m": "Bullish",
        "macd_bias": "Bullish",
        "volume_bias": "Buy",
        "supertrend_bias": "Buy",
        "ma5_ok": "OK",
        "ma20_ok": "OK",
        "ma50_ok": "OK",
        "vwap_ok": "OK",
        "broksum": "Acc",
        "entry_price": 1000,
        "tp": 1100,
        "cl": 950,
    }
    assert compute_confirm_score(plan) == 11
    assert compute_result_auto(plan) == "Buy"
    assert compute_rr(1000, 1100, 950) == pytest.approx(2.0)
    bear = dict(plan, tf_1d="Bearish")
    assert compute_result_auto(bear) == "No Trade"
    pl = compute_journal_pl(entry_price=1000, exit_price=1100, lots=1, stop_price=950)
    assert pl["shares"] == 100
    assert pl["net_pl"] is not None
    enriched = enrich_plan(plan)
    assert enriched["result_auto"] == "Buy"


def test_big_money_fast_in_out_unavailable():
    payload = build_big_money(ticker="BBCA", foreign_row=None, ownership_available=False)
    assert payload["layers"]["fast_in_fast_out"]["status"] == "UNAVAILABLE"
    assert "DATA INSUFFICIENT" in payload["layers"]["fast_in_fast_out"]["message"]
    assert payload["layers"]["broker"]["scope"] == "MARKET-WIDE"


def test_strategy_lab_oos_flag_and_unavailable():
    catalog = list_strategies()
    assert any(s["id"] == "close_pressure" for s in catalog["strategies"])
    unavailable = run_strategy_lab("intraday")
    assert unavailable["status"] == "UNAVAILABLE"
    assert unavailable["oos"] == "INSUFFICIENT OOS VALIDATION"
    assert unavailable["profitable_claim"] is False


def test_providers_not_configured():
    assert AIProvider().status().status == "NOT_CONFIGURED"
    assert NotificationProvider().status().status == "NOT_CONFIGURED"
    assert PaymentProvider().status().status == "NOT_CONFIGURED"
    md = MarketDataProvider().status().to_dict()
    caps = {c["name"]: c for c in md["capabilities"]}
    assert caps["realtime"]["status"] == "NOT_CONFIGURED"
    assert caps["orderbook"]["status"] == "NOT_CONFIGURED"


def test_schema_version_legacy_and_unsupported():
    assert classify_schema_version(DATA_SCHEMA_VERSION) == "current"
    assert classify_schema_version(None) == "legacy"
    assert classify_schema_version("9.9.9") == "unsupported"
    norm = normalize_company_record({"StockCode": "bbca", "pbv": 1.2, "price": 9000})
    assert norm["code"] == "BBCA"
    assert norm["price_bv"] == 1.2
    assert norm["close"] == 9000


def test_api_smoke_integrations_and_compute(client):
    assert client.get("/health").status_code == 200
    assert client.get("/api/integrations").json()["realtime"] == "NOT_CONFIGURED"
    assert client.get("/api/realtime/status").json()["realtime"] == "NOT_CONFIGURED"
    assert client.get("/api/ai/status").json()["status"] == "NOT_CONFIGURED"
    assert client.get("/api/payment/status").json()["status"] == "NOT_CONFIGURED"
    assert client.get("/api/strategy").status_code == 200
    assert client.get("/api/big-money").status_code == 200
    calc = client.post(
        "/api/trading-plan/compute",
        json={
            "tf_1d": "Bullish",
            "volume_bias": "Buy",
            "supertrend_bias": "Buy",
            "broksum": "Normal",
            "entry_price": 100,
            "tp": 120,
            "cl": 90,
        },
    )
    assert calc.status_code == 200
    assert "confirm_score" in calc.json()
    # Screener without network_alpha
    scr = client.get("/api/screener?timeframe=swing&limit=1")
    assert scr.status_code == 200
    body = scr.json()
    assert "results" in body
    assert body["meta"].get("network_alpha_required") is False


def test_stock_broker_alias_market_wide(client):
    resp = client.get("/api/stock/BBCA/broker")
    assert resp.status_code == 200
    data = resp.json()
    assert data["scope"] == "MARKET-WIDE"
    assert data["stock_specific"] is False
