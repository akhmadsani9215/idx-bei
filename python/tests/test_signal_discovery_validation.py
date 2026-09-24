"""Cluster 3 — OOS / walk-forward validation harness tests."""

from __future__ import annotations

import pytest

from idx.signal_discovery.contract import CandidateValidationError, assert_no_future_feature
from idx.signal_discovery.metrics_adapter import adapt_backtest_metrics, mark_unavailable_shell
from idx.signal_discovery.validation import (
    DEFAULT_MIN_SAMPLE,
    FORBIDDEN_VALIDATION_STATUSES,
    RESEARCH_ELIGIBLE_STATUS,
    ValidationConfig,
    ValidationConfigError,
    ValidationWindow,
    WalkForwardConfig,
    assert_fold_temporal_integrity,
    assert_no_oos_parameter_selection,
    build_walk_forward_folds,
    check_data_coverage,
    evaluate_research_eligibility,
    run_validation,
    validate_temporal_split,
)


def _windows():
    return (
        ValidationWindow("2024-01-01", "2024-03-31"),
        ValidationWindow("2024-04-01", "2024-06-30"),
        ValidationWindow("2024-07-01", "2024-09-30"),
    )


def _cfg(**kwargs) -> ValidationConfig:
    d, v, o = _windows()
    base = dict(
        trial_id="trial_test_001",
        strategy_id="s1_relative_strength_foreign",
        strategy_version="stage1-0.1.0",
        horizon="SWING_3_10D",
        engine_strategy="foreign_flow",
        parameters={"top_n": 10, "min_turnover_rp": 1e9},
        holding_days=7,
        discovery=d,
        validation=v,
        oos=o,
        universe_definition="test universe",
        min_sample=5,
        data_available_start="2024-01-01",
        data_available_end="2024-12-31",
        dry_run=True,
    )
    base.update(kwargs)
    return ValidationConfig(**base)


def _ok_eval(strategy, holding, start, end, params):
    """Synthetic evaluator: returns enough sample for gates."""
    return (
        {
            "total_trades": 40,
            "win_rate_pct": 55.0,
            "total_return_pct": 3.2,
            "avg_trade_return_pct": 0.08,
            "max_drawdown_pct": 4.0,
            "sharpe_ratio": 0.5,
            "sortino_ratio": 0.6,
            "profit_factor": 1.2,
            "holding_days": holding,
        },
        None,
    )


def test_temporal_split_rejects_overlap():
    d, v, o = _windows()
    validate_temporal_split(d, v, o)  # ok
    with pytest.raises(ValidationConfigError, match="overlap"):
        validate_temporal_split(
            ValidationWindow("2024-01-01", "2024-04-15"),
            v,
            o,
        )
    with pytest.raises(ValidationConfigError, match="overlap"):
        validate_temporal_split(
            d,
            ValidationWindow("2024-04-01", "2024-07-15"),
            o,
        )


def test_temporal_split_rejects_invalid_order_inside_window():
    with pytest.raises(ValidationConfigError):
        validate_temporal_split(
            ValidationWindow("2024-03-01", "2024-01-01"),
            ValidationWindow("2024-04-01", "2024-06-30"),
            ValidationWindow("2024-07-01", "2024-09-30"),
        )


def test_no_silent_date_shrinking():
    w = ValidationWindow("2024-01-01", "2024-06-30")
    cov = check_data_coverage(
        w,
        data_available_start="2024-02-01",
        data_available_end="2024-05-31",
    )
    assert cov["ok"] is False
    assert cov["actual_used_range"] is None
    assert cov["coverage_status"] == "INSUFFICIENT_DATA"
    assert "silent shrink" in (cov["failure_reason"] or "")


def test_full_coverage_uses_requested_range():
    w = ValidationWindow("2024-02-01", "2024-03-01")
    cov = check_data_coverage(
        w,
        data_available_start="2024-01-01",
        data_available_end="2024-12-31",
    )
    assert cov["ok"] is True
    assert cov["actual_used_range"] == cov["requested_range"]


def test_walk_forward_fold_ordering_and_unseen_test():
    wf = WalkForwardConfig(
        train_start="2024-01-01",
        first_train_end="2024-03-31",
        test_span_calendar_days=30,
        step_calendar_days=30,
        n_folds=3,
        parameter_version="locked-v1",
    )
    folds = build_walk_forward_folds(wf)
    assert_fold_temporal_integrity(folds)
    assert len(folds) == 3
    for i, f in enumerate(folds):
        assert f["train_end"] < f["test_start"]
        if i > 0:
            assert folds[i]["train_end"] > folds[i - 1]["train_end"]


