"""Cluster 12 — ingestion job serialization, persistence, interruption detection."""

from __future__ import annotations

import json

import pytest

import idx.ingestion as ing


@pytest.fixture
def isolated_jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(ing, "JOB_HISTORY_FILE", str(tmp_path / "jobs.json"))
    monkeypatch.setattr(ing, "_INGESTION_JOBS", {})
    return tmp_path


def test_interrupted_job_detected_from_history(isolated_jobs):
    (isolated_jobs / "jobs.json").write_text(
        json.dumps([{"job_id": "job-old", "status": "running", "created_at": "2026-09-01"}])
    )
    hist = ing.load_job_history()
    assert hist[0]["status"] == "interrupted"
    assert ing.get_job_status("job-old")["status"] == "interrupted"
    assert ing.running_job() is None


def test_persist_keeps_bounded_history(isolated_jobs, monkeypatch):
    monkeypatch.setattr(ing, "MAX_JOB_HISTORY", 3)
    for i in range(5):
        ing._persist_job(
            {"job_id": f"j{i}", "status": "completed", "created_at": f"2026-09-0{i + 1}"}
        )
    ids = [j["job_id"] for j in ing.load_job_history()]
    assert ids == ["j2", "j3", "j4"]
    assert [j["job_id"] for j in ing.list_recent_jobs(2)] == ["j4", "j3"]


def test_dead_task_does_not_block_new_jobs(isolated_jobs, monkeypatch):
    import asyncio

    monkeypatch.setattr(ing, "_JOB_TASKS", {})
    loop = asyncio.new_event_loop()
    coro = asyncio.sleep(10)
    task = loop.create_task(coro)
    ing._INGESTION_JOBS["job-dead"] = {"job_id": "job-dead", "type": "daily", "status": "running"}
    ing.register_job_task("job-dead", task)
    task.cancel()
    loop.run_until_complete(asyncio.sleep(0))
    loop.close()
    assert ing.running_job() is None
    assert ing._INGESTION_JOBS["job-dead"]["status"] == "interrupted"


def test_ingest_endpoint_rejects_concurrent_job(isolated_jobs):
    from fastapi.testclient import TestClient

    from idx.api import app

    ing._INGESTION_JOBS["job-busy"] = {
        "job_id": "job-busy",
        "type": "sync_all",
        "status": "running",
    }
    client = TestClient(app)
    r = client.post("/api/system/trigger-ingestion", json={"job_type": "daily"})
    assert r.status_code == 409
    assert "job-busy" in r.json()["detail"]
