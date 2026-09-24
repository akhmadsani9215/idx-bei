"""
Point-in-time & entry/exit contract tests for the existing backtest engine.

Uses small synthetic datasets only. Exercises ``run_backtest`` / signal helpers
directly — no second engine.
"""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from idx.backtest import calculate_metrics, run_backtest
from idx.signals import (
    _latest_per_code,
    compute_technical_indicators,
    foreign_flow_radar,
    sharia_value_screen,
)


def _synthetic_flow_universe(
    dates: pd.DatetimeIndex,
    *,
    aaa_closes: list[float] | None = None,
    bbb_closes: list[float] | None = None,
    aaa_fb: float = 2_000_000.0,
    aaa_fs: float = 200_000.0,
    bbb_fb: float = 100_000.0,
    bbb_fs: float = 2_000_000.0,
) -> pd.DataFrame:
    """Two-ticker universe: AAA = foreign inflow, BBB = outflow."""
    n = len(dates)
    if aaa_closes is None:
        aaa_closes = [100.0 + 10.0 * i for i in range(n)]
    if bbb_closes is None:
        bbb_closes = [200.0 + 5.0 * i for i in range(n)]
    rows: list[dict] = []
    for i, d in enumerate(dates):
        for code, closes, fb, fs in (
            ("AAA", aaa_closes, aaa_fb, aaa_fs),
            ("BBB", bbb_closes, bbb_fb, bbb_fs),
        ):
            c = float(closes[i])
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
                    # IDX reference price = prior Close (no corporate action)
                    "Previous": float(closes[i - 1]) if i else c,
                    "ForeignBuy": fb,
                    "ForeignSell": fs,
                    "TradebleShares": 100_000_000,
                }
            )
    return pd.DataFrame(rows)