def test_oos_parameter_selection_forbidden():
    before = {"top_n": 10}
    after = {"top_n": 10}
    assert_no_oos_parameter_selection(parameters_before_oos=before, parameters_after_oos=after)
    with pytest.raises(ValidationConfigError, match="retune"):
        assert_no_oos_parameter_selection(
            parameters_before_oos=before,
            parameters_after_oos={"top_n": 20},
        )


def test_run_validation_dry_run_phases_and_no_shuffle():
    out = run_validation(_cfg())
    assert out["shuffle_used"] is False
    assert out["status"] == "DRY_RUN"
    assert out["phases"]["IS"]["status"] == "DRY_RUN"
    assert out["phases"]["VALIDATION"]["status"] == "DRY_RUN"
    assert out["phases"]["OOS"]["status"] == "DRY_RUN"
    assert out["production_buy_emitted"] is False
    assert out["profitable_claim"] is False
    assert out["cost_model"] == "NOT_CONFIGURED"
    assert out["slippage_model"] == "NOT_CONFIGURED"
    assert out["survivorship_status"] == "NOT_VALIDATED"
    assert out["return_is_net_tradable"] is False
    assert out["eligibility"]["eligibility_status"] == "INCONCLUSIVE"


def test_is_validation_oos_isolation_via_ranges():
    out = run_validation(_cfg())
    is_end = out["phases"]["IS"]["requested_range"]["end"]
    val_start = out["phases"]["VALIDATION"]["requested_range"]["start"]
    val_end = out["phases"]["VALIDATION"]["requested_range"]["end"]
    oos_start = out["phases"]["OOS"]["requested_range"]["start"]
    assert is_end < val_start
    assert val_end < oos_start


def test_overlap_config_rejected():
    d = ValidationWindow("2024-01-01", "2024-05-01")
    v = ValidationWindow("2024-04-01", "2024-06-30")
    o = ValidationWindow("2024-07-01", "2024-09-30")
    out = run_validation(_cfg(discovery=d, validation=v, oos=o))
    assert out["status"] == "REJECTED"
    assert "overlap" in (out.get("failure_reason") or "")


def test_insufficient_data_when_oos_outside_coverage():
    out = run_validation(
        _cfg(
            dry_run=False,
            evaluate_fn=_ok_eval,
            data_available_start="2024-01-01",
            data_available_end="2024-06-15",  # OOS Jul-Sep outside
        )
    )
    assert out["phases"]["OOS"]["status"] == "INSUFFICIENT_DATA"
    assert out["phases"]["OOS"]["actual_used_range"] is None
    assert out["eligibility"]["eligibility_status"] == "INSUFFICIENT_DATA"


def test_sample_gate_insufficient_data():
    def tiny_eval(*_a, **_k):
        return (
            {"total_trades": 2, "total_return_pct": 99.0, "win_rate_pct": 100.0},
            None,
        )

    out = run_validation(_cfg(dry_run=False, evaluate_fn=tiny_eval, min_sample=DEFAULT_MIN_SAMPLE))
    assert out["phases"]["IS"]["status"] == "INSUFFICIENT_DATA"
    assert "min_sample" in (out["phases"]["IS"]["failure_reason"] or "")


def test_research_eligibility_not_production():
    ok = {
        "status": "OK",
        "sample_count": 40,
    }
    el = evaluate_research_eligibility(
        is_result=ok,
        validation_result=ok,
        oos_result=ok,
        walk_forward_result=None,
        require_walk_forward=False,
    )
    assert el["eligibility_status"] == RESEARCH_ELIGIBLE_STATUS
    assert el["production_status"] is None
    assert el["production_buy_emitted"] is False
    for bad in FORBIDDEN_VALIDATION_STATUSES:
        assert bad != el["eligibility_status"]


def test_full_validation_with_synthetic_eval_and_walk_forward():
    wf = WalkForwardConfig(
        train_start="2024-01-01",
        first_train_end="2024-03-31",
        test_span_calendar_days=30,
        step_calendar_days=30,
        n_folds=2,
    )
    out = run_validation(
        _cfg(
            dry_run=False,
            evaluate_fn=_ok_eval,
            walk_forward=wf,
            data_available_start="2024-01-01",
            data_available_end="2024-12-31",
        )
    )
    assert out["status"] == "COMPLETED"
    assert out["phases"]["IS"]["gate"] == "IS_SUCCESS"
    assert out["phases"]["VALIDATION"]["gate"] == "VALIDATION_SUCCESS"
    assert out["phases"]["OOS"]["gate"] == "OOS_SUCCESS"
    assert out["eligibility"]["eligibility_status"] == RESEARCH_ELIGIBLE_STATUS
    assert out["phases"]["WALK_FORWARD"]["status"] in ("OK", "PARTIAL")
    assert len(out["phases"]["WALK_FORWARD"]["folds"]) == 2
    agg = out["phases"]["WALK_FORWARD"]["aggregate"]
    assert agg["fold_count"] == 2
    assert "fold_success_count" in agg
    assert out["production_buy_emitted"] is False
    assert "PRODUCTION" not in str(out["eligibility"]["eligibility_status"])


