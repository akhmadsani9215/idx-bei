"""
Strategy Validation Foundation — reproducibility, isolation, no-signal, one-trade.

Exercises the EXISTING ``run_backtest`` + signal screens only (no second engine).
"""

from __future__ import annotations

import json
import math
import os
import unittest
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

from idx.api import app
from idx.backtest import run_backtest
from idx.core.utils import DATA_DIR


def _flow_frame(
    dates: pd.DatetimeIndex,
    *,
    code: str = "AAA",
    closes: list[float] | None = None,
    foreign_buy: float = 2_000_000.0,
    foreign_sell: float = 100_000.0,
    value: float = 5e9,
) -> pd.DataFrame:
    n = len(dates)
    if closes is None:
        closes = [100.0 + 10.0 * i for i in range(n)]
    rows = []
    for i, d in enumerate(dates):
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
                "Value": value,
                # IDX reference price = prior Close (no corporate action)
                "Previous": float(closes[i - 1]) if i else c,
                "ForeignBuy": foreign_buy,
                "ForeignSell": foreign_sell,
                "TradebleShares": 100_000_000,
            }
        )
    return pd.DataFrame(rows)


def _minimal_ratios(*codes: str) -> pd.DataFrame:
    return pd.DataFrame(
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
                "priceBV": 1.0,
            }
            for c in codes
        ]
    )


def _snapshot_result(metrics: dict, trades: pd.DataFrame) -> dict:
    """Canonical comparable snapshot for reproducibility asserts."""
    t = trades.copy()
    if len(t) > 0:
        t = t.sort_values(["EntryDate", "ExitDate", "StockCode"]).reset_index(drop=True)
        trade_records = t.to_dict(orient="records")
    else:
        trade_records = []
    # Drop non-finite metric floats for stable compare (should already be clean)
    clean_metrics = {}
    for k, v in metrics.items():
        if isinstance(v, float) and not math.isfinite(v):
            clean_metrics[k] = None
        else:
            clean_metrics[k] = v
    return {"metrics": clean_metrics, "trades": trade_records}


