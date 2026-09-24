"""Discovery runner skeleton — Stage-1 hypotheses → trial registry.

Uses existing ``idx.backtest.run_backtest`` only. Does not alter production
screener rules, does not emit PRODUCTION statuses, does not claim profitability.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from idx.schema_version import DATA_SCHEMA_VERSION
from idx.signal_discovery.contract import (
    ENGINE_VERSION,
    assert_no_future_feature,
    assert_signal_as_of_ordering,
    is_valid_horizon,
)
from idx.signal_discovery.hypotheses import (
    FEATURE_VERSION,
    STRATEGY_VERSION,
    horizon_policy,
    list_stage1_hypotheses,
)
from idx.signal_discovery.registry import (
    COST_MODEL_DEFAULT,
    FORBIDDEN_RUNNER_STATUSES,
    SLIPPAGE_MODEL_DEFAULT,
    SURVIVORSHIP_DEFAULT,
    TrialRegistry,
    normalize_engine_metrics,
)

DEFAULT_MAX_TRIALS = 7
DEFAULT_UNIVERSE = (
    "IDX listed equities from stock_summary Parquet; "
    "min_turnover filter per hypothesis parameters; "
    "survivorship NOT_VALIDATED (current listed universe only)"
)


@dataclass
class DiscoveryConfig:
    """Deterministic discovery run configuration."""

    horizon: str
    discovery_period: tuple[str, str] | None = None  # (start, end) YYYY-MM-DD
    validation_period: tuple[str, str] | None = None
    oos_period: tuple[str, str] | None = None
    max_trials: int = DEFAULT_MAX_TRIALS
    universe_definition: str = DEFAULT_UNIVERSE
    top_n: int = 10
    min_turnover_rp: float = 1_000_000_000
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    random_seed: int | None = None  # unused in Stage-1 (deterministic screens)
    data_quality: str = "B"
    # Optional injected frames for isolated tests / offline eval
    stock_df: Any = None
    ratios_df: Any = None
    actions_df: Any = None
    # When True, skip calling run_backtest (unit tests of registry/limit only)
    dry_run: bool = False
    # Evaluation as_of / signal timestamps for leakage checks (defaults to period end)
    signal_timestamp: str | None = None
    data_as_of: str | None = None
    hypothesis_ids: list[str] | None = None  # optional filter
    engine_version: str = ENGINE_VERSION
    strategy_version: str = STRATEGY_VERSION
    feature_version: str = FEATURE_VERSION
    data_version: str = DATA_SCHEMA_VERSION
    extra: dict[str, Any] = field(default_factory=dict)

    def fingerprint_payload(self) -> dict[str, Any]:
        """Stable subset used for trial_id hashing (no wall-clock, no DataFrames)."""
        return {
            "horizon": self.horizon,
            "discovery_period": self.discovery_period,
            "validation_period": self.validation_period,
            "oos_period": self.oos_period,
            "max_trials": self.max_trials,
            "universe_definition": self.universe_definition,
            "top_n": self.top_n,
            "min_turnover_rp": self.min_turnover_rp,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
            "random_seed": self.random_seed,
            "data_quality": self.data_quality,
            "dry_run": self.dry_run,
            "signal_timestamp": self.signal_timestamp,
            "data_as_of": self.data_as_of,
            "hypothesis_ids": self.hypothesis_ids,
            "engine_version": self.engine_version,
            "strategy_version": self.strategy_version,
            "feature_version": self.feature_version,
            "data_version": self.data_version,
            "has_injected_stock": self.stock_df is not None,
            "has_injected_ratios": self.ratios_df is not None,
        }


def make_trial_id(
    *,
    strategy_id: str,
    horizon: str,
    parameters: dict[str, Any],
    config: DiscoveryConfig,
) -> str:
    """Deterministic trial id from strategy + horizon + params + config fingerprint."""
    payload = {
        "strategy_id": strategy_id,
        "horizon": horizon,
        "parameters": parameters,
        "config": config.fingerprint_payload(),
    }
    blob = json.dumps(payload, sort_keys=True, default=str)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
    return f"trial_{strategy_id}_{horizon}_{digest}"


def _period_dict(period: tuple[str, str] | None) -> dict[str, str] | None:
    if period is None:
        return None
    return {"start": period[0], "end": period[1]}


def _resolve_timestamps(config: DiscoveryConfig) -> tuple[str, str]:
    """data_as_of <= signal_timestamp; prefer explicit, else discovery period end."""
    end = None
    if config.discovery_period:
        end = config.discovery_period[1]
    signal_ts = config.signal_timestamp or end or "1970-01-01"
    data_as_of = config.data_as_of or end or signal_ts
    return signal_ts, data_as_of


def _assert_leakage_invariants(config: DiscoveryConfig) -> None:
    signal_ts, data_as_of = _resolve_timestamps(config)
    assert_signal_as_of_ordering(signal_ts, data_as_of)
    # Feature as_of must not exceed entry/signal time (same bound for Stage-1).
    assert_no_future_feature(data_as_of, signal_ts, feature_name="trial_feature_as_of")
    # entry_time == signal_timestamp in Stage-1 backtest contract
    assert_no_future_feature(data_as_of, signal_ts, feature_name="entry_time_bound")


def _base_trial(
    *,
    trial_id: str,
    hyp: dict[str, Any],
    config: DiscoveryConfig,
    parameters: dict[str, Any],
    status: str,
    metrics: dict[str, Any],
    failure_reason: str | None,
    holding_days: int | None,
) -> dict[str, Any]:
    if status in FORBIDDEN_RUNNER_STATUSES:
        raise ValueError(f"Runner cannot emit forbidden status: {status}")
    signal_ts, data_as_of = _resolve_timestamps(config)
    return {
        "trial_id": trial_id,
        "strategy_id": hyp["strategy_id"],
        "strategy_version": config.strategy_version,
        "horizon": config.horizon,
        "hypothesis": hyp["hypothesis"],
        "hypothesis_family": hyp.get("hypothesis_family"),
        "feature_set": list(hyp.get("feature_set") or []),
        "feature_version": config.feature_version,
        "parameters": parameters,
        "parameter_count": int(hyp.get("parameter_count") or len(parameters)),
        "universe_definition": config.universe_definition,
        "discovery_period": _period_dict(config.discovery_period),
        "validation_period": _period_dict(config.validation_period),
        "oos_period": _period_dict(config.oos_period),
        "cost_model": COST_MODEL_DEFAULT,
        "slippage_model": SLIPPAGE_MODEL_DEFAULT,
        "engine_version": config.engine_version,
        "data_version": config.data_version,
        "data_quality": config.data_quality,
        "created_at": datetime.now(UTC).isoformat(),
        "status": status,
        "metrics": metrics,
        "failure_reason": failure_reason,
        "survivorship_status": SURVIVORSHIP_DEFAULT,
        "random_seed": config.random_seed,
        "entry_rule": hyp.get("entry_rule"),
        "exit_rule": hyp.get("exit_rule"),
        "tp_methodology": hyp.get("tp_methodology"),
        "cl_methodology": hyp.get("cl_methodology"),
        "holding_period_limit": holding_days,
        "signal_timestamp": signal_ts,
        "data_as_of": data_as_of,
        "engine_strategy": hyp.get("engine_strategy"),
        "discovery_method": "STAGE_1_HYPOTHESIS",
        "selection_label": None,
        "profitable_claim": False,
        "return_is_net_tradable": False,
        "notes": (
            "Descriptive evaluation only. Not profitability proof. Not a production BUY signal."
        ),
    }


def _evaluate_backtest(
    *,
    engine_strategy: str,
    holding_days: int,
    config: DiscoveryConfig,
    parameters: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    """Call existing run_backtest; return (normalized_metrics, failure_reason)."""
    from idx.backtest import run_backtest

    kwargs: dict[str, Any] = {
        "strategy": engine_strategy,
        "holding_days": holding_days,
        "top_n": int(parameters.get("top_n", config.top_n)),
        "min_turnover_rp": float(parameters.get("min_turnover_rp", config.min_turnover_rp)),
    }
    if config.discovery_period:
        kwargs["start_date"] = config.discovery_period[0]
        kwargs["end_date"] = config.discovery_period[1]
    if config.stop_loss_pct is not None:
        kwargs["stop_loss_pct"] = config.stop_loss_pct
    if config.take_profit_pct is not None:
        kwargs["take_profit_pct"] = config.take_profit_pct
    if config.stock_df is not None:
        kwargs["stock_df"] = config.stock_df
    if config.ratios_df is not None:
        kwargs["ratios_df"] = config.ratios_df
    if config.actions_df is not None:
        kwargs["actions_df"] = config.actions_df

    # Isolated injected runs must supply both frames for non-dividend strategies.
    if (
        config.stock_df is not None
        and config.ratios_df is None
        and engine_strategy != "dividend_arbitrage"
    ):
        return normalize_engine_metrics(None), (
            "INSUFFICIENT_DATA — ratios_df required with injected stock_df "
            "(no silent load of live Parquet in isolated mode)"
        )
    if config.ratios_df is not None and config.stock_df is None:
        return normalize_engine_metrics(None), (
            "INSUFFICIENT_DATA — stock_df required with injected ratios_df"
        )

    raw, _trades = run_backtest(**kwargs)
    metrics = normalize_engine_metrics(raw if isinstance(raw, dict) else None)
    if metrics.get("sample_count", 0) <= 0:
        return metrics, "INCONCLUSIVE — zero trades / empty evaluation window"
    return metrics, None


def run_stage1_discovery(config: DiscoveryConfig) -> dict[str, Any]:
    """Run Stage-1 curated hypotheses for one horizon into a TrialRegistry.

    Stops cleanly when ``max_trials`` is reached (records TRIAL_LIMIT_REACHED).
    Never emits PRODUCTION / PRODUCTION_CANDIDATE / BEST / WINNER labels.
    """
    registry = TrialRegistry()

    if not is_valid_horizon(config.horizon):
        registry.run_notes.append(f"Invalid horizon: {config.horizon!r}")
        return {
            "status": "REJECTED",
            "failure_reason": f"invalid horizon: {config.horizon}",
            "registry": registry.to_dict(),
            "inspection": [],
            "profitable_claim": False,
            "production_buy_emitted": False,
            "max_trials": config.max_trials,
            "trials_attempted": 0,
            "trial_limit_reached": False,
        }

    if config.max_trials < 1:
        registry.run_notes.append("max_trials < 1")
        return {
            "status": "REJECTED",
            "failure_reason": "max_trials must be >= 1",
            "registry": registry.to_dict(),
            "inspection": [],
            "profitable_claim": False,
            "production_buy_emitted": False,
            "max_trials": config.max_trials,
            "trials_attempted": 0,
            "trial_limit_reached": False,
        }

    try:
        _assert_leakage_invariants(config)
    except Exception as exc:  # noqa: BLE001 — surface as run failure
        registry.run_notes.append(f"Leakage invariant failed: {exc}")
        return {
            "status": "REJECTED",
            "failure_reason": f"leakage_invariant: {exc}",
            "registry": registry.to_dict(),
            "inspection": [],
            "profitable_claim": False,
            "production_buy_emitted": False,
            "max_trials": config.max_trials,
            "trials_attempted": 0,
            "trial_limit_reached": False,
        }

    policy = horizon_policy(config.horizon)
    hypotheses = list_stage1_hypotheses()
    if config.hypothesis_ids:
        allow = set(config.hypothesis_ids)
        hypotheses = [h for h in hypotheses if h["strategy_id"] in allow]

    trials_attempted = 0
    trial_limit_reached = False
    holding_days = policy.get("holding_days")

    for hyp in hypotheses:
        if trials_attempted >= config.max_trials:
            trial_limit_reached = True
            # Explicit limit marker trial (does not evaluate further hypotheses)
            limit_params = {"max_trials": config.max_trials, "stopped_before": hyp["strategy_id"]}
            limit_id = make_trial_id(
                strategy_id="trial_limit",
                horizon=config.horizon,
                parameters=limit_params,
                config=config,
            )
            # Ensure unique even if re-run: include attempted count
            limit_id = f"{limit_id}_{trials_attempted}"
            registry.register(
                _base_trial(
                    trial_id=limit_id,
                    hyp={
                        **hyp,
                        "strategy_id": "trial_limit",
                        "hypothesis": "Trial limit reached — remaining Stage-1 hypotheses not evaluated",
                        "hypothesis_family": "LIMIT",
                        "feature_set": [],
                        "engine_strategy": None,
                        "entry_rule": "N/A",
                        "exit_rule": "N/A",
                        "tp_methodology": "N/A",
                        "cl_methodology": "N/A",
                        "parameter_count": 0,
                    },
                    config=config,
                    parameters=limit_params,
                    status="TRIAL_LIMIT_REACHED",
                    metrics=normalize_engine_metrics(None),
                    failure_reason="TRIAL_LIMIT_REACHED",
                    holding_days=holding_days if isinstance(holding_days, int) else None,
                )
            )
            registry.run_notes.append(
                f"TRIAL_LIMIT_REACHED at max_trials={config.max_trials}; "
                f"not silently truncating remaining hypotheses"
            )
            break

        trials_attempted += 1
        parameters = dict(hyp.get("parameter_set") or {})
        parameters.setdefault("top_n", config.top_n)
        parameters.setdefault("min_turnover_rp", config.min_turnover_rp)
        if holding_days is not None:
            parameters["holding_days"] = holding_days

        trial_id = make_trial_id(
            strategy_id=hyp["strategy_id"],
            horizon=config.horizon,
            parameters=parameters,
            config=config,
        )

        # Horizon not executable → INSUFFICIENT_DATA (no silent horizon change)
        if not policy.get("executable", False) or holding_days is None:
            registry.register(
                _base_trial(
                    trial_id=trial_id,
                    hyp=hyp,
                    config=config,
                    parameters=parameters,
                    status="INSUFFICIENT_DATA",
                    metrics=normalize_engine_metrics(None),
                    failure_reason=policy.get("reason") or "horizon not executable",
                    holding_days=None,
                )
            )
            continue

        # Engine not available for this family
        engine = hyp.get("engine_strategy")
        if engine is None:
            registry.register(
                _base_trial(
                    trial_id=trial_id,
                    hyp=hyp,
                    config=config,
                    parameters=parameters,
                    status="INSUFFICIENT_DATA",
                    metrics=normalize_engine_metrics(None),
                    failure_reason=hyp.get("unavailable_reason")
                    or "engine_strategy unavailable — features/strategy not productized",
                    holding_days=int(holding_days),
                )
            )
            continue

        if config.dry_run:
            registry.register(
                _base_trial(
                    trial_id=trial_id,
                    hyp=hyp,
                    config=config,
                    parameters=parameters,
                    status="DISCOVERED",
                    metrics=normalize_engine_metrics(None),
                    failure_reason="dry_run — evaluation not executed",
                    holding_days=int(holding_days),
                )
            )
            continue

        # Evaluate via existing backtest engine
        metrics, fail = _evaluate_backtest(
            engine_strategy=str(engine),
            holding_days=int(holding_days),
            config=config,
            parameters=parameters,
        )
        if fail and fail.startswith("INSUFFICIENT_DATA"):
            status = "INSUFFICIENT_DATA"
        elif fail and fail.startswith("INCONCLUSIVE"):
            status = "INCONCLUSIVE"
        elif fail:
            status = "INCONCLUSIVE"
        else:
            # Inspection-only candidate — still NOT production / NOT proven
            status = "CANDIDATE"

        trial = _base_trial(
            trial_id=trial_id,
            hyp=hyp,
            config=config,
            parameters=parameters,
            status=status,
            metrics=metrics,
            failure_reason=fail,
            holding_days=int(holding_days),
        )
        if status == "CANDIDATE":
            trial["selection_label"] = "candidate for further validation"
        registry.register(trial)

    result_status = "COMPLETED"
    if trial_limit_reached:
        result_status = "TRIAL_LIMIT_REACHED"

    return {
        "status": result_status,
        "horizon": config.horizon,
        "stage": "STAGE_1_HYPOTHESIS",
        "registry": registry.to_dict(),
        "inspection": registry.inspection_ranking(metric_key="sample_count"),
        "multiple_testing": registry.multiple_testing_summary(),
        "profitable_claim": False,
        "production_buy_emitted": False,
        "max_trials": config.max_trials,
        "trials_attempted": trials_attempted,
        "trial_limit_reached": trial_limit_reached,
        "cost_model": COST_MODEL_DEFAULT,
        "slippage_model": SLIPPAGE_MODEL_DEFAULT,
        "survivorship_status": SURVIVORSHIP_DEFAULT,
        "notes": [
            "Stage-1 discovery only — not profitability proof.",
            "Gross unadjusted Close returns are not net tradable returns.",
            "Survivorship NOT_VALIDATED.",
            "No production BUY wiring.",
        ],
        "engine_version": config.engine_version,
        "DATA_SCHEMA_VERSION": DATA_SCHEMA_VERSION,
        "calculated_at": datetime.now(UTC).isoformat(),
    }
