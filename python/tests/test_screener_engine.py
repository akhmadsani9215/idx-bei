"""Tests for Screener Production Engine — dynamic targets/stops, RR, quality, no fabrication."""

from __future__ import annotations

from datetime import datetime, time

import numpy as np
import pandas as pd
import pytest

from idx.close_pressure_config import classify_time_window
from idx.screener.contract import (
    MIN_OPPORTUNITY_PCT,
    MIN_RR,
    SETUP_NOT_QUALIFIED,
    STATUS_INSUFFICIENT_DATA,
    STATUS_INSUFFICIENT_SAMPLE,
)
from idx.screener.engine import (
    evaluate_close_pressure_row,
    evaluate_long_term_candidate,
    evaluate_swing_row,
    run_screener,
)
from idx.screener.historical import compute_historical_stats
from idx.screener.structure import (
    classify_lifecycle,
    enrich_structure,
    reward_risk,
    select_dynamic_levels,
)


def _ohlcv(
    n: int = 80,
    *,
    start: float = 1000.0,
    trend: float = 2.0,
    vol: float = 1.2,
    code: str = "TEST",
) -> pd.DataFrame:
    """Synthetic daily bars with enough history for structure levels."""
    rng = np.random.default_rng(42)
    dates = pd.bdate_range("2025-01-02", periods=n)
    closes = []
    px = start
    for i in range(n):
        px = px + trend + float(rng.normal(0, 5))
        closes.append(max(50.0, px))
    closes = np.array(closes, dtype=float)
    highs = closes + np.abs(rng.normal(10, 3, n))
    lows = closes - np.abs(rng.normal(10, 3, n))
    opens = closes + rng.normal(0, 3, n)
    # Create a clear prior swing high / low structure
    highs[-15] = closes[-15] + 80
    lows[-20] = closes[-20] - 60
    vol_arr = rng.integers(1_000_000, 5_000_000, n).astype(float)
    vol_arr[-5:] *= vol
    fb = rng.integers(0, 100_000, n).astype(float)
    fs = rng.integers(0, 80_000, n).astype(float)
    fb[-5:] = fs[-5:] + 50_000
    return pd.DataFrame(
        {
            "Date": dates,
            "StockCode": code,
            "OpenPrice": opens,
            "High": highs,
            "Low": lows,
            "Close": closes,
            "Previous": np.concatenate([[closes[0]], closes[:-1]]),
            "Volume": vol_arr,
            "Value": vol_arr * closes,
            "ForeignBuy": fb,
            "ForeignSell": fs,
        }
    )


def test_dynamic_target_not_fixed_percent():
    df = enrich_structure(_ohlcv())
    row = df.iloc[-1]
    levels = select_dynamic_levels(row, min_rr=MIN_RR, min_opportunity_pct=MIN_OPPORTUNITY_PCT)
    entry = levels["entry_zone"]
    assert entry is not None
    # Must not be universal +3/+5/+7% fabrications
    for key in ("tp1", "tp2", "tp3"):
        tp = levels.get(key)
        if tp is None:
            continue
        pct = (tp - entry) / entry * 100.0
        assert abs(pct - 3.0) > 0.05
        assert abs(pct - 5.0) > 0.05
        assert abs(pct - 7.0) > 0.05
        assert levels.get(f"{key}_source") is not None


def test_dynamic_stop_not_fixed_percent():
    df = enrich_structure(_ohlcv())
    row = df.iloc[-1]
    levels = select_dynamic_levels(row, min_rr=1.0, min_opportunity_pct=None)
    entry = levels["entry_zone"]
    cl1 = levels.get("cl1")
    if cl1 is None:
        pytest.skip("No structural stop in synthetic path")
    pct = (cl1 - entry) / entry * 100.0
    assert abs(pct + 1.0) > 0.05
    assert abs(pct + 3.0) > 0.05
    assert abs(pct + 5.0) > 0.05
    assert levels.get("cl1_source") is not None


