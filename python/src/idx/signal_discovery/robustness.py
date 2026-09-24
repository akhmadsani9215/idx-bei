"""Robustness sensitivity harness (Cluster 4).

Controlled one-at-a-time neighbour testing around a locked base configuration,
evaluated on IS or VALIDATION only (OOS stays locked). Every variant is kept;
nothing is selected. Labels follow ``ROBUSTNESS_CRITERIA`` — engineering
heuristics on gross (or configured-net) expectancy, not statistical tests.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any

from idx.signal_discovery.contract import HORIZON_HOLDING_BOUNDS
from idx.signal_discovery.costs import (
    COST_STATUS_ILLUSTRATIVE,
    CostModel,
    SlippageModel,
    net_trade_summary,
    return_semantics,
)
from idx.signal_discovery.validation import (
    FORBIDDEN_VALIDATION_STATUSES,
    ValidationConfig,
    ValidationWindow,
    evaluate_window_with_trades,
)

ROBUSTNESS_DIMENSIONS: tuple[str, ...] = (
    "parameter_sensitivity",
    "universe_sensitivity",
    "horizon_sensitivity",
    "time_sensitivity",
    "cost_sensitivity",
)
# Dimensions that re-run the engine and can contribute to ROBUST.
ENGINE_DIMENSIONS: tuple[str, ...] = ROBUSTNESS_DIMENSIONS[:4]

ROBUSTNESS_STATUSES: tuple[str, ...] = ("ROBUST", "FRAGILE", "INCONCLUSIVE", "INSUFFICIENT_DATA")
ALLOWED_ROBUSTNESS_PHASES: tuple[str, ...] = ("IS", "VALIDATION")

# Keys run_backtest actually consumes; varying anything else would be a no-op.
ENGINE_PARAMETER_KEYS: frozenset[str] = frozenset({"top_n", "stop_loss_pct", "take_profit_pct"})
UNIVERSE_PARAMETER_KEYS: frozenset[str] = frozenset({"min_turnover_rp"})

MIN_EVALUABLE_NEIGHBORS = 2
MAX_MEDIAN_DEGRADATION = 0.5
MIN_DIMENSIONS_FOR_ROBUST = 2

ROBUSTNESS_CRITERIA: dict[str, Any] = {
    "variation": "one-at-a-time neighbours around locked base; no grid search, no selection",
    "evaluable": "variant status OK (sample >= min_sample) and metric not null",
    "min_evaluable_neighbors": MIN_EVALUABLE_NEIGHBORS,
    "base_metric_must_be_positive": True,
    "sign_flip_is_fragile": True,
    "max_median_degradation": MAX_MEDIAN_DEGRADATION,
    "all_neighbors_evaluable_for_robust": True,
    "min_dimensions_for_overall_robust": MIN_DIMENSIONS_FOR_ROBUST,
    "cost_sensitivity_counts_toward_robust": False,
    "basis": "engineering heuristic — not a significance test; not profitability evidence",
}


class RobustnessConfigError(ValueError):
    """Invalid robustness plan."""


@dataclass
class RobustnessConfig:
    """Explicit neighbour plan around ``base`` (parameters stay locked elsewhere)."""

    base: ValidationConfig
    evaluation_phase: str
    max_variants: int
    parameter_neighbors: dict[str, list[Any]] = field(default_factory=dict)
    universe_neighbors: dict[str, list[Any]] = field(default_factory=dict)
    holding_days_neighbors: list[int] = field(default_factory=list)
    time_subwindows: list[ValidationWindow] = field(default_factory=list)
    cost_scenarios: list[tuple[CostModel, SlippageModel]] = field(default_factory=list)


def _phase_window(cfg: RobustnessConfig) -> ValidationWindow:
    if cfg.evaluation_phase not in ALLOWED_ROBUSTNESS_PHASES:
        raise RobustnessConfigError(
            f"evaluation_phase={cfg.evaluation_phase!r} not allowed — OOS must stay locked"
        )
    return cfg.base.discovery if cfg.evaluation_phase == "IS" else cfg.base.validation


def _check_neighbors(key: str, base_value: Any, values: list[Any]) -> None:
    if not values:
        raise RobustnessConfigError(f"{key}: neighbour list is empty")
    if len(set(map(repr, values))) != len(values):
        raise RobustnessConfigError(f"{key}: duplicate neighbour values")
    if base_value in values:
        raise RobustnessConfigError(f"{key}: neighbours must not include the base value")


def _plan_variants(cfg: RobustnessConfig, phase_window: ValidationWindow) -> list[dict[str, Any]]:
    base = cfg.base
    plan: list[dict[str, Any]] = []

    engine_keys = None if base.evaluate_fn is not None else ENGINE_PARAMETER_KEYS
    for dimension, grid, allowed in (
        ("parameter_sensitivity", cfg.parameter_neighbors, engine_keys),
        ("universe_sensitivity", cfg.universe_neighbors, UNIVERSE_PARAMETER_KEYS),
    ):
        for key, values in grid.items():
            if key not in base.parameters:
                raise RobustnessConfigError(f"{dimension}: {key!r} not in base parameters")
            if dimension == "parameter_sensitivity" and key in UNIVERSE_PARAMETER_KEYS:
                raise RobustnessConfigError(
                    f"{key!r} is a universe filter — use universe_neighbors"
                )
            if allowed is not None and key not in allowed:
                raise RobustnessConfigError(
                    f"{dimension}: {key!r} is not consumed by the engine (allowed: {sorted(allowed)})"
                )
            _check_neighbors(key, base.parameters[key], values)
            for value in values:
                plan.append(
                    {
                        "dimension": dimension,
                        "varied_key": key,
                        "value": value,
                        "config": replace(base, parameters={**base.parameters, key: value}),
                        "window": phase_window,
                    }
                )

    if cfg.holding_days_neighbors:
        lo, hi = HORIZON_HOLDING_BOUNDS.get(base.horizon, (None, None))
        if lo is None or hi is None:
            raise RobustnessConfigError(f"horizon {base.horizon} has no executable holding bounds")
        _check_neighbors("holding_days", base.holding_days, cfg.holding_days_neighbors)
        for h in cfg.holding_days_neighbors:
            if not isinstance(h, int) or not lo <= h <= hi:
                raise RobustnessConfigError(
                    f"holding_days={h!r} outside {base.horizon} bounds [{lo},{hi}] — would change horizon"
                )
            plan.append(
                {
                    "dimension": "horizon_sensitivity",
                    "varied_key": "holding_days",
                    "value": h,
                    "config": replace(base, holding_days=h),
                    "window": phase_window,
                }
            )

    if cfg.time_subwindows:
        if len(cfg.time_subwindows) < MIN_EVALUABLE_NEIGHBORS:
            raise RobustnessConfigError(
                f"time_subwindows needs >= {MIN_EVALUABLE_NEIGHBORS} windows"
            )
        p_start, p_end = (
            date.fromisoformat(phase_window.start),
            date.fromisoformat(phase_window.end),
        )
        prev_end: date | None = None
        for w in cfg.time_subwindows:
            s, e = date.fromisoformat(w.start), date.fromisoformat(w.end)
            if not p_start <= s <= e <= p_end:
                raise RobustnessConfigError(
                    f"time subwindow [{w.start},{w.end}] outside {cfg.evaluation_phase} window"
                )
            if prev_end is not None and s <= prev_end:
                raise RobustnessConfigError("time subwindows must be ordered and non-overlapping")
            prev_end = e
            plan.append(
                {
                    "dimension": "time_sensitivity",
                    "varied_key": "window",
                    "value": w.as_dict(),
                    "config": base,
                    "window": w,
                }
            )
    return plan


def _metric(result: dict[str, Any], *, net_basis: bool) -> float | None:
    if net_basis:
        value = (result.get("net_returns") or {}).get("net_expectancy_pct")
    else:
        metrics = result.get("metrics") or {}
        value = metrics.get("expectancy_pct")
        if value is None:
            value = metrics.get("avg_trade_return_pct")
    return None if value is None else float(value)


def _record(
    variant_id: str,
    item: dict[str, Any],
    result: dict[str, Any],
    *,
    net_basis: bool,
) -> dict[str, Any]:
    cfg: ValidationConfig = item["config"]
    return {
        "variant_id": variant_id,
        "dimension": item["dimension"],
        "varied_key": item["varied_key"],
        "value": item["value"],
        "parameters": dict(cfg.parameters),
        "holding_days": cfg.holding_days,
        "window": item["window"].as_dict(),
        "status": result.get("status"),
        "failure_reason": result.get("failure_reason"),
        "sample_count": result.get("sample_count"),
        "metric_value": _metric(result, net_basis=net_basis)
        if result.get("status") == "OK"
        else None,
        "metrics": result.get("metrics"),
        "net_returns": result.get("net_returns"),
    }


def classify_dimension(base: dict[str, Any], neighbors: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply ``ROBUSTNESS_CRITERIA`` to one dimension (base vs its neighbours)."""
    evaluable = [n for n in neighbors if n["status"] == "OK" and n["metric_value"] is not None]
    base_metric = base["metric_value"] if base["status"] == "OK" else None
    out: dict[str, Any] = {
        "status": "INSUFFICIENT_DATA",
        "reasons": [],
        "neighbor_count": len(neighbors),
        "evaluable_neighbor_count": len(evaluable),
        "base_metric": base_metric,
        "median_neighbor_metric": None,
        "median_degradation": None,
        "sign_flip_count": None,
    }
    if base_metric is None:
        out["reasons"].append("base variant not evaluable")
        return out
    if len(evaluable) < MIN_EVALUABLE_NEIGHBORS:
        out["reasons"].append(f"{len(evaluable)} evaluable neighbours < {MIN_EVALUABLE_NEIGHBORS}")
        return out

    median = statistics.median(n["metric_value"] for n in evaluable)
    flips = sum(1 for n in evaluable if n["metric_value"] <= 0)
    out["median_neighbor_metric"] = round(median, 4)
    out["sign_flip_count"] = flips

    if base_metric <= 0:
        out["status"] = "INCONCLUSIVE"
        out["reasons"].append(
            "base metric <= 0 — no positive effect whose stability can be assessed"
        )
        return out

    degradation = 1.0 - median / base_metric
    out["median_degradation"] = round(degradation, 4)
    if flips:
        out["reasons"].append(f"{flips} evaluable neighbour(s) flip sign (<= 0)")
    if degradation > MAX_MEDIAN_DEGRADATION:
        out["reasons"].append(
            f"median neighbour degrades {degradation:.0%} > {MAX_MEDIAN_DEGRADATION:.0%}"
        )
    if out["reasons"]:
        out["status"] = "FRAGILE"
    elif len(evaluable) < len(neighbors):
        out["status"] = "INCONCLUSIVE"
        out["reasons"].append(f"{len(neighbors) - len(evaluable)} neighbour(s) not evaluable")
    else:
        out["status"] = "ROBUST"
    return out


