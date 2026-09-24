"""Cluster 2 — discovery runner + trial registry focused tests."""

from __future__ import annotations

import pytest

from idx.signal_discovery.contract import ENGINE_VERSION, REQUIRED_LINEAGE_FIELDS
from idx.signal_discovery.hypotheses import STAGE1_HYPOTHESES, list_stage1_hypotheses
from idx.signal_discovery.registry import (
    COST_MODEL_DEFAULT,
    FORBIDDEN_RUNNER_STATUSES,
    SLIPPAGE_MODEL_DEFAULT,
    SURVIVORSHIP_DEFAULT,
    TRIAL_REQUIRED_FIELDS,
    TrialRegistry,
    TrialRegistryError,
    empty_metrics_record,
    normalize_engine_metrics,
)
from idx.signal_discovery.runner import (
    DiscoveryConfig,
    make_trial_id,
    run_stage1_discovery,
)


def test_stage1_families_are_small_and_curated():
    families = {h["hypothesis_family"] for h in STAGE1_HYPOTHESES}
    assert families == {
        "TREND",
        "MOMENTUM",
        "BREAKOUT",
        "PULLBACK",
        "MEAN_REVERSION",
        "VOLUME_EXPANSION",
        "RELATIVE_STRENGTH",
    }
    assert len(STAGE1_HYPOTHESES) == 7
    # Every family maps to a strategy the single engine actually supports
    from idx.backtest import SUPPORTED_STRATEGIES

    engines = {h["engine_strategy"] for h in STAGE1_HYPOTHESES}
    assert engines <= SUPPORTED_STRATEGIES


def test_trial_id_deterministic_and_unique_per_strategy():
    cfg = DiscoveryConfig(
        horizon="SWING_3_10D",
        discovery_period=("2026-01-01", "2026-03-01"),
        dry_run=True,
    )
    a = make_trial_id(
        strategy_id="s1_trend_composite",
        horizon=cfg.horizon,
        parameters={"top_n": 10},
        config=cfg,
    )
    b = make_trial_id(
        strategy_id="s1_trend_composite",
        horizon=cfg.horizon,
        parameters={"top_n": 10},
        config=cfg,
    )
    c = make_trial_id(
        strategy_id="s1_relative_strength_foreign",
        horizon=cfg.horizon,
        parameters={"top_n": 10},
        config=cfg,
    )
    assert a == b
    assert a != c


def test_required_lineage_and_trial_fields():
    for f in (
        "trial_id",
        "strategy_id",
        "horizon",
        "cost_model",
        "slippage_model",
        "status",
        "metrics",
    ):
        assert f in TRIAL_REQUIRED_FIELDS
    # Contract lineage still includes discovery fields used by runner trials
    assert "hypothesis" in REQUIRED_LINEAGE_FIELDS
    assert "parameter_set" in REQUIRED_LINEAGE_FIELDS


def test_horizon_validation_rejects_unknown():
    out = run_stage1_discovery(DiscoveryConfig(horizon="NOT_A_HORIZON", dry_run=True))
    assert out["status"] == "REJECTED"
    assert "invalid horizon" in (out.get("failure_reason") or "")


def test_intraday_and_multibagger_insufficient_data_no_fallback():
    for horizon in ("INTRADAY", "MULTIBAGGER_1_5Y", "LONG_TERM_3_12M"):
        out = run_stage1_discovery(
            DiscoveryConfig(
                horizon=horizon,
                discovery_period=("2026-01-01", "2026-06-01"),
                dry_run=True,
                max_trials=7,
            )
        )
        trials = out["registry"]["trials"]
        assert trials
        assert all(t["status"] == "INSUFFICIENT_DATA" for t in trials)
        # Must not silently rewrite horizon
        assert all(t["horizon"] == horizon for t in trials)


def test_max_trials_enforcement_records_limit():
    out = run_stage1_discovery(
        DiscoveryConfig(
            horizon="SWING_3_10D",
            discovery_period=("2026-01-01", "2026-06-01"),
            dry_run=True,
            max_trials=2,
        )
    )
    assert out["trial_limit_reached"] is True
    assert out["status"] == "TRIAL_LIMIT_REACHED"
    assert out["trials_attempted"] == 2
    statuses = [t["status"] for t in out["registry"]["trials"]]
    assert "TRIAL_LIMIT_REACHED" in statuses
    # 2 evaluated + 1 limit marker
    assert len(out["registry"]["trials"]) == 3


def test_deterministic_config_same_trial_ids():
    kwargs = dict(
        horizon="NEXT_DAY_1_3D",
        discovery_period=("2026-01-01", "2026-02-01"),
        dry_run=True,
        max_trials=7,
        data_as_of="2026-02-01",
        signal_timestamp="2026-02-01",
    )
    a = run_stage1_discovery(DiscoveryConfig(**kwargs))
    b = run_stage1_discovery(DiscoveryConfig(**kwargs))
    ids_a = [t["trial_id"] for t in a["registry"]["trials"]]
    ids_b = [t["trial_id"] for t in b["registry"]["trials"]]
    assert ids_a == ids_b
    assert len(ids_a) == len(set(ids_a))


