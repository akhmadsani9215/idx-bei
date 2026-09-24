"""Focused contract/invariant tests for Signal Discovery Lab (Cluster 1)."""

from __future__ import annotations

import pytest

from idx.signal_discovery.contract import (
    BUY_SIGNAL_LABEL,
    CANDIDATE_STATUSES,
    HORIZONS,
    REQUIRED_LINEAGE_FIELDS,
    SCREENER_TIMEFRAME_TO_HORIZON,
    CandidateValidationError,
    assert_buy_not_from_insufficient_data,
    assert_no_future_feature,
    assert_production_eligibility,
    assert_rejected_cannot_skip_to_production,
    assert_signal_as_of_ordering,
    assert_status_transition,
    empty_multiple_testing_record,
    is_valid_horizon,
    is_valid_status,
    validate_candidate_metadata,
)


def _minimal_meta(**overrides):
    base = {
        "strategy_id": "hyp_trend_pullback",
        "strategy_version": "0.1.0",
        "horizon": "SWING_3_10D",
        "universe_definition": "IDX listed, min turnover 1e9 IDR",
        "feature_set": ["ema20", "ema50", "atr14"],
        "entry_rule": "close > ema20 after pullback to ema50",
        "exit_rule": "holding_period_limit or CL1",
        "tp_methodology": "structure_swing_high",
        "cl_methodology": "structure_swing_low",
        "minimum_rr": 2.0,
        "holding_period_limit": 10,
        "signal_timestamp": "2026-06-01",
        "data_as_of": "2026-06-01",
        "data_quality": "B",
        "source": "parquet.stock_summary",
        "engine_version": "signal-discovery-1.0",
        "discovery_method": "STAGE_1_HYPOTHESIS",
        "hypothesis": "Pullbacks in uptrend mean-reversion entry",
        "parameter_set": {"ema_fast": 20, "ema_slow": 50},
        "cost_model": "UNAVAILABLE",
        "slippage_model": "UNAVAILABLE",
        "status": "DISCOVERED",
    }
    base.update(overrides)
    return base


def test_horizon_validity():
    assert len(HORIZONS) == 7
    for h in HORIZONS:
        assert is_valid_horizon(h)
    assert not is_valid_horizon("SWING")
    assert not is_valid_horizon("")
    assert not is_valid_horizon(None)


def test_screener_timeframe_map_is_explicit():
    assert SCREENER_TIMEFRAME_TO_HORIZON["close_pressure"] == "NEXT_DAY_1_3D"
    assert SCREENER_TIMEFRAME_TO_HORIZON["swing"] == "SWING_3_10D"
    assert SCREENER_TIMEFRAME_TO_HORIZON["long_term"] == "LONG_TERM_3_12M"


def test_candidate_status_validity():
    assert "PRODUCTION_CANDIDATE" in CANDIDATE_STATUSES
    assert "INSUFFICIENT_DATA" in CANDIDATE_STATUSES
    for s in CANDIDATE_STATUSES:
        assert is_valid_status(s)
    assert not is_valid_status("PROFITABLE")
    assert not is_valid_status("BUY")


def test_required_lineage_fields():
    assert "strategy_id" in REQUIRED_LINEAGE_FIELDS
    assert "signal_timestamp" in REQUIRED_LINEAGE_FIELDS
    assert "data_as_of" in REQUIRED_LINEAGE_FIELDS
    assert "cost_model" in REQUIRED_LINEAGE_FIELDS
    errors = validate_candidate_metadata({"status": "DISCOVERED"})
    assert any("missing required field" in e for e in errors)
    assert validate_candidate_metadata(_minimal_meta()) == []


def test_signal_timestamp_as_of_ordering():
    assert assert_signal_as_of_ordering("2026-06-10", "2026-06-01")
    with pytest.raises(CandidateValidationError):
        assert_signal_as_of_ordering("2026-06-01", "2026-06-10")
    errors = validate_candidate_metadata(
        _minimal_meta(signal_timestamp="2026-01-01", data_as_of="2026-06-01")
    )
    assert any("data_as_of" in e for e in errors)


def test_no_future_feature_allowed():
    assert assert_no_future_feature("2026-05-01", "2026-06-01", feature_name="per")
    with pytest.raises(CandidateValidationError):
        assert_no_future_feature("2026-07-01", "2026-06-01", feature_name="future_close")
    errors = validate_candidate_metadata(
        _minimal_meta(),
        feature_as_of_map={"fs_filing": "2026-12-01"},
    )
    assert any("Future feature" in e for e in errors)


def test_production_eligibility_cannot_bypass_oos():
    assert assert_production_eligibility("CANDIDATE", has_oos=False)
    with pytest.raises(CandidateValidationError):
        assert_production_eligibility("PRODUCTION_CANDIDATE", has_oos=False)
    assert assert_production_eligibility("PRODUCTION_CANDIDATE", has_oos=True, oos_status="OK")
    errors = validate_candidate_metadata(
        _minimal_meta(status="PRODUCTION_CANDIDATE"),
        has_oos=False,
    )
    assert any("OOS" in e for e in errors)


def test_insufficient_data_cannot_become_buy():
    with pytest.raises(CandidateValidationError):
        assert_buy_not_from_insufficient_data("INSUFFICIENT_DATA", BUY_SIGNAL_LABEL)
    with pytest.raises(CandidateValidationError):
        assert_buy_not_from_insufficient_data("INCONCLUSIVE", BUY_SIGNAL_LABEL)
    with pytest.raises(CandidateValidationError):
        assert_buy_not_from_insufficient_data("REJECTED", BUY_SIGNAL_LABEL)
    assert assert_buy_not_from_insufficient_data("INSUFFICIENT_DATA", None)
    assert assert_buy_not_from_insufficient_data("CANDIDATE", BUY_SIGNAL_LABEL)
    errors = validate_candidate_metadata(_minimal_meta(status="INSUFFICIENT_DATA", signal="BUY"))
    assert any("cannot emit BUY" in e for e in errors)


def test_rejected_cannot_become_production_without_revalidation():
    with pytest.raises(CandidateValidationError):
        assert_rejected_cannot_skip_to_production("REJECTED", "PRODUCTION_CANDIDATE")
    with pytest.raises(CandidateValidationError):
        assert_status_transition("REJECTED", "PRODUCTION_CANDIDATE")
    # Revalidation path allowed
    assert assert_status_transition("REJECTED", "DISCOVERED")
    assert assert_status_transition("REJECTED", "BACKTESTING")


def test_multiple_testing_record_does_not_claim_significance():
    rec = empty_multiple_testing_record()
    assert rec["statistical_significance_claimed"] is False
    assert rec["oos_result"] is None