def test_rr_gate_requires_two_to_one():
    # Construct row with known structure
    row = pd.Series(
        {
            "Close": 1000.0,
            "ATR14": 20.0,
            "LAST_SWING_HIGH": 1060.0,  # +6% → RR vs stop
            "HIGH_5D": 1040.0,
            "HIGH_10D": 1050.0,
            "HIGH_20D": 1060.0,
            "LAST_SWING_LOW": 980.0,  # risk 20 → RR for 1060 = 3.0
            "LOW_5D": 975.0,
            "LOW_20D": 970.0,
        }
    )
    levels = select_dynamic_levels(row, min_rr=2.0, min_opportunity_pct=3.0)
    assert levels["qualified"] is True
    assert levels["rr1"] is not None and levels["rr1"] >= 2.0
    assert reward_risk(1000.0, levels["tp1"], levels["cl1"]) >= 2.0


def test_not_qualified_when_rr_fails():
    # Target too close vs deep stop → RR < 2
    row = pd.Series(
        {
            "Close": 1000.0,
            "ATR14": 5.0,
            "LAST_SWING_HIGH": 1015.0,  # +1.5% only
            "HIGH_5D": 1012.0,
            "LAST_SWING_LOW": 900.0,  # huge risk
            "LOW_5D": 890.0,
            "LOW_20D": 880.0,
        }
    )
    levels = select_dynamic_levels(row, min_rr=2.0, min_opportunity_pct=3.0)
    assert levels["qualified"] is False
    assert levels["setup_status"] == SETUP_NOT_QUALIFIED
    assert levels["tp1"] is None
    assert levels["tp2"] is None
    assert levels["tp3"] is None


def test_no_fabricated_tp2_tp3():
    # Only one resistance above entry that clears RR
    row = pd.Series(
        {
            "Close": 1000.0,
            "ATR14": np.nan,  # no ATR extensions
            "LAST_SWING_HIGH": 1100.0,
            "HIGH_5D": 1005.0,  # below +3% floor when CP floor applied
            "LAST_SWING_LOW": 980.0,
            "LOW_5D": 975.0,
        }
    )
    levels = select_dynamic_levels(row, min_rr=2.0, min_opportunity_pct=3.0)
    assert levels["qualified"] is True
    assert levels["tp1"] is not None
    # Without more structure / ATR, tp2/tp3 must stay null — not invented
    assert levels["tp2"] is None
    assert levels["tp3"] is None


def test_close_pressure_time_windows():
    assert classify_time_window(time(14, 30)) == "WATCH"
    assert classify_time_window(time(15, 0)) == "PRESSURE_BUILDING"
    assert classify_time_window(time(15, 30)) == "PRIMARY_SIGNAL"
    assert classify_time_window(time(15, 50)) == "PRE_CLOSING"
    assert classify_time_window(time(16, 0)) == "CLOSING_MATCH"
    assert classify_time_window(time(16, 3)) == "OUTSIDE"
    assert classify_time_window(time(10, 0)) == "OUTSIDE"


def test_eod_snapshot_quality_on_close_pressure():
    enriched = enrich_structure(_ohlcv(n=90, vol=2.0))
    # Force a path that can qualify: bump last swing high / low
    enriched.loc[enriched.index[-1], "LAST_SWING_HIGH"] = enriched.iloc[-1]["Close"] * 1.12
    enriched.loc[enriched.index[-1], "HIGH_20D"] = enriched.iloc[-1]["Close"] * 1.12
    enriched.loc[enriched.index[-1], "LAST_SWING_LOW"] = enriched.iloc[-1]["Close"] * 0.97
    enriched.loc[enriched.index[-1], "LOW_20D"] = enriched.iloc[-1]["Close"] * 0.96
    enriched.loc[enriched.index[-1], "ATR14"] = enriched.iloc[-1]["Close"] * 0.02

    result = evaluate_close_pressure_row(
        enriched,
        now_jakarta=datetime(2026, 9, 23, 15, 40),
    )
    assert result["data_quality"] == "E"
    assert result["confidence"] is not None and result["confidence"] < 0.5
    assert result["intraday_trade_side_available"] is False
    assert result["book_pressure_is_transaction"] is False
    assert "EOD" in (result["why_signal"] or "")
    assert result["cpe_phase"] == "PRIMARY_SIGNAL"