def test_all_stage1_families_wired_to_engine():
    out = run_stage1_discovery(
        DiscoveryConfig(
            horizon="SWING_3_10D",
            discovery_period=("2026-01-01", "2026-06-01"),
            dry_run=True,
            max_trials=7,
        )
    )
    by_family = {t["hypothesis_family"]: t for t in out["registry"]["trials"]}
    assert len(by_family) == 7
    assert all(t["status"] == "DISCOVERED" for t in by_family.values())


def test_no_fake_zero_metrics_when_unavailable():
    empty = empty_metrics_record()
    assert empty["mfe"] is None
    assert empty["mae"] is None
    assert empty["expectancy_pct"] is None
    assert empty["total_return_pct"] is None

    # Empty-engine zeros must not be copied as proven performance
    normalized = normalize_engine_metrics(
        {
            "total_trades": 0,
            "total_return_pct": 0.0,
            "win_rate_pct": 0.0,
            "sharpe_ratio": 0.0,
            "mfe": 0.0,
        }
    )
    assert normalized["sample_count"] == 0
    assert normalized["total_return_pct"] is None
    assert normalized["win_rate_pct"] is None
    assert normalized["sharpe_ratio"] is None
    assert normalized["mfe"] is None
    assert normalized["mfe_status"] == "NOT_AVAILABLE"


def test_cost_slippage_and_survivorship_honesty():
    out = run_stage1_discovery(
        DiscoveryConfig(
            horizon="SWING_3_10D",
            discovery_period=("2026-01-01", "2026-06-01"),
            dry_run=True,
            max_trials=3,
        )
    )
    assert out["cost_model"] == COST_MODEL_DEFAULT == "NOT_CONFIGURED"
    assert out["slippage_model"] == SLIPPAGE_MODEL_DEFAULT == "NOT_CONFIGURED"
    assert out["survivorship_status"] == SURVIVORSHIP_DEFAULT == "NOT_VALIDATED"
    for t in out["registry"]["trials"]:
        assert t["cost_model"] == "NOT_CONFIGURED"
        assert t["slippage_model"] == "NOT_CONFIGURED"
        assert t["survivorship_status"] == "NOT_VALIDATED"
        assert t["return_is_net_tradable"] is False
        assert t["profitable_claim"] is False


def test_leakage_invariant_rejects_future_data_as_of():
    out = run_stage1_discovery(
        DiscoveryConfig(
            horizon="SWING_3_10D",
            discovery_period=("2026-01-01", "2026-06-01"),
            signal_timestamp="2026-03-01",
            data_as_of="2026-06-01",  # after signal — forbidden
            dry_run=True,
        )
    )
    assert out["status"] == "REJECTED"
    assert "leakage" in (out.get("failure_reason") or "").lower()


def test_production_status_cannot_be_emitted():
    reg = TrialRegistry()
    bad = {
        "trial_id": "x",
        "strategy_id": "s",
        "strategy_version": "0",
        "horizon": "SWING_3_10D",
        "hypothesis": "h",
        "feature_set": [],
        "parameters": {},
        "universe_definition": "u",
        "discovery_period": None,
        "validation_period": None,
        "oos_period": None,
        "cost_model": COST_MODEL_DEFAULT,
        "slippage_model": SLIPPAGE_MODEL_DEFAULT,
        "engine_version": ENGINE_VERSION,
        "data_version": "1.0.0",
        "data_quality": "B",
        "created_at": "2026-01-01T00:00:00+00:00",
        "status": "PRODUCTION_CANDIDATE",
        "metrics": empty_metrics_record(),
        "failure_reason": None,
    }
    with pytest.raises(TrialRegistryError):
        reg.register(bad)
    assert "PRODUCTION_CANDIDATE" in FORBIDDEN_RUNNER_STATUSES

    out = run_stage1_discovery(DiscoveryConfig(horizon="SWING_3_10D", dry_run=True, max_trials=7))
    assert out["production_buy_emitted"] is False
    assert out["profitable_claim"] is False
    for t in out["registry"]["trials"]:
        assert t["status"] not in FORBIDDEN_RUNNER_STATUSES
    for row in out["inspection"]:
        assert row["selection_label"] == "candidate for further validation"
        assert "BEST" not in str(row.get("selection_label"))
        assert "WINNER" not in str(row.get("selection_label"))


def test_list_stage1_hypotheses_copies():
    a = list_stage1_hypotheses()
    a[0]["parameter_set"]["top_n"] = 999
    b = list_stage1_hypotheses()
    assert b[0]["parameter_set"].get("top_n") != 999
