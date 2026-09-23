"""
Tests for Data Ingestion Status, Gap Detection, and Backfill Recommendations.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from idx.api import app
from idx.ingestion import (
    build_freshness_contract,
    calculate_backfill_recommendations,
    detect_timeseries_gaps,
    get_dataset_inventory,
    get_full_ingestion_status,
    get_idx_holidays,
    run_async_ingestion_job,
)


def _minimal_inventory(
    stock_end: str | None = "2026-09-22",
    parquet_modified: str | None = "2026-09-22T18:00:00",
) -> dict:
    return {
        "timeseries": {
            "stock_summary": {
                "total_dates": 10,
                "start_date": "2026-09-01",
                "end_date": stock_end,
            },
            "broker_summary": {
                "total_dates": 10,
                "start_date": "2026-09-01",
                "end_date": stock_end,
            },
            "index_summary": {
                "total_dates": 10,
                "start_date": "2026-09-01",
                "end_date": stock_end,
            },
        },
        "parquet_exports": {
            "stock_summary": {"modified_iso": parquet_modified},
            "broker_summary": {"modified_iso": parquet_modified},
            "index_summary": {"modified_iso": parquet_modified},
        },
    }


class TestIngestionStatus(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_get_dataset_inventory(self):
        inv = get_dataset_inventory()
        self.assertIn("timeseries", inv)
        self.assertIn("stock_summary", inv["timeseries"])
        self.assertIn("broker_summary", inv["timeseries"])
        self.assertIn("index_summary", inv["timeseries"])
        self.assertIn("parquet_exports", inv)
        self.assertIn("fundamental_snapshots", inv)
        self.assertIn("total_listed_companies", inv["fundamental_snapshots"])
        self.assertIn("ksei_drift", inv)
        self.assertIn("system", inv)

    def test_detect_timeseries_gaps(self):
        res = detect_timeseries_gaps(
            dataset="stock_summary",
            start_date="2026-01-01",
            end_date="2026-09-08",
        )
        self.assertEqual(res["dataset"], "stock_summary")
        self.assertGreater(res["total_calendar_weekdays"], 150)
        self.assertGreater(res["official_holidays_count"], 10)
        self.assertIsInstance(res["official_holidays"], list)
        self.assertIsInstance(res["true_missing_trading_days"], list)
        self.assertGreaterEqual(res["coverage_percentage"], 0.0)
        self.assertLessEqual(res["coverage_percentage"], 100.0)

    def test_calculate_backfill_recommendations(self):
        recs = calculate_backfill_recommendations(current_date="2026-09-08")
        self.assertIn("summary", recs)
        self.assertIn("tiers", recs)
        self.assertEqual(len(recs["tiers"]), 4)

        tier_ids = [t["id"] for t in recs["tiers"]]
        self.assertIn("tier_1_immediate_gap_repair", tier_ids)
        self.assertIn("tier_2_one_year_baseline", tier_ids)
        self.assertIn("tier_3_three_year_multicycle", tier_ids)
        self.assertIn("tier_4_five_year_macro", tier_ids)

        tier2 = next(t for t in recs["tiers"] if t["tier"] == 2)
        self.assertEqual(tier2["priority"], "RECOMMENDED (BEST VALUE)")
        self.assertGreater(tier2["trading_days_to_fetch"], 200)
        self.assertIn("uv run idx backfill", tier2["recommended_cli_commands"][0])

    def test_get_full_ingestion_status(self):
        full = get_full_ingestion_status()
        self.assertIn(full["status"], ["healthy", "warning", "critical"])
        self.assertIsInstance(full["health_score"], (int, float))
        self.assertGreaterEqual(full["health_score"], 0)
        self.assertLessEqual(full["health_score"], 100)
        self.assertIn("inventory", full)
        self.assertIn("gaps", full)
        self.assertIn("recommendations", full)
        self.assertIn("freshness", full)
        freshness = full["freshness"]
        self.assertIn("last_successful_ingestion", freshness)
        self.assertIn("market_data", freshness)
        self.assertIn("screener_snapshot", freshness)
        self.assertIn("status", freshness)
        self.assertIn("screener_lagging", freshness)
        self.assertIn(freshness["status"], ["current", "screener_stale", "screener_missing", "unknown"])

    def test_api_ingestion_status_endpoint(self):
        resp = self.client.get("/api/system/ingestion-status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("status", data)
        self.assertIn("health_score", data)
        self.assertIn("inventory", data)
        self.assertIn("gaps", data)
        self.assertIn("recommendations", data)
        self.assertIn("freshness", data)
        self.assertIn("last_successful_ingestion", data["freshness"])
        self.assertIn("screener_snapshot", data["freshness"])

    def test_freshness_stale_screener_when_ingestion_newer(self):
        with tempfile.TemporaryDirectory() as tmp:
            alpha_path = os.path.join(tmp, "network_alpha_data.json")
            with open(alpha_path, "w", encoding="utf-8") as f:
                json.dump({"companies": [], "last_updated": "2026-09-20 10:00:00"}, f)
            # Force older mtime than ingestion evidence
            old = 1_700_000_000.0  # fixed epoch
            os.utime(alpha_path, (old, old))

            jobs = {
                "job-1": {
                    "job_id": "job-1",
                    "type": "daily",
                    "status": "completed",
                    "completed_at": "2026-09-22T18:30:00",
                    "created_at": "2026-09-22T18:00:00",
                }
            }
            freshness = build_freshness_contract(
                _minimal_inventory(parquet_modified="2026-09-22T18:00:00"),
                base_dir=tmp,
                jobs=jobs,
            )
            self.assertEqual(freshness["status"], "screener_stale")
            self.assertTrue(freshness["screener_lagging"])
            self.assertIsNotNone(freshness["warning"])
            self.assertTrue(freshness["last_successful_ingestion"]["available"])
            self.assertEqual(freshness["last_successful_ingestion"]["completed_at"], "2026-09-22T18:30:00")

    def test_freshness_current_when_screener_not_behind(self):
        with tempfile.TemporaryDirectory() as tmp:
            alpha_path = os.path.join(tmp, "network_alpha_data.json")
            with open(alpha_path, "w", encoding="utf-8") as f:
                json.dump({"companies": [], "last_updated": "2026-09-22 19:00:00"}, f)
            # Newer mtime than ingestion evidence
            new = 2_000_000_000.0
            os.utime(alpha_path, (new, new))

            jobs = {
                "job-1": {
                    "job_id": "job-1",
                    "type": "daily",
                    "status": "completed",
                    "completed_at": "2026-09-22T18:30:00",
                    "created_at": "2026-09-22T18:00:00",
                }
            }
            freshness = build_freshness_contract(
                _minimal_inventory(parquet_modified="2026-09-22T18:00:00"),
                base_dir=tmp,
                jobs=jobs,
            )
            self.assertEqual(freshness["status"], "current")
            self.assertFalse(freshness["screener_lagging"])
            self.assertIsNone(freshness["warning"])

    def test_freshness_does_not_claim_success_without_completed_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            alpha_path = os.path.join(tmp, "network_alpha_data.json")
            with open(alpha_path, "w", encoding="utf-8") as f:
                json.dump({"companies": [], "last_updated": "2026-09-22 19:00:00"}, f)

            jobs = {
                "job-running": {
                    "job_id": "job-running",
                    "type": "daily",
                    "status": "running",
                    "completed_at": None,
                    "created_at": "2026-09-22T18:00:00",
                },
                "job-failed": {
                    "job_id": "job-failed",
                    "type": "daily",
                    "status": "failed",
                    "completed_at": "2026-09-22T18:10:00",
                    "created_at": "2026-09-22T18:00:00",
                },
            }
            freshness = build_freshness_contract(
                _minimal_inventory(),
                base_dir=tmp,
                jobs=jobs,
            )
            self.assertFalse(freshness["last_successful_ingestion"]["available"])
            self.assertIsNone(freshness["last_successful_ingestion"]["completed_at"])

    def test_api_trigger_ingestion_and_jobs_list(self):
        resp = self.client.post(
            "/api/system/trigger-ingestion",
            json={"job_type": "daily", "date": "20260908"},
        )
        self.assertEqual(resp.status_code, 200)
        job_data = resp.json()
        self.assertIn("job_id", job_data)
        self.assertEqual(job_data["status"], "scheduled")

        # Query recent jobs
        jobs_resp = self.client.get("/api/system/jobs")
        self.assertEqual(jobs_resp.status_code, 200)
        self.assertIsInstance(jobs_resp.json(), list)

        # Query specific job
        job_detail = self.client.get(f"/api/system/jobs/{job_data['job_id']}")
        self.assertEqual(job_detail.status_code, 200)
        self.assertEqual(job_detail.json()["job_id"], job_data["job_id"])

    def test_api_get_invalid_job(self):
        resp = self.client.get("/api/system/jobs/nonexistent-job-9999")
        self.assertEqual(resp.status_code, 404)

    @patch("idx.ingestion.refresh_screener_snapshot", return_value={"status": "completed"})
    @patch("idx.pipelines.daily.ingest_daily", return_value={"status": "ok"})
    def test_run_async_ingestion_job_daily_screener_success(self, mock_ingest, mock_screener):
        import asyncio

        callback = AsyncMock()
        res = asyncio.run(
            run_async_ingestion_job(
                job_id="test-job-screener-ok",
                job_type="daily",
                params={"date": "20260908"},
                broadcast_callback=callback,
            )
        )
        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["progress_pct"], 100)
        mock_ingest.assert_called_once()
        mock_screener.assert_called_once()
        self.assertEqual(res["results"]["status"], "ok")
        self.assertEqual(res["results"]["screener_refresh"]["status"], "completed")
        self.assertIn("screener snapshot refreshed", res["message"])
        self.assertTrue(callback.called)
        progress_msgs = [
            c.args[0].get("message", "")
            for c in callback.await_args_list
            if c.args and isinstance(c.args[0], dict)
        ]
        self.assertTrue(any("Refreshing screener snapshot" in m for m in progress_msgs))

    @patch(
        "idx.ingestion.refresh_screener_snapshot",
        side_effect=RuntimeError("screener boom"),
    )
    @patch("idx.pipelines.daily.ingest_daily", return_value={"status": "ok", "stock_summary": {"status": "ok"}})
    def test_run_async_ingestion_job_daily_screener_failure_soft(self, mock_ingest, mock_screener):
        import asyncio

        callback = AsyncMock()
        res = asyncio.run(
            run_async_ingestion_job(
                job_id="test-job-screener-fail",
                job_type="daily",
                params={"date": "20260908"},
                broadcast_callback=callback,
            )
        )
        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["progress_pct"], 100)
        mock_ingest.assert_called_once()
        mock_screener.assert_called_once()
        self.assertEqual(res["results"]["status"], "ok")
        self.assertEqual(res["results"]["screener_refresh"]["status"], "failed")
        self.assertIn("screener boom", res["results"]["screener_refresh"]["error"])
        self.assertIn("screener refresh failed", res["message"])
        # Must broadcast completion, not ingestion_error, for soft screener failure
        event_types = [
            c.args[0].get("type")
            for c in callback.await_args_list
            if c.args and isinstance(c.args[0], dict)
        ]
        self.assertIn("ingestion_completed", event_types)
        self.assertNotIn("ingestion_error", event_types)

    @patch("idx.ingestion.refresh_screener_snapshot")
    @patch("idx.pipelines.parquet.export_all", return_value={"status": "ok"})
    @patch("idx.scrapers.historical.async_backfill_index_summary", new_callable=AsyncMock)
    @patch("idx.scrapers.historical.async_backfill_broker_summary", new_callable=AsyncMock)
    @patch("idx.scrapers.historical.async_backfill_stock_summary", new_callable=AsyncMock)
    def test_run_async_ingestion_job_backfill_skips_screener(
        self,
        mock_stock,
        mock_broker,
        mock_index,
        mock_export,
        mock_screener,
    ):
        import asyncio

        mock_stock.return_value = {"status": "ok"}
        mock_broker.return_value = {"status": "ok"}
        mock_index.return_value = {"status": "ok"}

        res = asyncio.run(
            run_async_ingestion_job(
                job_id="test-job-backfill",
                job_type="backfill",
                params={"start_date": "20260901", "end_date": "20260908", "concurrency": 2},
            )
        )
        self.assertEqual(res["status"], "completed")
        mock_screener.assert_not_called()
        self.assertNotIn("screener_refresh", res["results"])

    def test_get_idx_holidays(self):
        holidays_all = get_idx_holidays()
        self.assertIsInstance(holidays_all, dict)
        self.assertIn("2026-01-01", holidays_all)
        self.assertIn("2026-08-17", holidays_all)

        holidays_2026 = get_idx_holidays(year=2026)
        self.assertTrue(all(d.startswith("2026-") for d in holidays_2026.keys()))


if __name__ == "__main__":
    unittest.main()