class TestBacktestPITContract(unittest.TestCase):
    """Mandatory entry/exit evidence + anti-look-ahead assertions."""

    def test_entry_exit_contract_foreign_flow_synthetic(self):
        """Concrete evidence from the ACTUAL ``run_backtest`` implementation.

        Dates (business sessions):
          D1=2026-01-05, D2=2026-01-06, D3=2026-01-07, D4=2026-01-08,
          D5=2026-01-09, D6=2026-01-12

        Convention under test:
          * signal + entry on D1 (same-session Close)
          * planned exit = unique_dates[entry_idx + holding_days] = D3
          * holding_days=2 → D1 → D3
          * AAA Close path: 100, 110, 120, 130, 140, 150
          * gross return = (120 - 100) / 100 = 0.20
          * fees/slippage: not applied (unsupported)
        """
        dates = pd.bdate_range("2026-01-05", periods=6)
        stock = _synthetic_flow_universe(
            dates, aaa_closes=[100.0, 110.0, 120.0, 130.0, 140.0, 150.0]
        )
        ratios = pd.DataFrame(
            [
                {
                    "code": "AAA",
                    "stockName": "AAA",
                    "fsDate": "2025-06-30",
                    "roe": 20.0,
                    "per": 10.0,
                    "deRatio": 0.5,
                    "opini": "WTP",
                    "sharia": "S",
                }
            ]
        )

        metrics, trades = run_backtest(
            strategy="foreign_flow",
            holding_days=2,
            top_n=1,
            min_turnover_rp=1e8,
            stock_df=stock,
            ratios_df=ratios,
        )

        self.assertGreaterEqual(len(trades), 1, "expected at least one trade from synthetic data")
        first = trades.iloc[0]

        # --- concrete contract evidence (from implementation output) ---
        self.assertEqual(first["StockCode"], "AAA")
        self.assertEqual(first["EntryDate"], "2026-01-05")  # D1 signal+entry
        self.assertEqual(first["ExitDate"], "2026-01-07")  # D3 = D1 + 2 sessions
        self.assertEqual(float(first["EntryPrice"]), 100.0)
        self.assertEqual(float(first["ExitPrice"]), 120.0)
        self.assertAlmostEqual(float(first["Return"]), 0.20, places=6)
        self.assertAlmostEqual(float(first["ReturnPct"]), 20.0, places=2)
        # Holding period = 2 unique sessions in the date index (not calendar days)
        entry_ts = pd.Timestamp(first["EntryDate"])
        exit_ts = pd.Timestamp(first["ExitDate"])
        session_gap = int(dates.get_indexer([exit_ts])[0] - dates.get_indexer([entry_ts])[0])
        self.assertEqual(session_gap, 2)
        # No fees/slippage fields — net return == gross return
        self.assertNotIn("Fee", trades.columns)
        self.assertNotIn("Slippage", trades.columns)
        self.assertEqual(metrics["strategy"], "foreign_flow")
        self.assertEqual(metrics["holding_days"], 2)

    def test_future_price_mutation_does_not_change_entry_decision(self):
        """Run A vs Run B: mutate only post-entry prices; entry decision unchanged."""
        dates = pd.bdate_range("2026-01-05", periods=6)
        stock_a = _synthetic_flow_universe(
            dates, aaa_closes=[100.0, 110.0, 120.0, 130.0, 140.0, 150.0]
        )
        ratios = pd.DataFrame(
            [
                {
                    "code": c,
                    "stockName": c,
                    "fsDate": "2025-06-30",
                    "roe": 20.0,
                    "per": 10.0,
                    "deRatio": 0.5,
                    "opini": "WTP",
                    "sharia": "S",
                }
                for c in ("AAA", "BBB")
            ]
        )

        _, trades_a = run_backtest(
            strategy="foreign_flow",
            holding_days=2,
            top_n=1,
            min_turnover_rp=1e8,
            stock_df=stock_a,
            ratios_df=ratios,
        )
        self.assertGreaterEqual(len(trades_a), 1)
        entry_a = trades_a.iloc[0]

        # Run B: identical through entry date; explode only FUTURE closes after D1
        stock_b = stock_a.copy()
        future_mask = (stock_b["StockCode"] == "AAA") & (
            pd.to_datetime(stock_b["Date"]) > pd.Timestamp("2026-01-05")
        )
        stock_b.loc[future_mask, "Close"] = stock_b.loc[future_mask, "Close"] * 10.0
        # Also mutate future foreign flow to try to flip ranking if leaked
        stock_b.loc[future_mask, "ForeignBuy"] = 1.0
        stock_b.loc[future_mask, "ForeignSell"] = 9_999_999.0

        _, trades_b = run_backtest(
            strategy="foreign_flow",
            holding_days=2,
            top_n=1,
            min_turnover_rp=1e8,
            stock_df=stock_b,
            ratios_df=ratios,
        )
        self.assertGreaterEqual(len(trades_b), 1)
        entry_b = trades_b.iloc[0]

        self.assertEqual(entry_a["StockCode"], entry_b["StockCode"])
        self.assertEqual(entry_a["EntryDate"], entry_b["EntryDate"])
        self.assertEqual(float(entry_a["EntryPrice"]), float(entry_b["EntryPrice"]))
        # Exit price MAY differ (future data used for P&L only) — that is expected
        self.assertNotEqual(float(entry_a["ExitPrice"]), float(entry_b["ExitPrice"]))

    def test_later_fundamental_filings_cannot_affect_earlier_entry(self):
        dates = pd.bdate_range("2026-01-05", periods=6)
        stock = _synthetic_flow_universe(dates)
        # On entry D1 only the 2025 filing is known; a 2026-06 filing arrives later
        ratios = pd.DataFrame(
            [
                {
                    "code": "AAA",
                    "stockName": "AAA",
                    "fsDate": "2025-06-30",
                    "roe": 5.0,  # below SHARIA_MIN_ROE default (12) → should NOT pass
                    "per": 10.0,
                    "deRatio": 0.5,
                    "opini": "WTP",
                    "sharia": "S",
                    "priceBV": 1.0,
                },
                {
                    "code": "AAA",
                    "stockName": "AAA",
                    "fsDate": "2026-06-30",
                    "roe": 40.0,  # would pass if leaked
                    "per": 8.0,
                    "deRatio": 0.3,
                    "opini": "WTP",
                    "sharia": "S",
                    "priceBV": 1.0,
                },
            ]
        )
        # Direct screen at entry_date must not see future filing
        early = sharia_value_screen(ratios, as_of="2026-01-05")
        self.assertTrue(early.empty, "low-ROE historical filing must fail screen")

        late = sharia_value_screen(ratios, as_of="2026-12-31")
        self.assertFalse(late.empty)
        self.assertAlmostEqual(float(late.iloc[0]["roe"]), 40.0)

        metrics, trades = run_backtest(
            strategy="sharia_value",
            holding_days=2,
            top_n=1,
            stock_df=stock,
            ratios_df=ratios,
        )
        # First rebalance is on 2026-01-05 — no qualifying PIT filing → no trade that day
        if len(trades) > 0:
            self.assertNotEqual(trades.iloc[0]["EntryDate"], "2026-01-05")
        self.assertIn("total_trades", metrics)

    def test_later_technical_rows_cannot_affect_earlier_indicator(self):
        dates = pd.bdate_range("2026-01-05", periods=40)
        # Steady uptrend through entry; then crash after entry
        closes_a = [100.0 + i for i in range(40)]
        closes_b = list(closes_a)
        closes_b[25:] = [50.0] * (40 - 25)  # crash after index 25

        def _tech_frame(closes: list[float]) -> pd.DataFrame:
            rows = []
            for i, d in enumerate(dates):
                c = closes[i]
                rows.append(
                    {
                        "Date": d.strftime("%Y-%m-%d"),
                        "StockCode": "AAA",
                        "OpenPrice": c,
                        "High": c + 1,
                        "Low": c - 1,
                        "Close": c,
                        "Volume": 1_000_000 + i * 10_000,
                        "Previous": c - 1,
                    }
                )
            return pd.DataFrame(rows)

        entry_idx = 24
        entry_date = dates[entry_idx]
        tech_a = compute_technical_indicators(_tech_frame(closes_a))
        tech_b = compute_technical_indicators(_tech_frame(closes_b))
        row_a = tech_a[tech_a["Date"] == entry_date].iloc[0]
        row_b = tech_b[tech_b["Date"] == entry_date].iloc[0]
        self.assertEqual(row_a["TrendRegime"], row_b["TrendRegime"])
        self.assertAlmostEqual(float(row_a["EMA20"]), float(row_b["EMA20"]), places=2)
        self.assertAlmostEqual(float(row_a["RSI14"]), float(row_b["RSI14"]), places=1)

    def test_historical_feature_lookup_bounded_by_entry_date(self):
        dates = pd.bdate_range("2026-01-05", periods=6)
        stock = _synthetic_flow_universe(dates)
        entry = pd.Timestamp("2026-01-07")
        hist = stock[pd.to_datetime(stock["Date"]) <= entry]
        radar = foreign_flow_radar(hist, window_days=10, min_abs_pct_float=0.0, min_turnover_rp=1e8)
        # Close reflects last session ON OR BEFORE entry (D3), not later bars
        aaa = radar[radar["StockCode"] == "AAA"].iloc[0]
        self.assertEqual(float(aaa["Close"]), 120.0)

        # Full frame with future bars must match when sliced first (backtest pattern)
        full_radar = foreign_flow_radar(
            stock[pd.to_datetime(stock["Date"]) <= entry],
            window_days=10,
            min_abs_pct_float=0.0,
            min_turnover_rp=1e8,
        )
        self.assertEqual(
            float(full_radar[full_radar["StockCode"] == "AAA"].iloc[0]["Close"]), 120.0
        )

    def test_missing_historical_data_does_not_fallback_to_latest_snapshot(self):
        # Only a future undated/later filing exists — PIT as_of must return empty, not latest
        ratios = pd.DataFrame(
            [
                {
                    "code": "ZZZ",
                    "stockName": "ZZZ",
                    "fsDate": "2026-12-31",
                    "roe": 50.0,
                    "per": 5.0,
                    "deRatio": 0.1,
                    "opini": "WTP",
                    "sharia": "S",
                    "priceBV": 1.0,
                },
                {
                    "code": "ZZZ",
                    "stockName": "ZZZ",
                    "fsDate": None,  # undated must not act as snapshot fallback under as_of
                    "roe": 99.0,
                    "per": 1.0,
                    "deRatio": 0.0,
                    "opini": "WTP",
                    "sharia": "S",
                    "priceBV": 1.0,
                },
            ]
        )
        pit = _latest_per_code(ratios, as_of="2026-01-05")
        self.assertTrue(pit.empty)

        screen = sharia_value_screen(ratios, as_of="2026-01-05")
        self.assertTrue(screen.empty)

        dates = pd.bdate_range("2026-01-05", periods=6)
        stock = _synthetic_flow_universe(dates)
        # Inject ZZZ so universe exists but fundamentals are not PIT-available
        zzz_rows = []
        for d in dates:
            zzz_rows.append(
                {
                    "Date": d.strftime("%Y-%m-%d"),
                    "StockCode": "ZZZ",
                    "OpenPrice": 50.0,
                    "High": 51.0,
                    "Low": 49.0,
                    "Close": 50.0,
                    "Volume": 1_000_000,
                    "Value": 5e9,
                    "Previous": 49.0,
                    "ForeignBuy": 1_000_000,
                    "ForeignSell": 100_000,
                    "TradebleShares": 100_000_000,
                }
            )
        stock = pd.concat([stock, pd.DataFrame(zzz_rows)], ignore_index=True)
        _, trades = run_backtest(
            strategy="sharia_value",
            holding_days=2,
            top_n=5,
            stock_df=stock,
            ratios_df=ratios,
        )
        # Must not select ZZZ via undated/future snapshot fallback
        if len(trades) > 0:
            self.assertNotIn("ZZZ", set(trades["StockCode"].tolist()))

    def test_calculate_metrics_empty_and_nan_safe(self):
        empty = calculate_metrics(pd.Series(dtype=float))
        self.assertEqual(empty["total_trades"], 0)
        self.assertEqual(empty["total_return_pct"], 0.0)
        self.assertEqual(empty["sharpe_ratio"], 0.0)
        self.assertIsNone(empty["cagr_pct"])
        self.assertIsNone(empty["alpha_pct"])
        self.assertIsNone(empty["benchmark_return_pct"])

        messy = calculate_metrics(pd.Series([0.01, np.nan, np.inf, -0.02]))
        self.assertEqual(messy["total_trades"], 2)
        self.assertFalse(np.isnan(messy["sharpe_ratio"]))
        self.assertFalse(np.isinf(messy["max_drawdown_pct"]))
        self.assertIsNone(messy["cagr_pct"])
        # Total return must not be re-labeled as CAGR
        self.assertNotEqual(messy["cagr_pct"], messy["total_return_pct"])


if __name__ == "__main__":
    unittest.main()