def test_dormant_to_active_lifecycle():
    base = _ohlcv(n=60, vol=0.5)
    enriched = enrich_structure(base)
    # Low RVOL path
    enriched.loc[enriched.index[-1], "RVOL"] = 0.4
    enriched.loc[enriched.index[-1], "HIGH_20D"] = enriched.iloc[-1]["Close"] * 1.05
    enriched.loc[enriched.index[-1], "LOW_20D"] = enriched.iloc[-1]["Close"] * 0.97
    assert classify_lifecycle(enriched.iloc[-1]) == "DORMANT"

    enriched.loc[enriched.index[-1], "RVOL"] = 0.9
    assert classify_lifecycle(enriched.iloc[-1]) in ("EARLY_ACTIVITY", "ACCUMULATION", "DORMANT")

    enriched.loc[enriched.index[-1], "RVOL"] = 2.0
    enriched.loc[enriched.index[-1], "CLOSE_LOC"] = 0.9
    enriched.loc[enriched.index[-1], "HIGH_20D"] = enriched.iloc[-1]["Close"] * 0.99
    state = classify_lifecycle(enriched.iloc[-1])
    assert state in ("BREAKOUT", "EXPANSION", "ACTIVE")


def test_swing_engine_separated_from_close_pressure():
    enriched = enrich_structure(_ohlcv(n=100, trend=3.0, vol=1.8))
    last = enriched.iloc[-1]
    # Ensure structure fields for pullback/breakout-ish path
    enriched.loc[enriched.index[-1], "SMA20"] = last["Close"] * 0.98
    enriched.loc[enriched.index[-1], "SMA50"] = last["Close"] * 0.95
    enriched.loc[enriched.index[-1], "HIGH_20D"] = last["Close"] * 0.99
    enriched.loc[enriched.index[-1], "RVOL"] = 1.8
    enriched.loc[enriched.index[-1], "CLOSE_LOC"] = 0.8
    enriched.loc[enriched.index[-1], "LAST_SWING_HIGH"] = last["Close"] * 1.15
    enriched.loc[enriched.index[-1], "LAST_SWING_LOW"] = last["Close"] * 0.96
    enriched.loc[enriched.index[-1], "ATR14"] = last["Close"] * 0.02

    swing = evaluate_swing_row(enriched)
    cp = evaluate_close_pressure_row(enriched)
    assert swing["timeframe"] == "swing"
    assert cp["timeframe"] == "close_pressure"
    # Swing setup must not be a Close Pressure label rename
    if swing["setup"] != SETUP_NOT_QUALIFIED:
        assert not str(swing["setup"]).startswith("close_pressure")
        assert swing["setup"].startswith("swing_")


def test_long_term_insufficient_data():
    row = evaluate_long_term_candidate(
        ticker="ZZZZ",
        company_meta={"name": "Empty Co", "roe": 20.0},  # only 1 field
        enriched=None,
    )
    assert row["status"] == STATUS_INSUFFICIENT_DATA
    assert row["setup"] == SETUP_NOT_QUALIFIED
    assert row["signal"] == "CANDIDATE"
    assert "INSUFFICIENT" in (row["why_signal"] or "")


def test_long_term_candidate_partial():
    enriched = enrich_structure(_ohlcv(code="BBCA"))
    row = evaluate_long_term_candidate(
        ticker="BBCA",
        company_meta={
            "name": "Bank XYZ",
            "roe": 18.0,
            "per": 12.0,
            "price_bv": 1.2,
            "npm": 25.0,
            "de_ratio": 1.0,
            "yield": 4.5,
        },
        enriched=enriched,
    )
    assert row["signal"] == "CANDIDATE"
    assert row["status"] == "PARTIAL"
    assert "CANDIDATE" in (row["why_signal"] or "")
    assert "multibagger" in (row["why_signal"] or "").lower()  # disclaimer present


