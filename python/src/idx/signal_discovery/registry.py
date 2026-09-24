"""Trial registry for Signal Discovery Lab (Cluster 2).

Records every hypothesis evaluation. Never emits PRODUCTION / PRODUCTION_CANDIDATE.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from idx.signal_discovery.contract import ENGINE_VERSION, is_valid_horizon

# Statuses the runner/registry may emit (subset of candidate statuses).
RUNNER_STATUSES: frozenset[str] = frozenset(
    {
        "DISCOVERED",
        "BACKTESTING",
        "VALIDATION",
        "OOS_TESTING",
        "INCONCLUSIVE",
        "CANDIDATE",
        "REJECTED",
        "INSUFFICIENT_DATA",
        "TRIAL_LIMIT_REACHED",  # run-level / failure_reason marker also allowed as status
    }
)

FORBIDDEN_RUNNER_STATUSES: frozenset[str] = frozenset(
    {"PRODUCTION_CANDIDATE", "PRODUCTION", "PROFITABLE", "BEST", "WINNER", "PROVEN"}
)

TRIAL_REQUIRED_FIELDS: tuple[str, ...] = (
    "trial_id",
    "strategy_id",
    "strategy_version",
    "horizon",
    "hypothesis",
    "feature_set",
    "parameters",
    "universe_definition",
    "discovery_period",
    "validation_period",
    "oos_period",
    "cost_model",
    "slippage_model",
    "engine_version",
    "data_version",
    "data_quality",
    "created_at",
    "status",
    "metrics",
    "failure_reason",
)

COST_MODEL_DEFAULT = "NOT_CONFIGURED"
SLIPPAGE_MODEL_DEFAULT = "NOT_CONFIGURED"
SURVIVORSHIP_DEFAULT = "NOT_VALIDATED"


class TrialRegistryError(ValueError):
    """Invalid trial registration."""


def _param_fingerprint(owner: Any, parameters: Any, holding_days: Any) -> str:
    params = dict(parameters) if isinstance(parameters, dict) else {}
    # Runner stores holding_days inside parameters; validation keeps it separate.
    embedded = params.pop("holding_days", None)
    holding = holding_days if holding_days is not None else embedded
    items = ",".join(f"{k}={params[k]!r}" for k in sorted(params))
    return f"{owner}|{items}|h={holding!r}"


def empty_metrics_record() -> dict[str, Any]:
    """Honest metric shell — missing values are null, never fake tradable zeros."""
    keys = (
        "sample_count",
        "win_rate_pct",
        "total_return_pct",
        "avg_trade_return_pct",
        "mfe",
        "mae",
        "holding_period",
        "max_drawdown_pct",
        "sharpe_ratio",
        "sortino_ratio",
        "tp_hit_rate_pct",
        "cl_hit_rate_pct",
        "expectancy_pct",
        "profit_factor",
    )
    out: dict[str, Any] = {k: None for k in keys}
    out["return_basis"] = "GROSS_UNADJUSTED_CLOSE — not net tradable return"
    out["metrics_status"] = "NOT_AVAILABLE"
    return out


def normalize_engine_metrics(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Map ``run_backtest`` metrics → registry metrics; unavailable stay null.

    When ``total_trades`` is 0, performance figures from the empty-engine defaults
    are treated as NOT_AVAILABLE (null), not as proven zero performance.
    """
    out = empty_metrics_record()
    if not raw:
        return out

    sample = raw.get("total_trades")
    if sample is None:
        sample = raw.get("sample")
    try:
        sample_n = int(sample) if sample is not None else 0
    except (TypeError, ValueError):
        sample_n = 0

    out["sample_count"] = sample_n
    out["holding_period"] = raw.get("holding_days")
    out["median_holding_sessions"] = raw.get("median_holding_sessions")

    if sample_n <= 0:
        out["metrics_status"] = "NOT_AVAILABLE"
        # Explicitly null unavailable outcome metrics (do not copy empty-engine 0.0).
        for k in (
            "win_rate_pct",
            "total_return_pct",
            "avg_trade_return_pct",
            "max_drawdown_pct",
            "sharpe_ratio",
            "sortino_ratio",
            "profit_factor",
            "expectancy_pct",
            "mfe",
            "mae",
            "tp_hit_rate_pct",
            "cl_hit_rate_pct",
        ):
            out[k] = None
            out[f"{k}_status"] = "NOT_AVAILABLE"
        return out

    mapping = {
        "win_rate_pct": "win_rate_pct",
        "total_return_pct": "total_return_pct",
        "avg_trade_return_pct": "avg_trade_return_pct",
        "max_drawdown_pct": "max_drawdown_pct",
        "sharpe_ratio": "sharpe_ratio",
        "sortino_ratio": "sortino_ratio",
        "profit_factor": "profit_factor",
    }
    for dst, src in mapping.items():
        if src in raw and raw[src] is not None:
            out[dst] = raw[src]

    # Never available from production run_backtest today:
    for k in ("mfe", "mae", "tp_hit_rate_pct", "cl_hit_rate_pct", "expectancy_pct"):
        val = raw.get(k)
        if val is None:
            val = raw.get(f"median_{k}") if k in ("mfe", "mae") else None
        if val is None and k == "mfe":
            val = raw.get("median_mfe_pct")
        if val is None and k == "mae":
            val = raw.get("median_mae_pct")
        if val is None:
            out[k] = None
            out[f"{k}_status"] = "NOT_AVAILABLE"
        else:
            out[k] = val

    out["metrics_status"] = "PARTIAL"
    out["return_basis"] = "GROSS_UNADJUSTED_CLOSE — not net tradable return"
    return out


