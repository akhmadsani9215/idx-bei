"""Cluster 4 — robustness sensitivity harness + multiple-testing bookkeeping."""

from __future__ import annotations

import pandas as pd

from idx.signal_discovery.costs import illustrative_cost_model, illustrative_slippage_model
from idx.signal_discovery.registry import TRIAL_REQUIRED_FIELDS, TrialRegistry
from idx.signal_discovery.robustness import (
    ROBUSTNESS_STATUSES,
    RobustnessConfig,
    run_robustness,
)
from idx.signal_discovery.validation import (
    FORBIDDEN_VALIDATION_STATUSES,
    ValidationConfig,
    ValidationWindow,
)


def _make_eval(metric_fn, *, trades: int = 40, calls: list | None = None):
    """Evaluator whose per-trade gross return (%) = metric_fn(params, holding, start)."""

    def _eval(strategy, holding, start, end, params):
        if calls is not None:
            calls.append((holding, start, end, dict(params)))
        r = metric_fn(params, holding, start)
        n = trades(params, holding, start) if callable(trades) else trades
        ledger = pd.DataFrame({"Return": [r / 100.0] * n})
        return {"total_trades": n, "holding_days": holding}, ledger

    return _eval


def _base(evaluate_fn=None, **kwargs) -> ValidationConfig:
    base = dict(
        trial_id="trial_rb_001",
        strategy_id="s1_relative_strength_foreign",
        strategy_version="stage1-0.1.0",
        horizon="SWING_3_10D",
        engine_strategy="foreign_flow",
        parameters={"top_n": 10, "min_turnover_rp": 1e9},
        holding_days=7,
        discovery=ValidationWindow("2024-01-01", "2024-03-31"),
        validation=ValidationWindow("2024-04-01", "2024-06-30"),
        oos=ValidationWindow("2024-07-01", "2024-09-30"),
        universe_definition="test universe",
        min_sample=30,
        data_available_start="2024-01-01",
        data_available_end="2024-12-31",
        evaluate_fn=evaluate_fn,
    )
    base.update(kwargs)
    return ValidationConfig(**base)


def _stable(params, holding, start):
    return 1.0 + 0.01 * (params["top_n"] - 10) + 0.02 * (holding - 7)


def _rcfg(base, **kwargs) -> RobustnessConfig:
    d = dict(
        base=base,
        evaluation_phase="IS",
        max_variants=10,
        parameter_neighbors={"top_n": [8, 12]},
        holding_days_neighbors=[5, 9],
    )
    d.update(kwargs)
    return RobustnessConfig(**d)


def test_stable_neighbours_across_two_dimensions_is_robust_and_keeps_all_variants():
    calls: list = []
    out = run_robustness(_rcfg(_base(_make_eval(_stable, calls=calls))))
    assert out["status"] == "COMPLETED"
    assert out["robustness_status"] == "ROBUST"
    assert out["dimensions"]["parameter_sensitivity"]["status"] == "ROBUST"
    assert out["dimensions"]["horizon_sensitivity"]["status"] == "ROBUST"
    assert len(out["variants"]) == out["variant_count"] == 5
    assert len(calls) == 5
    assert all(c[1] == "2024-01-01" and c[2] == "2024-03-31" for c in calls)  # IS only
    assert out["oos_used"] is False
    assert out["metric_basis"] == "GROSS_EXPECTANCY_PCT"
    assert out["return_is_net_tradable"] is False
    assert out["survivorship_status"] == "NOT_VALIDATED"
    assert out["profitable_claim"] is False
    assert out["production_buy_emitted"] is False
    assert out["robustness_status"] not in FORBIDDEN_VALIDATION_STATUSES
    assert "selection_label" not in str(out["variants"])


def test_sign_flip_neighbour_is_fragile():
    def flip(params, holding, start):
        return -0.5 if params["top_n"] == 12 else 1.0

    out = run_robustness(_rcfg(_base(_make_eval(flip))))
    assert out["dimensions"]["parameter_sensitivity"]["status"] == "FRAGILE"
    assert out["robustness_status"] == "FRAGILE"


