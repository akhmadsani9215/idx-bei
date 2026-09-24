"""
Tests for FastAPI REST & WebSocket Microservice endpoints.
"""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from idx.api import app


class TestAPI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_endpoint(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["service"], "idx-bei-api")

    def test_sql_guardrails(self):
        response = self.client.post("/api/query/sql", json={"sql": "DROP TABLE test"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Only read-only SELECT queries are allowed", response.json()["detail"])

    def test_sql_valid_query(self):
        response = self.client.post(
            "/api/query/sql", json={"sql": "SELECT 100 AS num, 'IDX' AS exchange"}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data[0]["num"], 100)
        self.assertEqual(data[0]["exchange"], "IDX")

    def test_get_ubo(self):
        response = self.client.get("/api/graph/ubo/BBCA")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["ticker"], "BBCA")

    def test_stealth_accumulation_endpoint(self):
        response = self.client.get("/api/stealth-accumulation")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("smart_money_delta", data)
        self.assertIn("signal", data)
        self.assertEqual(data["signal"], "UNAVAILABLE")
        self.assertIsNone(data["smart_money_delta"])

    def test_backtest_endpoint(self):
        response = self.client.post(
            "/api/backtest",
            json={
                "strategy": "foreign_flow",
                "holding_days": 10,
                "top_n": 5,
                "min_turnover_rp": 1000000.0,
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("metrics", data)
        self.assertIn("equity_curve", data)
        self.assertIn("trades", data)
        # Zero-trade runs may have an empty equity curve (no fabricated placeholder date).
        self.assertIsInstance(data["equity_curve"], list)
        # CAGR must never silently equal total return
        metrics = data["metrics"]
        self.assertTrue(
            metrics.get("cagr_pct") is None
            or metrics.get("cagr_pct") != metrics.get("total_return_pct")
        )

    def test_backtest_result_contract_synthetic(self):
        """Deterministic engine → API contract: trades, dates, numerics, CAGR safety."""
        import pandas as pd

        trades = pd.DataFrame(
            [
                {
                    "EntryDate": "2026-01-05",
                    "ExitDate": "2026-01-07",
                    "StockCode": "AAA",
                    "EntryPrice": 100.0,
                    "ExitPrice": 120.0,
                    "ReturnPct": 20.0,
                    "Return": 0.20,
                },
                {
                    "EntryDate": "2026-01-05",
                    "ExitDate": "2026-01-07",
                    "StockCode": "BBB",
                    "EntryPrice": 50.0,
                    "ExitPrice": 55.0,
                    "ReturnPct": 10.0,
                    "Return": 0.10,
                },
            ]
        )
        # Equal-weight period return = 0.15 → total_return_pct = 15.0
        metrics = {
            "total_return_pct": 15.0,
            "cagr_pct": None,
            "sharpe_ratio": 1.2,
            "sortino_ratio": 1.1,
            "max_drawdown_pct": 0.0,
            "win_rate_pct": 100.0,
            "profit_factor": 999.0,
            "total_trades": 2,
            "avg_trade_return_pct": 15.0,
            "benchmark_return_pct": None,
            "alpha_pct": None,
            "strategy": "foreign_flow",
            "holding_days": 2,
        }

        with patch("idx.backtest.run_backtest", return_value=(metrics, trades)):
            response = self.client.post(
                "/api/backtest",
                json={
                    "strategy": "foreign_flow",
                    "holding_days": 2,
                    "top_n": 2,
                    "min_turnover_rp": 1e8,
                },
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()

        m = data["metrics"]
        self.assertIsNone(m["cagr_pct"])
        self.assertNotEqual(m["cagr_pct"], m["total_return_pct"])
        self.assertEqual(m["total_trades"], 2)
        self.assertEqual(m["trades_returned"], 2)
        self.assertEqual(m["total_return_pct"], 15.0)
        self.assertIsNone(m["alpha_pct"])

        self.assertEqual(len(data["trades"]), 2)
        t0 = data["trades"][0]
        self.assertRegex(t0["EntryDate"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertRegex(t0["ExitDate"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertIsInstance(t0["EntryPrice"], (int, float))
        self.assertIsInstance(t0["ExitPrice"], (int, float))
        self.assertIsInstance(t0["Return"], (int, float))
        self.assertAlmostEqual(
            float(t0["Return"]), (t0["ExitPrice"] - t0["EntryPrice"]) / t0["EntryPrice"], places=6
        )

        # Equity curve: base 100 then one exit session at 115 (mean return 15%)
        self.assertGreaterEqual(len(data["equity_curve"]), 2)
        self.assertEqual(data["equity_curve"][0]["value"], 100.0)
        self.assertAlmostEqual(data["equity_curve"][-1]["value"], 115.0, places=2)
        times = [p["time"] for p in data["equity_curve"]]
        self.assertEqual(times, sorted(times))

    def test_backtest_zero_trades_empty_equity_curve(self):
        import pandas as pd

        metrics = {
            "total_return_pct": 0.0,
            "cagr_pct": None,
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "max_drawdown_pct": 0.0,
            "win_rate_pct": 0.0,
            "profit_factor": 0.0,
            "total_trades": 0,
            "avg_trade_return_pct": 0.0,
            "benchmark_return_pct": None,
            "alpha_pct": None,
            "strategy": "foreign_flow",
            "holding_days": 10,
        }
        with patch("idx.backtest.run_backtest", return_value=(metrics, pd.DataFrame())):
            response = self.client.post(
                "/api/backtest",
                json={"strategy": "foreign_flow", "holding_days": 10, "top_n": 5},
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["equity_curve"], [])
        self.assertEqual(data["trades"], [])
        self.assertEqual(data["metrics"]["total_trades"], 0)
        self.assertIsNone(data["metrics"]["cagr_pct"])

    def test_backtester_tab_never_displays_cagr_as_total_return(self):
        """Frontend source guard: Total Strategy Return must not use cagr_pct."""
        import os

        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "frontend",
            "src",
            "components",
            "BacktesterTab.tsx",
        )
        path = os.path.abspath(path)
        with open(path, encoding="utf-8") as f:
            src = f.read()
        self.assertIn("total_return_pct", src)
        self.assertIn("not CAGR", src)
        # Must not render cagr_pct into the KPI value
        self.assertNotIn("metrics?.cagr_pct}", src)
        self.assertNotIn("metrics.cagr_pct}", src)
        self.assertNotIn(">CAGR<", src)
        self.assertNotIn("'CAGR'", src)
        self.assertNotIn('"CAGR"', src)

    def test_broadcast_endpoint(self):
        response = self.client.post("/api/broadcast", json={"type": "test_event", "val": 123})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "broadcast_sent")

    def test_websocket_stream(self):
        with self.client.websocket_connect("/ws/stream") as ws:
            msg = ws.receive_json()
            self.assertEqual(msg["type"], "handshake")
            self.assertEqual(msg["status"], "connected")
            ws.send_json({"type": "ping"})
            pong = ws.receive_json()
            self.assertEqual(pong["type"], "pong")

    def test_drift_endpoint(self):
        response = self.client.get("/api/drift")
        self.assertEqual(response.status_code, 200)

    def test_root_redirect(self):
        response = self.client.get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers.get("location"), "/dashboard/")

    def test_dashboard_endpoint(self):
        response = self.client.get("/dashboard/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers.get("content-type", ""))

    def test_sql_query_valid(self):
        response = self.client.post("/api/query/sql", json={"sql": "SELECT 42 AS num", "limit": 10})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [{"num": 42}])

    def test_sql_query_disallowed(self):
        response = self.client.post("/api/query/sql", json={"sql": "DROP TABLE test", "limit": 10})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Only read-only", response.json()["detail"])

    def test_sql_query_error(self):
        response = self.client.post(
            "/api/query/sql", json={"sql": "SELECT * FROM nonexistent_table_xyz", "limit": 10}
        )
        self.assertEqual(response.status_code, 400)

    def test_dividend_analysis_404(self):
        with patch("idx.dividend.analyze_stock_dividend") as mock_div:
            mock_div.return_value = {"has_dividend": False, "message": "No dividend"}
            response = self.client.get("/api/dividend/UNKNOWN")
            self.assertEqual(response.status_code, 404)

    def test_dividend_analysis_200(self):
        with patch("idx.dividend.analyze_stock_dividend") as mock_div:
            mock_div.return_value = {"has_dividend": True, "ticker": "BBCA", "yield": 4.5}
            response = self.client.get("/api/dividend/BBCA")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["ticker"], "BBCA")

    def test_dividend_screen(self):
        with patch("idx.dividend.screen_upcoming_dividends") as mock_screen:
            import pandas as pd

            mock_screen.return_value = pd.DataFrame([{"ticker": "BBCA", "yield": 4.5}])
            response = self.client.get("/api/dividend?min_yield=1.0")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.json()), 1)

    def test_graph_ubo(self):
        with patch("idx.api.get_ubo_tree") as mock_ubo:
            mock_ubo.return_value = {"ticker": "BBCA", "ultimate_owners": ["Djarum"]}
            response = self.client.get("/api/graph/ubo/BBCA")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["ticker"], "BBCA")

    def test_signals_endpoint(self):
        with patch("idx.api.build_briefing") as mock_brief:
            mock_brief.return_value = {"date": "2026-08-07", "signals": {}}
            response = self.client.get("/api/signals")
            self.assertEqual(response.status_code, 200)

    def test_stock_data_endpoints(self):
        import pandas as pd

        with patch("idx.api.query_dataset") as mock_query:
            # 404
            mock_query.return_value = pd.DataFrame()
            resp_404 = self.client.get("/api/stock/NOTFOUND")
            self.assertEqual(resp_404.status_code, 404)

            # 200
            mock_query.return_value = pd.DataFrame(
                [{"StockCode": "BBCA", "Date": "2026-08-01", "Close": 10000, "Volume": 5000000}]
            )
            resp_200 = self.client.get("/api/stock/BBCA")
            self.assertEqual(resp_200.status_code, 200)
            self.assertEqual(resp_200.json()["ticker"], "BBCA")

    def test_broker_flow_endpoints(self):
        with (
            patch("os.path.exists", return_value=False),
            patch("idx.core.timeseries.read_dataset") as mock_read,
        ):
            import pandas as pd

            mock_read.return_value = pd.DataFrame()
            resp_404 = self.client.get("/api/broker-flow")
            self.assertEqual(resp_404.status_code, 404)

    def test_graph_endpoints(self):
        with (
            patch("idx.api.get_company_network") as mock_net,
            patch("idx.api.calculate_board_centrality") as mock_cent,
            patch("idx.api.detect_cross_holdings") as mock_cross,
        ):
            import pandas as pd

            # network 200
            mock_net.return_value = {"ticker": "BBCA", "nodes": [{"id": "BBCA"}], "edges": []}
            resp = self.client.get("/api/graph/network/BBCA")
            self.assertEqual(resp.status_code, 200)

            # network 404
            mock_net.return_value = {"ticker": "XYZ", "nodes": []}
            resp_404 = self.client.get("/api/graph/network/XYZ")
            self.assertEqual(resp_404.status_code, 404)

            # centrality 200
            mock_cent.return_value = pd.DataFrame([{"insider": "Edwin", "board_seats": 5}])
            resp_cent = self.client.get("/api/graph/centrality")
            self.assertEqual(resp_cent.status_code, 200)
            self.assertEqual(len(resp_cent.json()), 1)

            # cross-holdings 200
            mock_cross.return_value = [{"controller": "Astra", "companies": ["ASII", "UNTR"]}]
            resp_cross = self.client.get("/api/graph/cross-holdings")
            self.assertEqual(resp_cross.status_code, 200)
            self.assertEqual(len(resp_cross.json()), 1)

    def test_dashboard_data_endpoint(self):
        resp = self.client.get("/api/dashboard-data")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("companies", data)
        self.assertIn("super_insiders", data)
        self.assertIn("conglomerates", data)

    def test_companies_endpoint(self):
        resp = self.client.get("/api/companies")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsInstance(data, list)

    def test_stock_blocks_endpoint(self):
        # Existing ticker (e.g. BBCA)
        resp = self.client.get("/api/stock/BBCA/blocks")
        if resp.status_code == 200:
            data = resp.json()
            self.assertEqual(data["ticker"], "BBCA")
            self.assertIn("blocks", data)
            self.assertIn("non_regular_value_rp", data)
            self.assertIn("smart_accumulation_ratio", data)
            # Honesty: whale / smart-accumulation never fabricated as 0.
            self.assertIsNone(data.get("total_whale_value_rp"))
            self.assertFalse(data.get("broker_blocks_available"))
        # Invalid ticker form → 400 (sanitize); unknown-but-valid form → 404
        resp_bad = self.client.get("/api/stock/INVALID_ZZZZ/blocks")
        self.assertEqual(resp_bad.status_code, 400)
        resp_404 = self.client.get("/api/stock/ZZZZ/blocks")
        self.assertIn(resp_404.status_code, (404, 200))  # 200 only if synthetic data present


if __name__ == "__main__":
    unittest.main()