def _overall(dimensions: dict[str, dict[str, Any]]) -> tuple[str, list[str]]:
    executed = {d: v["status"] for d, v in dimensions.items() if d in ENGINE_DIMENSIONS}
    if not executed:
        return "INSUFFICIENT_DATA", ["no engine sensitivity dimension requested"]
    statuses = list(executed.values())
    if "FRAGILE" in statuses:
        return "FRAGILE", [d for d, s in executed.items() if s == "FRAGILE"]
    if all(s == "INSUFFICIENT_DATA" for s in statuses):
        return "INSUFFICIENT_DATA", list(executed)
    if all(s == "ROBUST" for s in statuses) and len(statuses) >= MIN_DIMENSIONS_FOR_ROBUST:
        return "ROBUST", list(executed)
    if all(s == "ROBUST" for s in statuses):
        return "INCONCLUSIVE", [f"only {len(statuses)} dimension(s) tested"]
    return "INCONCLUSIVE", [d for d, s in executed.items() if s != "ROBUST"]


def _cost_sensitivity(cfg: RobustnessConfig, ledger: Any) -> dict[str, Any]:
    if not cfg.cost_scenarios:
        return {"status": "NOT_CONFIGURED", "scenarios": []}
    if ledger is None:
        return {
            "status": "INSUFFICIENT_DATA",
            "reason": "base variant produced no trade ledger",
            "scenarios": [],
        }
    scenarios = [net_trade_summary(ledger, c, s) for c, s in cfg.cost_scenarios]
    illustrative = any(
        COST_STATUS_ILLUSTRATIVE in (c.status, s.status) for c, s in cfg.cost_scenarios
    )
    nets = [x["net_expectancy_pct"] for x in scenarios]
    return {
        "status": "RESEARCH_ILLUSTRATIVE" if illustrative else "EVALUATED",
        "scenarios": scenarios,
        "net_expectancy_positive_in_all": (
            all(v > 0 for v in nets) if nets and all(v is not None for v in nets) else None
        ),
        "counts_toward_robust": False,
    }


