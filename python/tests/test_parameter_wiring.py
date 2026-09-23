"""Real-parameter wiring tests for Historical backfill + Ownership ingest.

All external/network calls are mocked — no live IDX/KSEI traffic.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from idx.api import app
from idx.ingestion import (
    get_orchestration_status,
    normalize_backfill_date_range,
    run_async_ingestion_job,
    run_sync_all_data,
    validate_ownership_path_or_url,
)


class TestDateRangeValidation(unittest.TestCase):
    def test_valid_range_yyyymmdd(self):
        start, end = normalize_backfill_date_range("20260105", "20260110")
        self.assertEqual(start, "20260105")
        self.assertEqual(end, "20260110")

    def test_valid_range_iso(self):
        start, end = normalize_backfill_date_range("2026-01-05", "2026-01-10")
        self.assertEqual((start, end), ("20260105", "20260110"))

    def test_invalid_missing_dates(self):
        with self.assertRaises(ValueError):
            normalize_backfill_date_range(None, "20260110")
        with self.assertRaises(ValueError):
            normalize_backfill_date_range("20260105", None)

    def test_invalid_inverted_range(self):
        with self.assertRaises(ValueError) as ctx:
            normalize_backfill_date_range("20260120", "20260110")
        self.assertIn("start_date", str(ctx.exception).lower())

    def test_invalid_format(self):
        with self.assertRaises(ValueError):
            normalize_backfill_date_range("Jan-5-2026", "20260110")


class TestOwnershipPathValidation(unittest.TestCase):
    def test_missing_path(self):
        with self.assertRaises(ValueError):
            validate_ownership_path_or_url(None)
        with self.assertRaises(ValueError):
            validate_ownership_path_or_url("  ")

    def test_missing_local_file(self):
        with self.assertRaises(ValueError) as ctx:
            validate_ownership_path_or_url("C:/definitely/missing/ownership.csv")
        self.assertIn("not found", str(ctx.exception).lower())

    def test_http_url_requires_opt_in(self):
        url = "https://example.invalid/ksei-ownership.csv"
        with self.assertRaises(ValueError) as ctx:
            validate_ownership_path_or_url(url)
        self.assertIn("RITELINSIGHT_ALLOW_OWNERSHIP_HTTP", str(ctx.exception))

    def test_http_url_accepted_when_opted_in(self):
        url = "https://example.invalid/ksei-ownership.csv"
        with patch.dict(os.environ, {"RITELINSIGHT_ALLOW_OWNERSHIP_HTTP": "1"}):
            self.assertEqual(validate_ownership_path_or_url(url), url)

    def test_existing_local_file_must_be_under_data_dir(self):
        from idx.core.utils import DATA_DIR

        os.makedirs(DATA_DIR, exist_ok=True)
        path = os.path.join(DATA_DIR, "_test_ownership_agent7.csv")
        with open(path, "wb") as fh:
            fh.write(b"DATE,SHARE_CODE\n")
        try:
            self.assertEqual(validate_ownership_path_or_url(path), os.path.realpath(path))
        finally:
            os.unlink(path)

    def test_local_file_outside_data_dir_rejected(self):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as fh:
            fh.write(b"DATE,SHARE_CODE\n")
            path = fh.name
        try:
            with self.assertRaises(ValueError) as ctx:
                validate_ownership_path_or_url(path)
            self.assertIn("DATA_DIR", str(ctx.exception))
        finally:
            os.unlink(path)


class TestHistoricalBackfillJob(unittest.TestCase):
    @patch("idx.pipelines.parquet.export_all", return_value={"status": "ok"})
    @patch("idx.scrapers.historical.async_backfill_index_summary", new_callable=AsyncMock)
    @patch("idx.scrapers.historical.async_backfill_broker_summary", new_callable=AsyncMock)
    @patch("idx.scrapers.historical.async_backfill_stock_summary", new_callable=AsyncMock)
    def test_valid_date_range_backfill(self, mock_stock, mock_broker, mock_index, _export):
        mock_stock.return_value = {"total_records": 10, "dates_fetched": 2, "errors": 0}
        mock_broker.return_value = {"total_records": 5, "dates_fetched": 2, "errors": 0}
        mock_index.return_value = {"total_records": 3, "dates_fetched": 2, "errors": 0}

        res = asyncio.run(
            run_async_ingestion_job(
                job_id="hist-ok",
                job_type="backfill",
                params={"start_date": "2026-01-05", "end_date": "2026-01-08", "concurrency": 2},
            )
        )
        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["results"]["start_date"], "20260105")
        self.assertEqual(res["results"]["end_date"], "20260108")
        orch = res["results"]["orchestration"]
        self.assertEqual(orch["status"], "SUCCESS")
        self.assertEqual(orch["records"], 18)
        status = get_orchestration_status()
        hist = next(p for p in status["pipelines"] if p["id"] == "historical")
        self.assertEqual(hist["availability"], "PARTIAL")
        self.assertEqual(hist["status"], "SUCCESS")

    def test_invalid_range_fails_job_without_network(self):
        res = asyncio.run(
            run_async_ingestion_job(
                job_id="hist-bad",
                job_type="backfill",
                params={"start_date": "20260120", "end_date": "20260110"},
            )
        )
        self.assertEqual(res["status"], "failed")
        self.assertIn("start_date", res["message"].lower())

    def test_missing_dates_fails_without_defaults(self):
        res = asyncio.run(
            run_async_ingestion_job(
                job_id="hist-missing",
                job_type="backfill",
                params={},
            )
        )
        self.assertEqual(res["status"], "failed")
        self.assertIn("explicit", res["message"].lower())

    @patch("idx.pipelines.parquet.export_all", return_value={"status": "ok"})
    @patch("idx.scrapers.historical.async_backfill_index_summary", new_callable=AsyncMock)
    @patch("idx.scrapers.historical.async_backfill_broker_summary", new_callable=AsyncMock)
    @patch("idx.scrapers.historical.async_backfill_stock_summary", new_callable=AsyncMock)
    def test_partial_failure_isolation(self, mock_stock, mock_broker, mock_index, _export):
        mock_stock.return_value = {"total_records": 10, "dates_fetched": 1, "errors": 0}
        mock_broker.side_effect = RuntimeError("broker unavailable")
        mock_index.return_value = {"total_records": 2, "dates_fetched": 1, "errors": 0}

        res = asyncio.run(
            run_async_ingestion_job(
                job_id="hist-partial",
                job_type="backfill",
                params={"start_date": "20260105", "end_date": "20260106"},
            )
        )
        self.assertEqual(res["status"], "completed")
        orch = res["results"]["orchestration"]
        self.assertEqual(orch["status"], "PARTIAL")
        self.assertTrue(any("broker" in e.lower() for e in orch["errors"]))


class TestOwnershipJob(unittest.TestCase):
    def test_ownership_unavailable_without_path_api(self):
        client = TestClient(app)
        resp = client.post("/api/system/trigger-ingestion", json={"job_type": "ownership"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("path_or_url", resp.json()["detail"].lower())

    @patch("idx.core.ownership.ingest_ksei_ownership")
    def test_ownership_success_with_local_file(self, mock_ingest):
        from idx.core.utils import DATA_DIR

        mock_ingest.return_value = {
            "status": "ok",
            "total_rows": 12,
            "output_file": "1%ownership-2026-01-01.csv",
            "deltas": None,
            "tycoon_drift": None,
        }
        os.makedirs(DATA_DIR, exist_ok=True)
        path = os.path.join(DATA_DIR, "_test_own_ok_agent7.csv")
        with open(path, "wb") as fh:
            fh.write(b"x")
        try:
            res = asyncio.run(
                run_async_ingestion_job(
                    job_id="own-ok",
                    job_type="ownership",
                    params={"path_or_url": path},
                )
            )
        finally:
            if os.path.isfile(path):
                os.unlink(path)
        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["results"]["orchestration"]["status"], "SUCCESS")
        self.assertEqual(res["results"]["orchestration"]["records"], 12)
        status = get_orchestration_status()
        own = next(p for p in status["pipelines"] if p["id"] == "ownership")
        self.assertEqual(own["availability"], "UNAVAILABLE")
        self.assertEqual(own["status"], "SUCCESS")

    @patch(
        "idx.core.ownership.ingest_ksei_ownership",
        side_effect=RuntimeError("bad csv"),
    )
    def test_ownership_failure_handling(self, _mock):
        from idx.core.utils import DATA_DIR

        os.makedirs(DATA_DIR, exist_ok=True)
        path = os.path.join(DATA_DIR, "_test_own_fail_agent7.csv")
        with open(path, "wb") as fh:
            fh.write(b"x")
        try:
            res = asyncio.run(
                run_async_ingestion_job(
                    job_id="own-fail",
                    job_type="ownership",
                    params={"path_or_url": path},
                )
            )
        finally:
            if os.path.isfile(path):
                os.unlink(path)
        self.assertEqual(res["status"], "failed")
        self.assertEqual(res["results"]["orchestration"]["status"], "FAILED")


class TestSyncAllDoesNotUnrestrictedHistorical(unittest.TestCase):
    @patch("idx.ingestion.refresh_screener_snapshot", return_value={"status": "completed"})
    @patch("idx.signals.build_briefing", return_value={"radar_rows": 1})
    @patch("idx.pipelines.parquet.export_financial_ratios", return_value={"rows": 1})
    @patch("idx.scrapers.financial.fetch_financial_ratios", return_value={"data": []})
    @patch(
        "idx.pipelines.daily.ingest_daily",
        return_value={
            "stock_summary": {"status": "ok", "records": 1},
            "broker_summary": {"status": "ok", "records": 1},
            "index_summary": {"status": "ok", "records": 1},
        },
    )
    @patch("idx.scrapers.historical.async_backfill_stock_summary", new_callable=AsyncMock)
    def test_sync_all_skips_historical_backfill(self, mock_hist, *_rest):
        result = run_sync_all_data()
        mock_hist.assert_not_called()
        by_id = {p["id"]: p for p in result["pipelines"]}
        self.assertEqual(by_id["historical"]["status"], "UNAVAILABLE")
        self.assertEqual(by_id["ownership"]["status"], "UNAVAILABLE")


class TestApiParameterContracts(unittest.TestCase):
    def test_api_backfill_rejects_inverted_range(self):
        client = TestClient(app)
        resp = client.post(
            "/api/system/trigger-ingestion",
            json={
                "job_type": "backfill",
                "start_date": "20260120",
                "end_date": "20260101",
            },
        )
        self.assertEqual(resp.status_code, 400)

    def test_api_backfill_rejects_missing_dates(self):
        client = TestClient(app)
        resp = client.post(
            "/api/system/trigger-ingestion",
            json={"job_type": "backfill"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("explicit", resp.json()["detail"].lower())

    def test_api_backfill_accepts_valid_range_mocked(self):
        client = TestClient(app)
        with patch("idx.api.run_async_ingestion_job", new_callable=AsyncMock) as mock_job:
            mock_job.return_value = {"status": "completed"}
            resp = client.post(
                "/api/system/trigger-ingestion",
                json={
                    "job_type": "backfill",
                    "start_date": "2026-01-05",
                    "end_date": "2026-01-08",
                    "concurrency": 2,
                },
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["params"]["start_date"], "20260105")
        self.assertEqual(resp.json()["params"]["end_date"], "20260108")


if __name__ == "__main__":
    unittest.main()
