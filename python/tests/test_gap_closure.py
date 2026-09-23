"""Production gap-closure tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from idx.auth_session import auth_status
from idx.backtest import _pit_market_slice
from idx.big_money import build_big_money
from idx.cors_config import resolve_cors_origins
from idx.rebuild import rebuild_features, rebuild_target_risk
from idx.screener.structure import enrich_structure
from idx.strategy_lab import normalize_lab_metrics
from idx.trading_plan import (
    compute_confirm_score,
    compute_journal_pl,
    compute_result_auto,
    compute_rr,
    enrich_plan,
    weekly_recap,
)
from idx.universe import apply_universe_cap, discover_universe


def _bars(code="AAA", n=40):
    dates = pd.bdate_range("2025-06-01", periods=n)
    closes = np.linspace(100, 140, n)
    return pd.DataFrame(
        {
            "Date": dates,
            "StockCode": code,
            "OpenPrice": closes,
            "High": closes + 5,
            "Low": closes - 5,
            "Close": closes,
            "Previous": np.concatenate([[closes[0]], closes[:-1]]),
            "Volume": np.full(n, 1e6),
            "Value": closes * 1e6,
            "ForeignBuy": np.full(n, 1000.0),
            "ForeignSell": np.full(n, 500.0),
        }
    )


def test_big_money_inventory_and_fast_in_out():
    bm = build_big_money(ticker="BBCA", ownership_available=False, foreign_row=None)
    assert bm["layers"]["fast_in_fast_out"]["status"] == "UNAVAILABLE"
    assert "DATA INSUFFICIENT" in bm["layers"]["fast_in_fast_out"]["message"]
    assert bm["data_inventory"]["actor_level_transaction"] == "UNAVAILABLE"
    assert bm["layers"]["broker"]["scope"] == "MARKET-WIDE"

    # Foreign available
    bm2 = build_big_money(
        ticker="BBCA",
        ownership_available=False,
        foreign_row={"ForeignBuy": 10, "ForeignSell": 3, "as_of": "2026-01-02"},
    )
    assert bm2["layers"]["foreign"]["status"] == "AVAILABLE"
    assert bm2["layers"]["foreign"]["foreign_net"] == 7


def test_big_money_broker_concentration_from_frame():
    broker = pd.DataFrame(
        {
            "Date": ["2026-01-02"] * 3,
            "IDFirm": ["A", "B", "C"],
            "FirmName": ["A", "B", "C"],
            "Value": [100e9, 50e9, 25e9],
            "Volume": [1, 1, 1],
        }
    )
    bm = build_big_money(ticker=None, broker_summary=broker, ownership_available=False)
    assert bm["layers"]["broker"]["status"] == "AVAILABLE"
    assert bm["layers"]["broker"]["concentration"]["cr1_pct"] is not None
    assert bm["layers"]["broker"]["concentration"]["institutional_share_pct"] is None


def test_cors_production_no_wildcard():
    dev = resolve_cors_origins(env="development")
    assert "*" in dev["allow_origins"]
    assert dev["allow_credentials"] is False
    prod_empty = resolve_cors_origins(env="production", origins_env="")
    assert prod_empty["allow_origins"] == []
    prod = resolve_cors_origins(env="production", origins_env="https://app.example.com")
    assert prod["allow_origins"] == ["https://app.example.com"]
    stripped = resolve_cors_origins(env="production", origins_env="*,https://x.com")
    assert "*" not in stripped["allow_origins"]


def test_universe_cap_not_silent():
    tickers = [f"T{i:03d}" for i in range(100)]
    meta = apply_universe_cap(tickers, max_universe=10)
    assert meta["universe_total"] == 100
    assert meta["skipped_due_to_cap"] == 90
    assert meta["universe_capped"] is True
    assert len(meta["tickers"]) == 10


def test_discover_universe_from_frame():
    df = pd.concat([_bars("ADRO"), _bars("BBCA"), _bars("PTBA")], ignore_index=True)
    uni = discover_universe(df)
    assert uni["universe_total"] == 3
    assert uni["network_alpha_required"] is False
    assert set(uni["tickers"]) == {"ADRO", "BBCA", "PTBA"}


def test_rebuild_does_not_require_network_and_is_deterministic():
    df = pd.concat([_bars("ADRO", 50), _bars("BBCA", 50)], ignore_index=True)
    feat = rebuild_features(stock_df=df, max_tickers=2)
    assert feat["mutates_source"] is False
    assert feat["records"] >= 1
    assert feat["engine_version"]
    tr = rebuild_target_risk(stock_df=df, max_tickers=2)
    assert tr["mutates_source"] is False
    assert tr["records"] >= 1


def test_pit_slice_excludes_future_bars():
    df = _bars("X", 10)
    entry = df["Date"].iloc[5]
    pit = _pit_market_slice(df, entry)
    assert pit["Date"].max() <= entry
    assert len(pit) == 6


def test_structure_no_current_bar_in_prior_high():
    df = _bars("Y", 30)
    df.loc[df.index[-1], "High"] = 999999
    en = enrich_structure(df)
    assert en.iloc[-1]["HIGH_5D"] != 999999


def test_lab_metrics_unavailable_not_zero():
    norm = normalize_lab_metrics({"total_trades": 12, "win_rate_pct": 40.0})
    assert norm["sample"] == 12
    assert norm["mfe"] is None
    assert norm["mfe_status"] == "UNAVAILABLE"
    assert norm["distribution_status"] == "UNAVAILABLE"


def test_trading_plan_edge_cases():
    assert compute_rr(100, 120, 100) is None  # zero risk
    assert compute_rr(None, 120, 90) is None
    pl = compute_journal_pl(entry_price=100, exit_price=None, lots=1)
    assert pl["net_pl"] is None
    assert compute_result_auto({"tf_1d": "Bearish"}) == "No Trade"
    assert compute_confirm_score({}) == 0
    plan = enrich_plan(
        {
            "tf_1d": "Bullish",
            "volume_bias": "Sell",
            "supertrend_bias": "Sell",
            "entry_price": 100,
            "tp": 110,
            "cl": 95,
        }
    )
    assert plan["result_auto"] == "No Trade"
    weekly = weekly_recap([])
    assert weekly["sample_status"] == "EMPTY"
    assert weekly["total_trades"] == 0


def test_auth_multi_user_idp_message():
    st = auth_status()
    assert "MULTI-USER IDENTITY PROVIDER NOT CONFIGURED" in st["multi_user_identity_provider"]
