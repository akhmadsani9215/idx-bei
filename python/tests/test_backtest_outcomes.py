"""Per-trade outcome metrics (MFE/MAE, TP/CL hit, holding sessions) in run_backtest."""

from __future__ import annotations

import pandas as pd

from idx.backtest import run_backtest
from idx.signal_discovery.metrics_adapter import adapt_backtest_metrics


def _universe(aaa_closes: list[float]) -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-05", periods=len(aaa_closes))
    rows = []
    for i, d in enumerate(dates):
        for code, c, prev, fb, fs in (
            ("AAA", aaa_closes[i], aaa_closes[max(i - 1, 0)], 2_000_000.0, 200_000.0),
            ("BBB", 200.0 + 5.0 * i, 200.0 + 5.0 * max(i - 1, 0), 100_000.0, 2_000_000.0),
        ):
            rows.append(
                {
                    "Date": d.strftime("%Y-%m-%d"),
                    "StockCode": code,
                    "OpenPrice": c - 1.0,
                    "High": c + 2.0,
                    "Low": c - 2.0,
                    "Close": c,
                    "Volume": 1_000_000,
                    "Value": 5e9,
                    "Previous": prev,
                    "ForeignBuy": fb,
                    "ForeignSell": fs,
                    "TradebleShares": 100_000_000,
                }
            )
    return pd.DataFrame(rows)


_RATIOS = pd.DataFrame([{"code": "AAA", "fsDate": "2025-06-30", "roe": 20.0}])


def _run(closes: list[float], **kwargs):
    return run_backtest(
        strategy="foreign_flow",
        holding_days=2,
        top_n=1,
        min_turnover_rp=1e8,
        stock_df=_universe(closes),
        ratios_df=_RATIOS,
        **kwargs,
    )


def test_time_exit_excursions_use_post_entry_high_low():
    metrics, trades = _run([100.0, 110.0, 120.0, 130.0, 140.0, 150.0])
    first = trades.iloc[0]
    assert first["StockCode"] == "AAA"
    assert first["ExitReason"] == "TIME"
    assert first["HoldingSessions"] == 2
    assert first["ExcursionBasis"] == "HIGH_LOW"
    # entry Close 100; post-entry highs 112/122, lows 108/118 → MFE 22%, MAE 0%
    assert first["MFEPct"] == 22.0
    assert first["MAEPct"] == 0.0
    assert metrics["expectancy_pct"] is not None
    assert metrics["median_mfe_pct"] is not None
    assert metrics["excursion_basis"] == "HIGH_LOW"
    assert metrics["tp_hit_rate_pct"] is None  # no TP rule configured
    assert metrics["cl_hit_rate_pct"] is None


def test_stop_loss_exit_is_recorded_with_hit_rate():
    metrics, trades = _run([100.0, 90.0, 80.0, 70.0, 60.0, 50.0], stop_loss_pct=5.0)
    first = trades.iloc[0]
    assert first["ExitReason"] == "STOP_LOSS"
    assert first["HoldingSessions"] == 1
    assert first["Return"] == -0.05
    # excursion is the real path (Low 88 → -12%), not the booked stop level
    assert first["MAEPct"] == -12.0
    assert metrics["cl_hit_rate_pct"] == 100.0
    assert metrics["tp_hit_rate_pct"] is None


def test_take_profit_hit_rate():
    metrics, trades = _run([100.0, 110.0, 120.0, 130.0, 140.0, 150.0], take_profit_pct=5.0)
    assert set(trades["ExitReason"]) == {"TAKE_PROFIT"}
    assert metrics["tp_hit_rate_pct"] == 100.0
    assert metrics["cl_hit_rate_pct"] is None


def test_empty_result_outcomes_are_null():
    metrics, trades = run_backtest(strategy="not_a_strategy")
    assert len(trades) == 0
    for key in ("expectancy_pct", "median_mfe_pct", "median_mae_pct", "median_holding_sessions"):
        assert metrics[key] is None


def test_technical_rules_are_point_in_time():
    """Appending future bars must not change any earlier selection (trailing features only)."""
    from idx.backtest import TECHNICAL_RULES

    closes = [100.0 + (i % 7) * 3.0 - (i % 3) * 5.0 for i in range(60)]
    base = _universe(closes)
    future = _universe(closes + [500.0] * 10)
    for strategy in TECHNICAL_RULES:
        kwargs = dict(
            strategy=strategy, holding_days=2, top_n=1, min_turnover_rp=1e8, ratios_df=_RATIOS
        )
        _, a = run_backtest(stock_df=base, **kwargs)
        _, b = run_backtest(stock_df=future, **kwargs)
        cols = ["EntryDate", "StockCode"]
        if len(a):
            last_entry = a["EntryDate"].max()
            b_same = b[b["EntryDate"] < last_entry][cols].reset_index(drop=True)
            a_same = a[a["EntryDate"] < last_entry][cols].reset_index(drop=True)
            assert a_same.equals(b_same), strategy


def test_window_trades_stay_inside_window_with_warmup():
    closes = [100.0 + i for i in range(40)]
    start, end = "2026-02-02", "2026-02-20"
    for strategy in ("foreign_flow", "momentum"):
        _, trades = run_backtest(
            strategy=strategy,
            holding_days=2,
            top_n=1,
            min_turnover_rp=1e8,
            start_date=start,
            end_date=end,
            stock_df=_universe(closes),
            ratios_df=_RATIOS,
        )
        assert len(trades) > 0, strategy
        assert trades["EntryDate"].min() >= start
        assert trades["ExitDate"].max() <= end


def test_trades_never_span_a_data_gap():
    stock = _universe([100.0 + i for i in range(30)])
    stock["Date"] = pd.to_datetime(stock["Date"])
    late = stock["Date"] > "2026-01-23"  # shift the tail by 60 days → artificial data gap
    stock.loc[late, "Date"] = stock.loc[late, "Date"] + pd.Timedelta(days=60)
    for strategy in ("foreign_flow", "momentum"):
        metrics, trades = run_backtest(
            strategy=strategy,
            holding_days=3,
            top_n=1,
            min_turnover_rp=1e8,
            stock_df=stock,
            ratios_df=_RATIOS,
        )
        assert metrics["data_gap_segments"] == 2
        assert metrics["data_gap_rebalances_skipped"] >= 1
        if strategy == "momentum":
            # 20-session lookback cannot be satisfied inside either 15-session segment
            assert len(trades) == 0
            continue
        assert len(trades) > 0
        spans = pd.to_datetime(trades["ExitDate"]) - pd.to_datetime(trades["EntryDate"])
        assert (spans.dt.days <= 14).all(), strategy


def test_adapter_surfaces_engine_outcomes():
    metrics, trades = _run([100.0, 110.0, 120.0, 130.0, 140.0, 150.0])
    adapted = adapt_backtest_metrics(metrics, trades_df=trades, holding_days=2)
    assert adapted["mfe"] == metrics["median_mfe_pct"]
    assert adapted["mae"] == metrics["median_mae_pct"]
    assert "mfe_status" not in adapted
    assert adapted["tp_hit_rate_pct_status"] == "NOT_CONFIGURED"
    assert adapted["median_holding_sessions"] == 2.0