def test_parameter_selection_phase_cannot_be_oos():
    out = run_validation(_cfg(parameter_selection_phase="OOS"))
    assert out["status"] == "REJECTED"
    assert "OOS selection forbidden" in (out.get("failure_reason") or "")


def test_future_feature_rejection():
    with pytest.raises(CandidateValidationError):
        assert_no_future_feature("2024-08-01", "2024-07-01", feature_name="fs")


def test_metrics_adapter_no_fake_zeros():
    shell = mark_unavailable_shell()
    assert shell["mfe"] is None
    assert shell["mae"] is None
    adapted = adapt_backtest_metrics(
        {"total_trades": 0, "total_return_pct": 0.0, "sharpe_ratio": 0.0}
    )
    assert adapted["total_return_pct"] is None
    assert adapted["return_is_net_tradable"] is False
    adapted_ok = adapt_backtest_metrics(
        {
            "total_trades": 10,
            "total_return_pct": 1.5,
            "win_rate_pct": 50.0,
            "avg_trade_return_pct": 0.15,
            "holding_days": 7,
        }
    )
    assert adapted_ok["mfe"] is None
    assert adapted_ok["mfe_status"] == "NOT_AVAILABLE"
    assert adapted_ok["sample_count"] == 10


def test_run_validation_points_to_robustness_without_executing():
    out = run_validation(_cfg())
    assert out["robustness"]["status"] == "NOT_EXECUTED"
    assert out["eligibility"]["eligibility_basis"].startswith("DATA_SUFFICIENCY")


def test_walk_forward_requires_every_fold_ok():
    wf = WalkForwardConfig(
        train_start="2024-01-01",
        first_train_end="2024-03-31",
        test_span_calendar_days=30,
        step_calendar_days=30,
        n_folds=2,
    )

    def one_fold_fails(strategy, holding, start, end, params):
        raw, _ = _ok_eval(strategy, holding, start, end, params)
        if start == "2024-05-01":
            raw = {**raw, "total_trades": 1}
        return raw, None

    out = run_validation(_cfg(dry_run=False, evaluate_fn=one_fold_fails, walk_forward=wf))
    assert out["phases"]["WALK_FORWARD"]["status"] == "PARTIAL"
    assert out["eligibility"]["gates"]["WALK_FORWARD_SUCCESS"] is False
    assert out["eligibility"]["eligibility_status"] != RESEARCH_ELIGIBLE_STATUS


def test_overlapping_walk_forward_folds_rejected_not_raised():
    wf = WalkForwardConfig(
        train_start="2024-01-01",
        first_train_end="2024-03-31",
        test_span_calendar_days=60,
        step_calendar_days=30,
        n_folds=2,
    )
    out = run_validation(_cfg(dry_run=False, evaluate_fn=_ok_eval, walk_forward=wf))
    assert out["status"] == "REJECTED"
    assert out["phases"]["WALK_FORWARD"]["status"] == "REJECTED"
    assert out["eligibility"]["eligibility_status"] != RESEARCH_ELIGIBLE_STATUS


def test_expectancy_uses_explicit_ledger_units():
    import pandas as pd

    # Fraction ledger with a >150% trade must still be scaled to percent.
    trades = pd.DataFrame({"Return": [2.0, -0.5], "ReturnPct": [200.0, -50.0]})
    adapted = adapt_backtest_metrics({"total_trades": 2, "holding_days": 7}, trades_df=trades)
    assert adapted["expectancy_pct"] == 75.0
    pct_only = adapt_backtest_metrics(
        {"total_trades": 2, "holding_days": 7},
        trades_df=pd.DataFrame({"ReturnPct": [1.0, 0.5]}),
    )
    assert pct_only["expectancy_pct"] == 0.75


def test_production_status_impossible_from_cluster3():
    out = run_validation(_cfg(dry_run=False, evaluate_fn=_ok_eval))
    status = out["eligibility"]["eligibility_status"]
    assert status == RESEARCH_ELIGIBLE_STATUS
    assert status not in FORBIDDEN_VALIDATION_STATUSES
    assert out["eligibility"]["production_status"] is None
    assert out["production_buy_emitted"] is False
    assert out["profitable_claim"] is False