def validate_trial_record(trial: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in TRIAL_REQUIRED_FIELDS:
        if field not in trial:
            errors.append(f"missing field: {field}")
    status = trial.get("status")
    if status in FORBIDDEN_RUNNER_STATUSES:
        errors.append(f"forbidden status for discovery runner: {status}")
    if status is not None and status not in RUNNER_STATUSES:
        errors.append(f"invalid runner status: {status}")
    horizon = trial.get("horizon")
    if horizon is not None and not is_valid_horizon(str(horizon)):
        errors.append(f"invalid horizon: {horizon}")
    if trial.get("cost_model") not in (None, COST_MODEL_DEFAULT, "UNAVAILABLE", "NOT_CONFIGURED"):
        # Allow explicit named models later; Cluster 2 expects honesty marker.
        pass
    return errors


class TrialRegistry:
    """In-memory trial registry (Cluster 2). Persist later without changing schema."""

    def __init__(self) -> None:
        self._trials: dict[str, dict[str, Any]] = {}
        self._order: list[str] = []
        self._robustness_runs: list[dict[str, Any]] = []
        self.run_notes: list[str] = []

    def __len__(self) -> int:
        return len(self._trials)

    def register(self, trial: dict[str, Any]) -> dict[str, Any]:
        errors = validate_trial_record(trial)
        if errors:
            raise TrialRegistryError("; ".join(errors))
        if trial.get("status") in FORBIDDEN_RUNNER_STATUSES:
            raise TrialRegistryError(f"Discovery runner cannot emit status={trial.get('status')}")
        tid = str(trial["trial_id"])
        if tid in self._trials:
            raise TrialRegistryError(f"duplicate trial_id: {tid}")
        stored = deepcopy(trial)
        if "survivorship_status" not in stored:
            stored["survivorship_status"] = SURVIVORSHIP_DEFAULT
        if "selection_label" not in stored:
            stored["selection_label"] = None
        if "profitable_claim" not in stored:
            stored["profitable_claim"] = False
        if "hypothesis_family" not in stored:
            stored["hypothesis_family"] = None
        if "parameter_count" not in stored:
            params = stored.get("parameters") or {}
            stored["parameter_count"] = len(params) if isinstance(params, dict) else 0
        if "random_seed" not in stored:
            stored["random_seed"] = None
        self._trials[tid] = stored
        self._order.append(tid)
        return deepcopy(stored)

    def get(self, trial_id: str) -> dict[str, Any] | None:
        t = self._trials.get(trial_id)
        return deepcopy(t) if t else None

    def all_trials(self) -> list[dict[str, Any]]:
        return [deepcopy(self._trials[i]) for i in self._order]

    def trial_ids(self) -> list[str]:
        return list(self._order)

    def number_of_trials(self) -> int:
        return len(self._trials)

    def record_robustness_run(self, result: dict[str, Any]) -> dict[str, Any]:
        """Count a ``run_robustness`` result toward the multiple-testing budget."""
        trial_id = result.get("trial_id")
        if trial_id not in self._trials:
            raise TrialRegistryError(f"robustness run for unknown trial_id: {trial_id}")
        variants = result.get("variants") or []
        summary = {
            "trial_id": trial_id,
            "status": result.get("status"),
            "robustness_status": result.get("robustness_status"),
            "evaluation_phase": result.get("evaluation_phase"),
            "variant_count": len(variants),
            "parameter_sets": sorted(
                {
                    _param_fingerprint(
                        result.get("strategy_id"), v.get("parameters"), v.get("holding_days")
                    )
                    for v in variants
                }
            ),
        }
        self._robustness_runs.append(summary)
        return deepcopy(summary)

    def multiple_testing_summary(self) -> dict[str, Any]:
        trials = self.all_trials()
        families = sorted(
            {str(t["hypothesis_family"]) for t in trials if t.get("hypothesis_family")}
        )
        by_family: dict[str, int] = {}
        by_horizon: dict[str, int] = {}
        param_sets: set[str] = set()
        for t in trials:
            fam = str(t.get("hypothesis_family") or "UNSPECIFIED")
            by_family[fam] = by_family.get(fam, 0) + 1
            hz = str(t.get("horizon") or "UNSPECIFIED")
            by_horizon[hz] = by_horizon.get(hz, 0) + 1
            param_sets.add(
                _param_fingerprint(t.get("strategy_id"), t.get("parameters"), t.get("holding_days"))
            )
        robustness_variants = sum(r["variant_count"] for r in self._robustness_runs)
        for r in self._robustness_runs:
            param_sets.update(r["parameter_sets"])
        return {
            "number_of_trials": len(trials),
            "total_trials": len(trials),
            "trials_by_family": dict(sorted(by_family.items())),
            "trials_by_horizon": dict(sorted(by_horizon.items())),
            "hypothesis_families": families,
            "parameter_count_total": sum(int(t.get("parameter_count") or 0) for t in trials),
            "parameter_variants": len(param_sets),
            "robustness_runs": len(self._robustness_runs),
            "robustness_variants_total": robustness_variants,
            "evaluations_upper_bound": len(trials) + robustness_variants,
            "selection_method": "inspection_sort_only — not production winner",
            "adjustment_status": "NOT_APPLIED",
            "deflated_sharpe": None,
            "deflated_sharpe_status": "NOT_IMPLEMENTED",
            "false_discovery_control": "NOT_IMPLEMENTED",
            "statistical_significance_claimed": False,
            "notes": (
                "Multiple hypotheses tested; do not treat top inspection rank "
                "as proven edge or production winner. evaluations_upper_bound counts "
                "correlated evaluations, not independent tests."
            ),
        }

    def inspection_ranking(
        self,
        *,
        metric_key: str = "sample_count",
    ) -> list[dict[str, Any]]:
        """Sort for human inspection only — never BEST/WINNER/PROFITABLE."""
        ranked: list[dict[str, Any]] = []
        for t in self.all_trials():
            if t.get("status") in ("INSUFFICIENT_DATA", "TRIAL_LIMIT_REACHED", "REJECTED"):
                continue
            metrics = t.get("metrics") or {}
            score = metrics.get(metric_key)
            item = deepcopy(t)
            item["inspection_metric"] = metric_key
            item["inspection_score"] = score
            item["selection_label"] = "candidate for further validation"
            ranked.append(item)

        def _key(row: dict[str, Any]) -> tuple[int, float]:
            s = row.get("inspection_score")
            if s is None:
                return (1, 0.0)
            try:
                return (0, -float(s))
            except (TypeError, ValueError):
                return (1, 0.0)

        ranked.sort(key=_key)
        return ranked

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine_version": ENGINE_VERSION,
            "created_at": datetime.now(UTC).isoformat(),
            "trials": self.all_trials(),
            "multiple_testing": self.multiple_testing_summary(),
            "run_notes": list(self.run_notes),
            "profitable_claim": False,
            "production_buy_emitted": False,
        }