def test_large_degradation_is_fragile():
    def cliff(params, holding, start):
        return 2.0 if params["top_n"] == 10 else 0.5

    out = run_robustness(_rcfg(_base(_make_eval(cliff)), holding_days_neighbors=[]))
    dim = out["dimensions"]["parameter_sensitivity"]
    assert dim["status"] == "FRAGILE"
    assert dim["median_degradation"] == 0.75


def test_single_dimension_cannot_be_robust():
    out = run_robustness(_rcfg(_base(_make_eval(_stable)), holding_days_neighbors=[]))
    assert out["dimensions"]["parameter_sensitivity"]["status"] == "ROBUST"
    assert out["robustness_status"] == "INCONCLUSIVE"


def test_non_positive_base_is_inconclusive_not_robust():
    out = run_robustness(_rcfg(_base(_make_eval(lambda p, h, s: -0.2))))
    assert out["dimensions"]["parameter_sensitivity"]["status"] == "INCONCLUSIVE"
    assert out["robustness_status"] == "INCONCLUSIVE"


def test_insufficient_neighbour_samples():
    def few(params, holding, start):
        return 5 if params["top_n"] != 10 else 40

    out = run_robustness(_rcfg(_base(_make_eval(_stable, trades=few)), holding_days_neighbors=[]))
    assert out["dimensions"]["parameter_sensitivity"]["status"] == "INSUFFICIENT_DATA"
    assert out["robustness_status"] == "INSUFFICIENT_DATA"
    assert all(v["status"] in ("OK", "INSUFFICIENT_DATA") for v in out["variants"])


def test_one_unevaluable_neighbour_blocks_robust():
    def few(params, holding, start):
        return 5 if params["top_n"] == 14 else 40

    out = run_robustness(
        _rcfg(_base(_make_eval(_stable, trades=few)), parameter_neighbors={"top_n": [8, 12, 14]})
    )
    assert out["dimensions"]["parameter_sensitivity"]["status"] == "INCONCLUSIVE"
    assert out["robustness_status"] == "INCONCLUSIVE"


def test_oos_phase_rejected():
    out = run_robustness(_rcfg(_base(_make_eval(_stable)), evaluation_phase="OOS"))
    assert out["status"] == "REJECTED"
    assert "OOS" in out["failure_reason"]


def test_variant_budget_enforced_without_execution():
    calls: list = []
    out = run_robustness(_rcfg(_base(_make_eval(_stable, calls=calls)), max_variants=3))
    assert out["status"] == "TRIAL_LIMIT_REACHED"
    assert out["variants"] == []
    assert calls == []


def test_holding_neighbour_outside_horizon_rejected():
    out = run_robustness(_rcfg(_base(_make_eval(_stable)), holding_days_neighbors=[5, 15]))
    assert out["status"] == "REJECTED"
    assert "SWING_3_10D" in out["failure_reason"]


def test_real_engine_rejects_no_op_parameters():
    base = _base(None, parameters={"top_n": 10, "min_turnover_rp": 1e9, "lookback": 20})
    out = run_robustness(_rcfg(base, parameter_neighbors={"lookback": [10, 30]}))
    assert out["status"] == "REJECTED"
    assert "not consumed" in out["failure_reason"]
    out = run_robustness(_rcfg(base, parameter_neighbors={"min_turnover_rp": [5e8, 2e9]}))
    assert out["status"] == "REJECTED"
    assert "universe_neighbors" in out["failure_reason"]


def test_neighbour_list_must_exclude_base_and_duplicates():
    out = run_robustness(_rcfg(_base(_make_eval(_stable)), parameter_neighbors={"top_n": [10, 12]}))
    assert out["status"] == "REJECTED"
    out = run_robustness(_rcfg(_base(_make_eval(_stable)), parameter_neighbors={"top_n": [12, 12]}))
    assert out["status"] == "REJECTED"


