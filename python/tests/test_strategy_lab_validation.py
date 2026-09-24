"""Cluster 10 — Strategy Lab ↔ validation / research-study integration."""

from __future__ import annotations

import json

import pandas as pd
import pytest

import idx.strategy_lab as lab


def _stock() -> pd.DataFrame:
    rows = []
    for i, d in enumerate(pd.bdate_range("2024-01-01", periods=160)):
        for k in range(4):
            c = 100.0 + k * 5 + (i % 9) - 4
            prev = 100.0 + k * 5 + ((i - 1) % 9) - 4 if i else c
            rows.append(
                {
                    "Date": d.strftime("%Y-%m-%d"),
                    "StockCode": f"S{k}",
                    "OpenPrice": c,
                    "High": c + 1,
                    "Low": c - 1,
                    "Close": c,
                    "Previous": prev,
                    "Volume": 1_000_000 + 10_000 * ((i + k) % 5),
                    "Value": 5e9,
                    "ForeignBuy": 2e6 * (k + 1),
                    "ForeignSell": 1e6,
                    "TradebleShares": 1e8,
                }
            )
    return pd.DataFrame(rows)


@pytest.fixture
def research_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(lab, "RESEARCH_DIR", str(tmp_path))
    lab._STUDY_CACHE.update({"path": None, "mtime": None, "report": None})
    return tmp_path


def test_catalog_maps_new_engines_and_no_production_claim(research_dir):
    catalog = {s["id"]: s for s in lab.list_strategies()["strategies"]}
    for sid in ("momentum", "breakout", "pullback", "mean_reversion", "volume_expansion"):
        assert catalog[sid]["engine"] == sid
        assert catalog[sid]["research_validation"]["status"] == "NOT_VALIDATED"
        assert catalog[sid]["profitable_claim"] is False
    assert catalog["intraday"]["research_validation"]["status"] == "UNAVAILABLE"
    assert "broker" not in catalog["bandarmology"]["notes"].lower().replace("no broker", "")


def test_research_validation_reads_latest_study(research_dir):
    report = {
        "generated_at": "2026-09-23T00:00:00+00:00",
        "trials": [
            {
                "strategy_id": "s1_momentum_standalone",
                "horizon": "NEXT_DAY_1_3D",
                "verdict": "FAILED",
            },
            {
                "strategy_id": "s1_momentum_standalone",
                "horizon": "SWING_3_10D",
                "verdict": "FRAGILE",
            },
        ],
    }
    (research_dir / "discovery_study_2026-09-23.json").write_text(json.dumps(report))
    rv = lab.research_validation("momentum")
    assert rv["status"] == "NOT_VALIDATED"
    assert rv["by_horizon"] == {"NEXT_DAY_1_3D": "FAILED", "SWING_3_10D": "FRAGILE"}
    assert rv["production_status"] is None
    entry = {s["id"]: s for s in lab.list_strategies()["strategies"]}["momentum"]
    assert "FAILED" in entry["oos"]


def test_run_strategy_validation_uses_harness(research_dir):
    out = lab.run_strategy_validation(
        "momentum",
        horizon="SWING_3_10D",
        holding_days=5,
        discovery=("2024-01-01", "2024-03-29"),
        validation=("2024-04-01", "2024-05-31"),
        oos=("2024-06-03", "2024-08-09"),
        top_n=2,
        min_turnover_rp=1e8,
        walk_forward={
            "train_start": "2024-01-01",
            "first_train_end": "2024-03-29",
            "test_span_calendar_days": 30,
            "step_calendar_days": 30,
            "n_folds": 2,
        },
        injected_frames={"stock_df": _stock(), "ratios_df": pd.DataFrame()},
    )
    assert out["status"] in ("COMPLETED", "REJECTED")
    assert set(out["phases"]) == {"IS", "VALIDATION", "OOS", "WALK_FORWARD"}
    assert out["production_buy_emitted"] is False
    assert out["return_is_net_tradable"] is False
    assert out["strategy"] == "momentum"


def test_run_strategy_validation_rejects_overlap_and_unknown(research_dir):
    out = lab.run_strategy_validation(
        "momentum",
        horizon="SWING_3_10D",
        holding_days=5,
        discovery=("2024-01-01", "2024-04-30"),
        validation=("2024-04-01", "2024-05-31"),
        oos=("2024-06-03", "2024-08-09"),
        injected_frames={"stock_df": _stock(), "ratios_df": pd.DataFrame()},
    )
    assert out["status"] == "REJECTED"
    assert (
        lab.run_strategy_validation(
            "intraday",
            horizon="INTRADAY",
            holding_days=1,
            discovery=("a", "b"),
            validation=("c", "d"),
            oos=("e", "f"),
        )["status"]
        == "UNAVAILABLE"
    )
    bad_wf = lab.run_strategy_validation(
        "momentum",
        horizon="SWING_3_10D",
        holding_days=5,
        discovery=("2024-01-01", "2024-03-29"),
        validation=("2024-04-01", "2024-05-31"),
        oos=("2024-06-03", "2024-08-09"),
        walk_forward={"n_folds": 0},
        injected_frames={"stock_df": _stock(), "ratios_df": pd.DataFrame()},
    )
    assert bad_wf["status"] == "REJECTED"


def test_api_validate_and_research_routes(research_dir):
    from fastapi.testclient import TestClient

    from idx.api import app

    client = TestClient(app)
    r = client.post(
        "/api/strategy/validate",
        json={
            "strategy": "intraday",
            "horizon": "INTRADAY",
            "holding_days": 1,
            "discovery_start": "2024-01-01",
            "discovery_end": "2024-02-01",
            "validation_start": "2024-02-02",
            "validation_end": "2024-03-01",
            "oos_start": "2024-03-02",
            "oos_end": "2024-04-01",
        },
    )
    assert r.status_code == 200 and r.json()["status"] == "UNAVAILABLE"
    assert client.post("/api/strategy/validate", json={"strategy": "momentum"}).status_code == 422
    research = client.get("/api/strategy/research").json()
    assert research["status"] == "NOT_VALIDATED"