class TestStrategyValidationFoundation(unittest.TestCase):
    def test_historical_run_does_not_touch_dashboard_or_live_fx(self):
        """Injected frames must not read network_alpha, details JSON, or live FX."""
        dates = pd.bdate_range("2026-01-05", periods=6)
        stock = _flow_frame(dates, closes=[100.0, 110.0, 120.0, 130.0, 140.0, 150.0])
        ratios = _minimal_ratios("AAA")

        dashboard = os.path.join(DATA_DIR, "network_alpha_data.json")
        details = os.path.join(DATA_DIR, "companyDetailsByKodeEmiten.json")

        def _blocked_load_json(path, *args, **kwargs):
            raise AssertionError(f"unexpected load_json({path!r})")

        def _blocked_usd(*_a, **_k):
            raise AssertionError("unexpected resolve_usd_idr_quote()")

        def _blocked_load_data():
            raise AssertionError("unexpected _load_data() with injected frames")

        with (
            patch("idx.backtest._load_data", side_effect=_blocked_load_data),
            patch("idx.backtest.load_json", side_effect=_blocked_load_json),
            patch("idx.backtest.resolve_usd_idr_quote", side_effect=_blocked_usd),
        ):
            metrics, trades = run_backtest(
                strategy="foreign_flow",
                holding_days=2,
                top_n=1,
                min_turnover_rp=1e8,
                stock_df=stock,
                ratios_df=ratios,
                actions_df=pd.DataFrame(),
            )
        self.assertGreaterEqual(metrics["total_trades"], 1)
        # Explicit: result came from injected history, not dashboard tickers
        self.assertEqual(set(trades["StockCode"].unique()), {"AAA"})
        # Document isolation: dashboard / details paths exist but were not used
        self.assertTrue(isinstance(dashboard, str) and isinstance(details, str))

    def test_identical_inputs_are_reproducible(self):
        dates = pd.bdate_range("2026-01-05", periods=8)
        stock = pd.concat(
            [
                _flow_frame(
                    dates,
                    code="AAA",
                    closes=[100 + i for i in range(8)],
                    foreign_buy=3e6,
                    foreign_sell=1e5,
                ),
                _flow_frame(
                    dates,
                    code="BBB",
                    closes=[200 + i for i in range(8)],
                    foreign_buy=2.5e6,
                    foreign_sell=1e5,
                ),
            ],
            ignore_index=True,
        )
        ratios = _minimal_ratios("AAA", "BBB")
        kwargs = dict(
            strategy="foreign_flow",
            holding_days=2,
            top_n=2,
            min_turnover_rp=1e8,
            stock_df=stock,
            ratios_df=ratios,
            actions_df=pd.DataFrame(),
            stop_loss_pct=None,
            take_profit_pct=None,
        )
        a = _snapshot_result(*run_backtest(**kwargs))
        b = _snapshot_result(*run_backtest(**kwargs))
        self.assertEqual(a, b)
        self.assertGreater(a["metrics"]["total_trades"], 0)
        # Deterministic ranking: AAA has stronger foreign inflow than BBB
        first_entry = a["trades"][0]["EntryDate"]
        first_basket = [t["StockCode"] for t in a["trades"] if t["EntryDate"] == first_entry]
        self.assertEqual(first_basket[0], "AAA")
        self.assertEqual(first_basket, ["AAA", "BBB"])

    def test_no_signal_produces_api_safe_empty_result(self):
        """Zero NFF → foreign_flow screen empty → no fabricated trades/equity dates."""
        dates = pd.bdate_range("2026-01-05", periods=6)
        # NFF = 0 → |PctFloat| = 0 < default 0.5% filter
        stock = _flow_frame(
            dates,
            closes=[100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
            foreign_buy=500_000.0,
            foreign_sell=500_000.0,
        )
        ratios = _minimal_ratios("AAA")
        metrics, trades = run_backtest(
            strategy="foreign_flow",
            holding_days=2,
            top_n=5,
            min_turnover_rp=1e8,
            stock_df=stock,
            ratios_df=ratios,
        )
        self.assertEqual(len(trades), 0)
        self.assertEqual(metrics["total_trades"], 0)
        self.assertEqual(metrics["total_return_pct"], 0.0)
        self.assertIsNone(metrics["cagr_pct"])
        self.assertIsNone(metrics["alpha_pct"])
        self.assertEqual(metrics["strategy"], "foreign_flow")

        with patch("idx.backtest.run_backtest", return_value=(metrics, trades)):
            client = TestClient(app)
            resp = client.post(
                "/api/backtest",
                json={"strategy": "foreign_flow", "holding_days": 2, "top_n": 5},
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["trades"], [])
        self.assertEqual(data["equity_curve"], [])
        self.assertEqual(data["metrics"]["total_trades"], 0)
        self.assertIsNone(data["metrics"]["cagr_pct"])
        # No NaN/Inf leakage
        payload = json.dumps(data)
        self.assertNotIn("NaN", payload)
        self.assertNotIn("Infinity", payload)

    def test_single_signal_single_trade_evidence(self):
        """Exactly one foreign_flow selection → one trade from the real engine."""
        # 4 sessions, holding=2 → only i=0 rebalance (range(0, 2, 2))
        dates = pd.bdate_range("2026-01-05", periods=4)
        # D1=100, D2=110, D3=120, D4=130 — entry D1, exit D3
        stock = _flow_frame(
            dates,
            code="AAA",
            closes=[100.0, 110.0, 120.0, 130.0],
            foreign_buy=2_000_000.0,
            foreign_sell=100_000.0,
        )
        ratios = _minimal_ratios("AAA")
        metrics, trades = run_backtest(
            strategy="foreign_flow",
            holding_days=2,
            top_n=1,
            min_turnover_rp=1e8,
            stock_df=stock,
            ratios_df=ratios,
            start_date="2026-01-05",
            end_date="2026-01-08",
        )
        self.assertEqual(len(trades), 1, "expected exactly one trade")
        self.assertEqual(metrics["total_trades"], 1)
        row = trades.iloc[0]
        # --- evidence from actual engine ---
        self.assertEqual(row["StockCode"], "AAA")
        self.assertEqual(row["EntryDate"], "2026-01-05")  # signal + entry session
        self.assertEqual(row["ExitDate"], "2026-01-07")
        self.assertEqual(float(row["EntryPrice"]), 100.0)
        self.assertEqual(float(row["ExitPrice"]), 120.0)
        self.assertAlmostEqual(float(row["Return"]), 0.20, places=6)
        self.assertEqual(metrics["holding_days"], 2)

    def test_date_range_respected_and_outside_data_ignored(self):
        dates = pd.bdate_range("2026-01-05", periods=10)
        # Strong inflow early; reverse to outflow after window — must not affect in-range run
        stock = _flow_frame(
            dates,
            closes=[100.0 + i for i in range(10)],
            foreign_buy=2e6,
            foreign_sell=1e5,
        )
        # Mutate only sessions after end_date
        late = pd.to_datetime(stock["Date"]) > pd.Timestamp("2026-01-12")
        stock = stock.copy()
        stock.loc[late, "ForeignBuy"] = 1.0
        stock.loc[late, "ForeignSell"] = 9_999_999.0
        stock.loc[late, "Close"] = 1.0

        ratios = _minimal_ratios("AAA")
        m1, t1 = run_backtest(
            strategy="foreign_flow",
            holding_days=2,
            top_n=1,
            min_turnover_rp=1e8,
            stock_df=stock,
            ratios_df=ratios,
            start_date="2026-01-05",
            end_date="2026-01-12",
        )
        # Identical window without late mutations
        stock_early = stock[pd.to_datetime(stock["Date"]) <= "2026-01-12"].copy()
        m2, t2 = run_backtest(
            strategy="foreign_flow",
            holding_days=2,
            top_n=1,
            min_turnover_rp=1e8,
            stock_df=stock_early,
            ratios_df=ratios,
            start_date="2026-01-05",
            end_date="2026-01-12",
        )
        self.assertEqual(_snapshot_result(m1, t1), _snapshot_result(m2, t2))
        if len(t1) > 0:
            self.assertTrue((t1["EntryDate"] >= "2026-01-05").all())
            self.assertTrue((t1["ExitDate"] <= "2026-01-12").all())

    def test_invalid_parameters_return_empty_not_crash(self):
        dates = pd.bdate_range("2026-01-05", periods=6)
        stock = _flow_frame(dates)
        ratios = _minimal_ratios("AAA")
        for holding, top in ((0, 1), (-1, 1), (2, 0), (2, -5)):
            metrics, trades = run_backtest(
                strategy="foreign_flow",
                holding_days=holding,
                top_n=top,
                stock_df=stock,
                ratios_df=ratios,
            )
            self.assertEqual(len(trades), 0)
            self.assertEqual(metrics["total_trades"], 0)
            self.assertIn("strategy", metrics)

        metrics, trades = run_backtest(
            strategy="foreign_flow",
            holding_days=2,
            top_n=1,
            start_date="2026-02-01",
            end_date="2026-01-01",
            stock_df=stock,
            ratios_df=ratios,
        )
        self.assertEqual(len(trades), 0)
        self.assertEqual(metrics["total_trades"], 0)

        metrics, trades = run_backtest(
            strategy="not_a_real_strategy",
            holding_days=2,
            top_n=1,
            stock_df=stock,
            ratios_df=ratios,
        )
        self.assertEqual(len(trades), 0)
        self.assertEqual(metrics["strategy"], "not_a_real_strategy")


if __name__ == "__main__":
    unittest.main()