def run_robustness(cfg: RobustnessConfig) -> dict[str, Any]:
    """Execute the neighbour plan; retain every variant; never select or promote."""
    base_cfg = cfg.base
    semantics = return_semantics(base_cfg.cost_model, base_cfg.slippage_model)
    net_basis = bool(semantics["return_is_net_tradable"])
    header: dict[str, Any] = {
        "trial_id": base_cfg.trial_id,
        "strategy_id": base_cfg.strategy_id,
        "strategy_version": base_cfg.strategy_version,
        "horizon": base_cfg.horizon,
        "engine_version": base_cfg.engine_version,
        "evaluation_phase": cfg.evaluation_phase,
        "oos_used": False,
        "metric_basis": "NET_EXPECTANCY_PCT" if net_basis else "GROSS_EXPECTANCY_PCT",
        "criteria": ROBUSTNESS_CRITERIA,
        **semantics,
        "survivorship_status": base_cfg.survivorship_status,
        "profitable_claim": False,
        "production_buy_emitted": False,
    }

    try:
        if not isinstance(cfg.max_variants, int) or cfg.max_variants < 1:
            raise RobustnessConfigError("max_variants must be an int >= 1")
        phase_window = _phase_window(cfg)
        plan = _plan_variants(cfg, phase_window)
    except (RobustnessConfigError, ValueError) as exc:
        return {
            **header,
            "status": "REJECTED",
            "robustness_status": None,
            "failure_reason": str(exc),
        }

    variant_count = 1 + len(plan)
    header["evaluation_window"] = phase_window.as_dict()
    header["variant_count"] = variant_count
    if variant_count > cfg.max_variants:
        return {
            **header,
            "status": "TRIAL_LIMIT_REACHED",
            "robustness_status": None,
            "failure_reason": (
                f"planned variants={variant_count} > max_variants={cfg.max_variants}; "
                "nothing executed (no silent truncation)"
            ),
            "variants": [],
        }

    phase_label = f"ROBUSTNESS_{cfg.evaluation_phase}"
    base_item = {
        "dimension": "base",
        "varied_key": None,
        "value": None,
        "config": base_cfg,
        "window": phase_window,
    }
    base_result, base_ledger = evaluate_window_with_trades(
        base_cfg, phase_window, phase=phase_label
    )
    base_record = _record("v000_base", base_item, base_result, net_basis=net_basis)

    variants = [base_record]
    for i, item in enumerate(plan, start=1):
        result, _ = evaluate_window_with_trades(item["config"], item["window"], phase=phase_label)
        variants.append(_record(f"v{i:03d}", item, result, net_basis=net_basis))

    dimensions: dict[str, dict[str, Any]] = {}
    for dim in ENGINE_DIMENSIONS:
        neighbors = [v for v in variants[1:] if v["dimension"] == dim]
        if neighbors:
            dimensions[dim] = classify_dimension(base_record, neighbors)

    if base_cfg.dry_run:
        status, robustness_status, reasons = "DRY_RUN", "INCONCLUSIVE", ["dry run — no evidence"]
    else:
        status = "COMPLETED"
        robustness_status, reasons = _overall(dimensions)
    if robustness_status in FORBIDDEN_VALIDATION_STATUSES:
        robustness_status = "INCONCLUSIVE"

    cost = _cost_sensitivity(cfg, base_ledger)
    return {
        **header,
        "status": status,
        "robustness_status": robustness_status,
        "robustness_reasons": reasons,
        "failure_reason": None,
        "base": base_record,
        "dimensions": dimensions,
        "cost_sensitivity": cost,
        "variants": variants,
        "engine_runs": variant_count,
        "multiple_testing": {
            "robustness_variants_evaluated": variant_count,
            "cost_scenarios_evaluated": len(cost["scenarios"]),
            "statistical_significance_claimed": False,
        },
        "notes": [
            "All variants retained; none selected as best.",
            "ROBUST describes neighbour stability on the evaluation phase only — not edge or profitability.",
            f"Metric basis {header['metric_basis']}; survivorship {base_cfg.survivorship_status}.",
        ],
    }