def test_universe_and_time_dimensions():
    out = run_robustness(
        _rcfg(
            _base(_make_eval(_stable)),
            parameter_neighbors={},
            holding_days_neighbors=[],
            universe_neighbors={"min_turnover_rp": [5e8, 2e9]},
            time_subwindows=[
                ValidationWindow("2024-01-01", "2024-01-31"),
                ValidationWindow("2024-02-01", "2024-02-29"),
                ValidationWindow("2024-03-01", "2024-03-31"),
            ],
        )
    )
    assert set(out["dimensions"]) == {"universe_sensitivity", "time_sensitivity"}
    assert out["robustness_status"] == "ROBUST"


def test_time_subwindow_outside_phase_rejected():
    out = run_robustness(
        _rcfg(
            _base(_make_eval(_stable)),
            time_subwindows=[
                ValidationWindow("2024-03-01", "2024-03-31"),
                ValidationWindow("2024-04-01", "2024-04-30"),
            ],
        )
    )
    assert out["status"] == "REJECTED"


def test_cost_sensitivity_is_illustrative_and_does_not_drive_label():
    scenarios = [
        (
            illustrative_cost_model(buy_fee_bps=bps, sell_fee_bps=bps, label=f"{bps}bps"),
            illustrative_slippage_model(per_side_bps=bps, label=f"{bps}bps"),
        )
        for bps in (10, 100)
    ]
    out = run_robustness(_rcfg(_base(_make_eval(_stable)), cost_scenarios=scenarios))
    cost = out["cost_sensitivity"]
    assert cost["status"] == "RESEARCH_ILLUSTRATIVE"
    assert cost["counts_toward_robust"] is False
    assert len(cost["scenarios"]) == 2
    assert (
        cost["scenarios"][0]["net_expectancy_pct"] > 0 > cost["scenarios"][1]["net_expectancy_pct"]
    )
    assert cost["net_expectancy_positive_in_all"] is False
    assert out["robustness_status"] == "ROBUST"
    assert out["return_is_net_tradable"] is False


def test_cost_sensitivity_not_configured_by_default():
    out = run_robustness(_rcfg(_base(_make_eval(_stable))))
    assert out["cost_sensitivity"]["status"] == "NOT_CONFIGURED"


def test_dry_run_is_never_robust():
    out = run_robustness(_rcfg(_base(_make_eval(_stable), dry_run=True)))
    assert out["status"] == "DRY_RUN"
    assert out["robustness_status"] == "INCONCLUSIVE"
    assert out["robustness_status"] in ROBUSTNESS_STATUSES


def test_registry_counts_robustness_toward_multiple_testing():
    reg = TrialRegistry()
    trial = {f: None for f in TRIAL_REQUIRED_FIELDS} | {
        "trial_id": "trial_rb_001",
        "strategy_id": "s1_relative_strength_foreign",
        "horizon": "SWING_3_10D",
        "status": "CANDIDATE",
        "hypothesis_family": "relative_strength",
        "parameters": {"top_n": 10, "min_turnover_rp": 1e9, "holding_days": 7},
        "metrics": {},
    }
    reg.register(trial)
    out = run_robustness(_rcfg(_base(_make_eval(_stable))))
    summary = reg.record_robustness_run(out)
    assert summary["variant_count"] == 5

    mt = reg.multiple_testing_summary()
    assert mt["total_trials"] == 1
    assert mt["trials_by_family"] == {"relative_strength": 1}
    assert mt["trials_by_horizon"] == {"SWING_3_10D": 1}
    assert mt["robustness_runs"] == 1
    assert mt["robustness_variants_total"] == 5
    # base variant matches the registered trial's parameter set → 5 distinct, not 6
    assert mt["parameter_variants"] == 5
    assert mt["evaluations_upper_bound"] == 6
    assert mt["adjustment_status"] == "NOT_APPLIED"
    assert mt["deflated_sharpe"] is None
    assert mt["deflated_sharpe_status"] == "NOT_IMPLEMENTED"
    assert mt["statistical_significance_claimed"] is False
