"""
Tests for Vectorized Backtest Strategy Simulator and performance metrics.
"""

import unittest

import numpy as np
import pandas as pd

from idx.backtest import calculate_metrics, run_backtest


class TestBacktest(unittest.TestCase):
    def setUp(self):
        dates = pd.date_range("2026-01-01", periods=60, freq="B")
        rows = []
        for ticker in ["BBCA", "BBRI", "TLKM", "ASII"]:
            base = 5000.0
            for i, d in enumerate(dates):
                base += np.sin(i / 3.0) * 40 + 5
                rows.append(
                    {
                        "Date": d.strftime("%Y-%m-%d"),
                        "StockCode": ticker,
                        "OpenPrice": base - 10,
                        "High": base + 30,
                        "Low": base - 20,
                        "Close": base,
                        "Volume": 2_000_000,
                        "Value": 2_000_000 * base,
                        "Previous": base - 5,
                        "ForeignBuy": 1_200_000,
                        "ForeignSell": 400_000,
                        "TradebleShares": 100_000_000,
                    }
                )
        self.stock_df = pd.DataFrame(rows)
        self.ratios_df = pd.DataFrame(
            [
                {
                    "code": t,
                    "stockName": t,
                    "fsDate": "2026-06-30",
                    "roe": 20.0,
                    "per": 10.0,
                    "deRatio": 0.5,
                    "opini": "WTP",
                    "sharia": "S",
                }
                for t in ["BBCA", "BBRI", "TLKM", "ASII"]
            ]
        )

    def test_calculate_metrics(self):
        returns = pd.Series([0.05, -0.02, 0.04, 0.08, -0.01, 0.03])
        metrics = calculate_metrics(returns)
        self.assertIn("total_return_pct", metrics)
        self.assertIn("sharpe_ratio", metrics)
        self.assertIn("win_rate_pct", metrics)
        self.assertEqual(metrics["total_trades"], 6)
        self.assertGreater(metrics["win_rate_pct"], 50.0)
        self.assertIsNone(metrics["cagr_pct"])
        self.assertIsNone(metrics["alpha_pct"])

    def test_calculate_metrics_edge_cases(self):
        one = calculate_metrics(pd.Series([0.10]))
        self.assertEqual(one["total_trades"], 1)
        self.assertAlmostEqual(one["total_return_pct"], 10.0, places=2)
        self.assertEqual(one["win_rate_pct"], 100.0)
        self.assertIsNone(one["cagr_pct"])

        all_win = calculate_metrics(pd.Series([0.01, 0.02, 0.03]))
        self.assertEqual(all_win["win_rate_pct"], 100.0)

        all_lose = calculate_metrics(pd.Series([-0.01, -0.02, -0.03]))
        self.assertEqual(all_lose["win_rate_pct"], 0.0)
        self.assertLess(all_lose["total_return_pct"], 0.0)

        zero_var = calculate_metrics(pd.Series([0.01, 0.01, 0.01]))
        self.assertEqual(zero_var["sharpe_ratio"], 0.0)  # std == 0 → sharpe 0
        self.assertFalse(np.isnan(zero_var["sharpe_ratio"]))

        with_bench = calculate_metrics(
            pd.Series([0.05, 0.05]), benchmark_returns=pd.Series([0.01, 0.01])
        )
        self.assertIsNotNone(with_bench["benchmark_return_pct"])
        self.assertIsNotNone(with_bench["alpha_pct"])
        self.assertIsNone(with_bench["cagr_pct"])

    def test_portfolio_period_metrics_match_equal_weight_exit_groups(self):
        """Parallel same-ExitDate trades must average, not chain-compound."""
        from idx.backtest import _portfolio_period_returns

        trades = pd.DataFrame(
            {
                "ExitDate": ["2026-01-07", "2026-01-07"],
                "Return": [0.20, 0.10],
            }
        )
        period = _portfolio_period_returns(trades)
        self.assertEqual(len(period), 1)
        self.assertAlmostEqual(float(period.iloc[0]), 0.15, places=6)
        m = calculate_metrics(period)
        self.assertAlmostEqual(m["total_return_pct"], 15.0, places=2)

    def test_run_backtest_foreign_flow(self):
        metrics, trades = run_backtest(
            strategy="foreign_flow",
            holding_days=10,
            top_n=2,
            stock_df=self.stock_df,
            ratios_df=self.ratios_df,
        )
        self.assertIn("total_return_pct", metrics)
        self.assertEqual(metrics["strategy"], "foreign_flow")
        self.assertGreaterEqual(len(trades), 1)

    def test_run_backtest_with_stop_loss_and_take_profit(self):
        metrics, trades = run_backtest(
            strategy="foreign_flow",
            holding_days=10,
            top_n=2,
            stop_loss_pct=5.0,
            take_profit_pct=10.0,
            stock_df=self.stock_df,
            ratios_df=self.ratios_df,
        )
        self.assertIn("total_return_pct", metrics)
        self.assertGreaterEqual(len(trades), 1)

    def test_run_backtest_sharia_and_alpha(self):
        m_sharia, t_sharia = run_backtest(
            strategy="sharia_value",
            holding_days=10,
            top_n=2,
            stock_df=self.stock_df,
            ratios_df=self.ratios_df,
        )
        self.assertIn("total_return_pct", m_sharia)

        m_alpha, t_alpha = run_backtest(
            strategy="composite_alpha",
            holding_days=10,
            top_n=2,
            stock_df=self.stock_df,
            ratios_df=self.ratios_df,
        )
        self.assertIn("total_return_pct", m_alpha)

    def test_run_backtest_bandarmology(self):
        m_bandar, t_bandar = run_backtest(
            strategy="bandarmology",
            holding_days=10,
            top_n=2,
            stock_df=self.stock_df,
            ratios_df=self.ratios_df,
        )
        self.assertIn("total_return_pct", m_bandar)

    def test_run_backtest_stealth_accumulation(self):
        m_stealth, t_stealth = run_backtest(
            strategy="stealth_accumulation",
            holding_days=10,
            top_n=2,
            stock_df=self.stock_df,
            ratios_df=self.ratios_df,
        )
        self.assertIn("total_return_pct", m_stealth)
        self.assertEqual(m_stealth.get("strategy"), "stealth_accumulation")

    def test_run_backtest_volatility_parity(self):
        metrics, trades = run_backtest(
            strategy="foreign_flow",
            holding_days=10,
            top_n=2,
            position_sizing="volatility_parity",
            stock_df=self.stock_df,
            ratios_df=self.ratios_df,
        )
        self.assertIn("total_return_pct", metrics)
        self.assertEqual(metrics["position_sizing"], "volatility_parity")
        self.assertGreaterEqual(len(trades), 1)
        self.assertIn("Weight", trades.columns)
        self.assertIn("WeightedReturn", trades.columns)


if __name__ == "__main__":
    unittest.main()
