"""Clusters 6–8 — controlled study protocol, verdict rules, JSON safety."""

from __future__ import annotations

import json
from dataclasses import replace

import pandas as pd

from idx.signal_discovery.study import (
    VERDICTS,
    _verdict,
    default_plan_for_local_data,
    holding_neighbors,
    report_json_safe,
    run_controlled_study,
)
from idx.signal_discovery.validation import ValidationWindow, WalkForwardConfig


def _phase(exp, base=0.1, net=None, status="OK"):
    return {
        "status": status,
        "gross_expectancy_pct": exp,
        "excess_vs_baseline_pct": None if exp is None else exp - base,
        "illustrative_net_expectancy_pct": exp - 0.5 if net is None and exp is not None else net,
        "failure_reason": None if status == "OK" else "sample",
    }


def _trial(**over):
    t = {
        "phases": {"IS": _phase(1.5), "VALIDATION": _phase(1.2), "OOS": _phase(1.0)},
        "eligibility_status": "VALIDATED_FOR_RESEARCH",
        "robustness_status": "ROBUST",
        "robustness_reasons": [],
        "walk_forward_folds": [{"status": "OK", "gross_expectancy_pct": 0.8}],
        "deflated_sharpe": {"status": "PASS"},
        "fdr_decision": "DISCOVERY",
    }
    t.update(over)
    return t


def test_verdict_survives_only_when_every_check_passes():
    assert _verdict(_trial()) == ("SURVIVES_RESEARCH_VALIDATION", [])
    v, reasons = _verdict(_trial(deflated_sharpe={"status": "FAIL"}))
    assert v == "INCONCLUSIVE" and "DSR FAIL" in reasons


def test_verdict_failed_and_fragile_and_insufficient():
    t = _trial()
    t["phases"]["OOS"] = _phase(-0.2)
    assert _verdict(t)[0] == "FAILED"
    t = _trial()
    t["phases"]["OOS"] = _phase(0.05, base=0.3)  # positive but below baseline
    assert _verdict(t)[0] == "FAILED"
    t = _trial()
    t["phases"]["OOS"] = _phase(0.3, base=0.1, net=-0.1)  # dies after stress costs
    assert _verdict(t)[0] == "FAILED"
    assert _verdict(_trial(robustness_status="FRAGILE"))[0] == "FRAGILE"
    folds = [
        {"status": "OK", "gross_expectancy_pct": 0.5},
        {"status": "OK", "gross_expectancy_pct": -0.1},
    ]
    assert _verdict(_trial(walk_forward_folds=folds))[0] == "FRAGILE"
    t = _trial()
    t["phases"]["VALIDATION"] = _phase(None, status="INSUFFICIENT_DATA")
    assert _verdict(t)[0] == "INSUFFICIENT_DATA"


def test_holding_neighbors_stay_inside_horizon():
    assert holding_neighbors("NEXT_DAY_1_3D", 2) == [1, 3]
    assert holding_neighbors("SWING_3_10D", 7) == [6, 8]
    assert holding_neighbors("POSITION_1_3M", 42) == [32, 52]
    assert holding_neighbors("INTRADAY", 1) == []


def test_default_plan_is_explicit_and_illustrative():
    plan = default_plan_for_local_data()
    assert plan.discovery.end < plan.validation.start
    assert plan.validation.end < plan.oos.start
    assert plan.stress_cost.status == "RESEARCH_ILLUSTRATIVE"
    assert plan.max_trials >= 7 * 4


def test_report_json_safe():
    import numpy as np

    out = report_json_safe(
        {"a": float("nan"), "b": np.float64(1.5), "c": [float("inf"), np.int64(2)]}
    )
    assert out == {"a": None, "b": 1.5, "c": [None, 2]}
    json.dumps(out, allow_nan=False)


def _synthetic_stock() -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-01", periods=120)
    rows = []
    for k in range(6):
        for i, d in enumerate(dates):
            c = 100.0 + k * 10 + ((i * (k + 1)) % 11) - 5
            rows.append(
                {
                    "Date": d.strftime("%Y-%m-%d"),
                    "StockCode": f"T{k:03d}",
                    "OpenPrice": c,
                    "High": c + 1,
                    "Low": c - 1,
                    "Close": c,
                    "Previous": float(c if i == 0 else 100.0 + k * 10 + (((i - 1) * (k + 1)) % 11) - 5),
                    "Volume": 1_000_000 + 50_000 * ((i + k) % 7),
                    "Value": 5e9,
                    "ForeignBuy": 1_000_000.0 * (k + 1),
                    "ForeignSell": 900_000.0,
                    "TradebleShares": 100_000_000,
                }
            )
    return pd.DataFrame(rows)


def test_study_end_to_end_on_synthetic_data_is_honest():
    plan = replace(
        default_plan_for_local_data(),
        discovery=ValidationWindow("2024-01-01", "2024-02-29"),
        validation=ValidationWindow("2024-03-01", "2024-04-15"),
        oos=ValidationWindow("2024-04-16", "2024-06-14"),
        walk_forward=WalkForwardConfig(
            train_start="2024-01-01",
            first_train_end="2024-02-29",
            test_span_calendar_days=30,
            step_calendar_days=30,
            n_folds=2,
        ),
        horizons=("INTRADAY", "SWING_3_10D"),
    )
    ratios = pd.DataFrame([{"code": "T000", "fsDate": "2023-12-31", "roe": 15.0, "per": 10.0}])
    report = run_controlled_study(plan, _synthetic_stock(), ratios, None)
    assert report["production_buy_emitted"] is False
    assert report["profitable_claim"] is False
    assert len(report["trials"]) == 7  # SWING_3_10D × 7 families
    assert sum(1 for n in report["not_evaluated"] if n["verdict"] == "UNAVAILABLE") == 7
    for t in report["trials"]:
        assert t["verdict"] in VERDICTS
        assert t["production_status"] is None
        assert t["cost_semantics"]["return_is_net_tradable"] is False
    assert report["multiple_testing"]["total_trials"] == 7
    assert report["multiple_testing"]["robustness_runs"] == 7
    json.dumps(report_json_safe(report), allow_nan=False)