def test_historical_sample_size_gating():
    enriched = enrich_structure(_ohlcv(n=40))
    stats = compute_historical_stats(
        enriched,
        signal_fn=lambda r: True,
        horizon=5,
        min_sample=30,
        min_opportunity_pct=None,
        min_rr=1.0,
    )
    # With short history, expect insufficient or unavailable — never fake high confidence
    assert stats["sample_size"] < 30 or stats["stats_status"] == STATUS_INSUFFICIENT_SAMPLE
    if stats["sample_size"] < 30:
        assert stats["stats_status"] == STATUS_INSUFFICIENT_SAMPLE


def test_no_future_leakage_in_structure_levels():
    raw = _ohlcv(n=50)
    # Poison the final bar high/low — levels for last bar must use prior windows only
    raw.loc[raw.index[-1], "High"] = 9_999_999
    raw.loc[raw.index[-1], "Low"] = 1
    enriched = enrich_structure(raw)
    last = enriched.iloc[-1]
    # Prior 5D high must not equal the poisoned current high
    assert last["HIGH_5D"] != 9_999_999
    assert last["LOW_5D"] != 1
    assert last["HIGH_5D"] < 9_999_999


def test_schema_mismatch_missing_fields():
    # Malformed / nearly empty frame
    empty = pd.DataFrame({"Date": [], "StockCode": [], "Close": []})
    out = run_screener(timeframe="swing", stock_df=empty, company_meta={})
    assert out["results"] == []
    assert out["meta"]["status"] in ("UNAVAILABLE", "ok")

    # Missing High/Low — engine should not crash
    thin = pd.DataFrame(
        {
            "Date": pd.bdate_range("2025-06-01", periods=30),
            "StockCode": ["AAA"] * 30,
            "Close": np.linspace(100, 130, 30),
            "Volume": [1e6] * 30,
            "Value": [1e9] * 30,
        }
    )
    out2 = run_screener(
        timeframe="close_pressure",
        stock_df=thin,
        company_meta={},
        include_not_qualified=True,
    )
    assert "results" in out2
    assert isinstance(out2["results"], list)


def test_empty_screener_result():
    out = run_screener(
        timeframe="close_pressure",
        stock_df=pd.DataFrame(),
        company_meta={},
    )
    assert out["results"] == []
    assert out["meta"]["count"] == 0


def test_malformed_null_data_sanitize():
    enriched = enrich_structure(_ohlcv(n=50))
    enriched.loc[enriched.index[-1], "Close"] = np.nan
    result = evaluate_close_pressure_row(enriched)
    assert result["price"] is None or result["price"] != result["price"]  # null-safe
    # JSON-facing sanitize should use None
    from idx.screener.contract import sanitize_result

    clean = sanitize_result(result)
    assert clean["price"] is None


def test_run_screener_filters_and_pagination():
    frames = []
    for i, code in enumerate(["AAA", "BBB", "CCC"]):
        f = _ohlcv(n=70, start=800 + i * 50, code=code, vol=2.0)
        frames.append(f)
    stock = pd.concat(frames, ignore_index=True)
    # Inject structure so at least some can qualify
    out = run_screener(
        timeframe="swing",
        stock_df=stock,
        company_meta={
            "AAA": {"name": "A"},
            "BBB": {"name": "B"},
            "CCC": {"name": "C"},
        },
        limit=2,
        cursor=0,
        include_not_qualified=True,
    )
    assert out["meta"]["limit"] == 2
    assert len(out["results"]) <= 2
    assert "engine_version" in out["meta"]
    assert out["meta"]["next_cursor"] in (None, 2) or out["meta"]["total_matched"] <= 2


def test_unknown_timeframe_error():
    out = run_screener(timeframe="intraday_tick", stock_df=_ohlcv())
    assert out["results"] == []
    assert out["meta"]["status"] == "error"
