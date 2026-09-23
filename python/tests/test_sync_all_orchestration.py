"""Tests for Data Center Sync All Data orchestration foundation."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from idx.api import app
from idx.ingestion import (
    PIPELINE_CATALOG,
    get_full_ingestion_status,
    get_orchestration_status,
    run_sync_all_data,
)


def _ok_daily() -> dict:
    return {
        "stock_summary": {"status": "ok", "records": 100},
        "broker_summary": {"status": "ok", "records": 50},
        "index_summary": {"status": "ok", "records": 10},
        "parquet_export": {"status": "ok"},
    }


class TestSyncAllOrchestration(unittest.TestCase):
    def test_catalog_covers_required_pipelines(self):
        ids = {p["id"] for p in PIPELINE_CATALOG}
        self.assertEqual(
            ids,
            {
                "market_eod",
                "financial",
                "foreign",
                "historical",
                "ownership",
                "broker",
                "feature_rebuild",
                "signal_rebuild",
                "target_risk",
                "screener_rebuild",
            },
        )

    def test_orchestration_status_marks_unavailable_honestly(self):
        import idx.ingestion as ing

        ing._LAST_SYNC_ALL = None
        ing._LAST_HISTORICAL_RUN = None
        ing._LAST_OWNERSHIP_RUN = None
        status = get_orchestration_status()
        self.assertEqual(status["integrations"]["realtime"], "NOT_CONFIGURED")
        self.assertEqual(status["integrations"]["ai"], "NOT_CONFIGURED")
        by_id = {p["id"]: p for p in status["pipelines"]}
        self.assertEqual(by_id["ownership"]["availability"], "UNAVAILABLE")
        self.assertEqual(by_id["ownership"]["status"], "UNAVAILABLE")
        # Feature/target rebuild are PARTIAL (on-read snapshot) until a Sync All run.
        self.assertEqual(by_id["feature_rebuild"]["availability"], "PARTIAL")
        self.assertEqual(by_id["target_risk"]["availability"], "PARTIAL")
        self.assertEqual(by_id["historical"]["availability"], "PARTIAL")
        self.assertIn(
            "date range",
            " ".join(by_id["historical"].get("warnings") or []).lower()
            + " "
            + str(by_id["historical"].get("notes") or "").lower(),
        )
        self.assertNotEqual(by_id["historical"]["status"], "SUCCESS")
        self.assertIsNone(by_id["ownership"]["source"])

    def test_ingestion_status_includes_orchestration(self):
        full = get_full_ingestion_status()
        self.assertIn("orchestration", full)
        self.assertIn("pipelines", full["orchestration"])
        self.assertIn("integrations", full["orchestration"])

    def test_api_ingestion_status_includes_orchestration(self):
        client = TestClient(app)
        resp = client.get("/api/system/ingestion-status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("orchestration", data)
        self.assertEqual(data["orchestration"]["integrations"]["payment"], "NOT_CONFIGURED")
        self.assertGreaterEqual(len(data["orchestration"]["pipelines"]), 10)

    def test_api_rejects_unknown_job_type(self):
        client = TestClient(app)
        resp = client.post(
            "/api/system/trigger-ingestion",
            json={"job_type": "fabricate_everything"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_api_accepts_sync_all_job_type(self):
        client = TestClient(app)
        with patch("idx.api.run_async_ingestion_job", new_callable=AsyncMock) as mock_job:
            mock_job.return_value = {"status": "completed"}
            resp = client.post(
                "/api/system/trigger-ingestion",
                json={"job_type": "sync_all"},
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["job_type"], "sync_all")
        self.assertIn("job_id", body)
        self.assertTrue(mock_job.called)
        kwargs = mock_job.call_args.kwargs
        self.assertEqual(kwargs.get("job_type"), "sync_all")

    @patch("idx.rebuild.rebuild_target_risk", return_value={"status": "SUCCESS", "records": 5, "warnings": [], "errors": [], "duration_sec": 0.1, "engine_version": "rebuild-1.0"})
    @patch("idx.rebuild.rebuild_features", return_value={"status": "SUCCESS", "records": 5, "warnings": [], "errors": [], "duration_sec": 0.1, "engine_version": "rebuild-1.0"})
    @patch("idx.ingestion.refresh_screener_snapshot", return_value={"status": "completed"})
    @patch("idx.signals.build_briefing", return_value={"radar_rows": 3, "shield_rows": 1})
    @patch("idx.pipelines.parquet.export_financial_ratios", return_value={"rows": 20})
    @patch("idx.scrapers.financial.fetch_financial_ratios", return_value={"data": [{"code": "AAA"}]})
    @patch("idx.pipelines.daily.ingest_daily", return_value=_ok_daily())
    def test_sync_all_success_path(self, *_mocks):
        result = run_sync_all_data()
        self.assertEqual(result["overall_status"], "SUCCESS")
        by_id = {p["id"]: p for p in result["pipelines"]}
        self.assertEqual(by_id["market_eod"]["status"], "SUCCESS")
        self.assertEqual(by_id["broker"]["status"], "SUCCESS")
        self.assertEqual(by_id["foreign"]["status"], "SUCCESS")
        self.assertEqual(by_id["financial"]["status"], "SUCCESS")
        self.assertEqual(by_id["signal_rebuild"]["status"], "SUCCESS")
        self.assertEqual(by_id["screener_rebuild"]["status"], "SUCCESS")
        self.assertEqual(by_id["ownership"]["status"], "UNAVAILABLE")
        self.assertEqual(by_id["feature_rebuild"]["status"], "SUCCESS")
        self.assertEqual(by_id["target_risk"]["status"], "SUCCESS")
        self.assertEqual(by_id["historical"]["status"], "UNAVAILABLE")
        # Sync All must not invent a SUCCESS for historical/ownership
        self.assertNotIn(
            by_id["historical"]["status"],
            {"SUCCESS"},
        )
        self.assertIsInstance(by_id["market_eod"]["records"], int)

    @patch("idx.rebuild.rebuild_target_risk", return_value={"status": "SUCCESS", "records": 2, "warnings": [], "errors": [], "duration_sec": 0.01, "engine_version": "rebuild-1.0"})
    @patch("idx.rebuild.rebuild_features", return_value={"status": "SUCCESS", "records": 2, "warnings": [], "errors": [], "duration_sec": 0.01, "engine_version": "rebuild-1.0"})
    @patch("idx.ingestion.refresh_screener_snapshot", return_value={"status": "completed"})
    @patch("idx.signals.build_briefing", return_value={"radar_rows": 2})
    @patch("idx.pipelines.parquet.export_financial_ratios", return_value={"rows": 5})
    @patch(
        "idx.scrapers.financial.fetch_financial_ratios",
        side_effect=RuntimeError("financial down"),
    )
    @patch("idx.pipelines.daily.ingest_daily", return_value=_ok_daily())
    def test_failure_isolation_financial_does_not_fail_market(self, *_mocks):
        result = run_sync_all_data()
        by_id = {p["id"]: p for p in result["pipelines"]}
        self.assertEqual(by_id["market_eod"]["status"], "SUCCESS")
        self.assertEqual(by_id["broker"]["status"], "SUCCESS")
        self.assertEqual(by_id["foreign"]["status"], "SUCCESS")
        self.assertEqual(by_id["financial"]["status"], "FAILED")
        self.assertEqual(by_id["signal_rebuild"]["status"], "SUCCESS")
        self.assertEqual(by_id["screener_rebuild"]["status"], "SUCCESS")
        self.assertEqual(result["overall_status"], "PARTIAL")
        self.assertTrue(by_id["financial"]["errors"])

    @patch("idx.rebuild.rebuild_target_risk", return_value={"status": "SUCCESS", "records": 1, "warnings": [], "errors": [], "duration_sec": 0.01, "engine_version": "rebuild-1.0"})
    @patch("idx.rebuild.rebuild_features", return_value={"status": "SUCCESS", "records": 1, "warnings": [], "errors": [], "duration_sec": 0.01, "engine_version": "rebuild-1.0"})
    @patch("idx.ingestion.refresh_screener_snapshot", return_value={"status": "completed"})
    @patch("idx.signals.build_briefing", return_value={"radar_rows": 1})
    @patch("idx.pipelines.parquet.export_financial_ratios", return_value={"rows": 5})
    @patch("idx.scrapers.financial.fetch_financial_ratios", return_value={"data": [{"code": "AAA"}]})
    @patch("idx.pipelines.daily.ingest_daily", return_value=_ok_daily())
    def test_controlled_foreign_failure_keeps_market_success(self, *_mocks):
        result = run_sync_all_data(fail_pipelines={"foreign"})
        by_id = {p["id"]: p for p in result["pipelines"]}
        self.assertEqual(by_id["market_eod"]["status"], "SUCCESS")
        self.assertEqual(by_id["broker"]["status"], "SUCCESS")
        self.assertEqual(by_id["foreign"]["status"], "FAILED")
        self.assertEqual(result["overall_status"], "PARTIAL")


if __name__ == "__main__":
    unittest.main()
