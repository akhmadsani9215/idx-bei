"""OOS + walk-forward validation harness (Cluster 3; cost/survivorship lineage Cluster 4).

Temporal splits only — no random shuffle. Parameters locked from IS/TRAIN;
OOS and walk-forward test folds never retune parameters.

Does not emit PRODUCTION / PRODUCTION_BUY / profitability claims.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from idx.schema_version import DATA_SCHEMA_VERSION
from idx.screener.contract import MIN_HISTORICAL_SAMPLE
from idx.signal_discovery.contract import (
    ENGINE_VERSION,
    assert_no_future_feature,
    assert_signal_as_of_ordering,
    is_valid_horizon,
)
from idx.signal_discovery.costs import (
    NOT_CONFIGURED_COST_MODEL,
    NOT_CONFIGURED_SLIPPAGE_MODEL,
    CostModel,
    SlippageModel,
    net_trade_summary,
    return_semantics,
)
from idx.signal_discovery.hypotheses import FEATURE_VERSION
from idx.signal_discovery.metrics_adapter import adapt_backtest_metrics, mark_unavailable_shell
from idx.signal_discovery.registry import SURVIVORSHIP_DEFAULT

PhaseName = Literal["IS", "VALIDATION", "OOS", "WALK_FORWARD"]

VALIDATION_PHASES: tuple[str, ...] = ("IS", "VALIDATION", "OOS", "WALK_FORWARD")

# Engineering sample gate (aligned with screener historical sample policy — not scientific truth).
DEFAULT_MIN_SAMPLE = MIN_HISTORICAL_SAMPLE

FORBIDDEN_VALIDATION_STATUSES: frozenset[str] = frozenset(
    {
        "PRODUCTION",
        "PRODUCTION_BUY",
        "PRODUCTION_CANDIDATE",
        "BEST",
        "WINNER",
        "PROVEN",
        "PROFITABLE",
    }
)

# Cluster 3 may only promote research validation — never production wiring.
RESEARCH_ELIGIBLE_STATUS = "VALIDATED_FOR_RESEARCH"

ELIGIBILITY_BASIS = (
    "DATA_SUFFICIENCY_AND_TEMPORAL_INTEGRITY — every required phase met min_sample without "
    "leakage/coverage failure. No performance threshold is applied; this is not evidence of edge."
)


class ValidationConfigError(ValueError):
    """Invalid temporal split or validation configuration."""


@dataclass(frozen=True)
class ValidationWindow:
    """Inclusive calendar date window [start, end] as YYYY-MM-DD strings."""

    start: str
    end: str

    def as_dict(self) -> dict[str, str]:
        return {"start": self.start, "end": self.end}


@dataclass
class WalkForwardConfig:
    """Expanding-window walk-forward (temporal only).

    Fold k:
      train = [train_start, train_end_k]
      test  = (train_end_k, test_end_k]  — unseen relative to that train end
    Train end expands by ``step_calendar_days`` each fold; parameters stay locked.
    """

    train_start: str
    first_train_end: str
    test_span_calendar_days: int
    step_calendar_days: int
    n_folds: int
    parameter_version: str = "locked-v1"

    def __post_init__(self) -> None:
        if self.n_folds < 1:
            raise ValidationConfigError("n_folds must be >= 1")
        if self.test_span_calendar_days < 1 or self.step_calendar_days < 1:
            raise ValidationConfigError("test_span and step must be >= 1 calendar days")


@dataclass
class ValidationConfig:
    """Explicit temporal validation plan — no current-date defaults."""

    trial_id: str
    strategy_id: str
    strategy_version: str
    horizon: str
    engine_strategy: str
    parameters: dict[str, Any]
    holding_days: int
    discovery: ValidationWindow  # IS
    validation: ValidationWindow
    oos: ValidationWindow
    universe_definition: str
    min_sample: int = DEFAULT_MIN_SAMPLE
    feature_version: str = FEATURE_VERSION
    data_version: str = DATA_SCHEMA_VERSION
    engine_version: str = ENGINE_VERSION
    # Declared available data span — do not silently shrink requested windows
    data_available_start: str | None = None
    data_available_end: str | None = None
    walk_forward: WalkForwardConfig | None = None
    # Locked parameters for all phases (selection only from IS / TRAIN)
    parameter_selection_phase: str = "IS"
    dry_run: bool = False
    stock_df: Any = None
    ratios_df: Any = None
    actions_df: Any = None
    # Optional injectable evaluator for tests: (strategy, holding, start, end, params) -> (raw_metrics, trades_df)
    evaluate_fn: Callable[..., tuple[dict[str, Any] | None, Any]] | None = None
    cost_model: CostModel = NOT_CONFIGURED_COST_MODEL
    slippage_model: SlippageModel = NOT_CONFIGURED_SLIPPAGE_MODEL
    # Output of survivorship.evaluate_survivorship_policy / audit_survivorship_evidence
    survivorship_assessment: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def survivorship_status(self) -> str:
        if self.survivorship_assessment is None:
            return SURVIVORSHIP_DEFAULT
        return str(self.survivorship_assessment.get("survivorship_status") or SURVIVORSHIP_DEFAULT)


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError as exc:
        raise ValidationConfigError(f"Invalid date: {value!r}") from exc


def _window_ok(window: ValidationWindow, *, label: str) -> None:
    s = _parse_date(window.start)
    e = _parse_date(window.end)
    if s > e:
        raise ValidationConfigError(f"{label}: start ({window.start}) > end ({window.end})")


def validate_temporal_split(
    discovery: ValidationWindow,
    validation: ValidationWindow,
    oos: ValidationWindow,
) -> None:
    """Reject overlaps and non-chronological ordering. No shuffle."""
    _window_ok(discovery, label="discovery")
    _window_ok(validation, label="validation")
    _window_ok(oos, label="oos")

    d_end = _parse_date(discovery.end)
    v_start = _parse_date(validation.start)
    v_end = _parse_date(validation.end)
    o_start = _parse_date(oos.start)

    if d_end >= v_start:
        raise ValidationConfigError(
            f"discovery/validation overlap or non-chronological: "
            f"discovery.end={discovery.end} >= validation.start={validation.start}"
        )
    if v_end >= o_start:
        raise ValidationConfigError(
            f"validation/oos overlap or non-chronological: "
            f"validation.end={validation.end} >= oos.start={oos.start}"
        )


def check_data_coverage(
    window: ValidationWindow,
    *,
    data_available_start: str | None,
    data_available_end: str | None,
) -> dict[str, Any]:
    """Return coverage verdict without silently shrinking the requested window."""
    requested = window.as_dict()
    if data_available_start is None or data_available_end is None:
        return {
            "ok": True,
            "requested_range": requested,
            "actual_used_range": requested,
            "coverage_status": "UNDECLARED_AVAILABILITY — assumed caller guarantees coverage",
            "failure_reason": None,
        }

    avail_s = _parse_date(data_available_start)
    avail_e = _parse_date(data_available_end)
    req_s = _parse_date(window.start)
    req_e = _parse_date(window.end)

    if req_s < avail_s or req_e > avail_e:
        return {
            "ok": False,
            "requested_range": requested,
            "actual_used_range": None,
            "coverage_status": "INSUFFICIENT_DATA",
            "failure_reason": (
                f"Requested [{window.start},{window.end}] outside available "
                f"[{data_available_start},{data_available_end}] — "
                f"refusing silent shrink"
            ),
        }
    return {
        "ok": True,
        "requested_range": requested,
        "actual_used_range": requested,
        "coverage_status": "FULL",
        "failure_reason": None,
    }


def build_walk_forward_folds(cfg: WalkForwardConfig) -> list[dict[str, Any]]:
    """Generate expanding-window folds (temporal order)."""
    train_start = _parse_date(cfg.train_start)
    train_end = _parse_date(cfg.first_train_end)
    if train_start > train_end:
        raise ValidationConfigError("walk-forward train_start > first_train_end")

    folds: list[dict[str, Any]] = []
    for i in range(cfg.n_folds):
        test_start = train_end + timedelta(days=1)
        test_end = train_end + timedelta(days=cfg.test_span_calendar_days)
        if test_start > test_end:
            raise ValidationConfigError(f"fold {i}: empty test window")
        folds.append(
            {
                "fold_id": f"wf_{i:03d}",
                "train_start": train_start.isoformat(),
                "train_end": train_end.isoformat(),
                "test_start": test_start.isoformat(),
                "test_end": test_end.isoformat(),
                "parameter_version": cfg.parameter_version,
            }
        )
        # Expand train to include prior test; step forward
        train_end = train_end + timedelta(days=cfg.step_calendar_days)
    return folds


def assert_fold_temporal_integrity(folds: list[dict[str, Any]]) -> None:
    """Each fold: train_end < test_start; folds ordered; test unseen vs that train."""
    prev_test_end: date | None = None
    for fold in folds:
        tr_s = _parse_date(fold["train_start"])
        tr_e = _parse_date(fold["train_end"])
        te_s = _parse_date(fold["test_start"])
        te_e = _parse_date(fold["test_end"])
        if not (tr_s <= tr_e < te_s <= te_e):
            raise ValidationConfigError(
                f"fold {fold.get('fold_id')} not strictly temporal: "
                f"train=[{fold['train_start']},{fold['train_end']}] "
                f"test=[{fold['test_start']},{fold['test_end']}]"
            )
        if prev_test_end is not None and tr_e < prev_test_end:
            # Expanding window must not shrink train end
            raise ValidationConfigError(
                f"fold {fold.get('fold_id')} train_end shrinks vs prior test coverage"
            )
        prev_test_end = te_e


def _lineage(config: ValidationConfig, phase: str) -> dict[str, Any]:
    return {
        "trial_id": config.trial_id,
        "strategy_id": config.strategy_id,
        "strategy_version": config.strategy_version,
        "data_version": config.data_version,
        "feature_version": config.feature_version,
        "universe_definition": config.universe_definition,
        "horizon": config.horizon,
        "engine_version": config.engine_version,
        "engine_strategy": config.engine_strategy,
        "phase": phase,
        "parameter_selection_phase": config.parameter_selection_phase,
        "parameters_locked": deepcopy(config.parameters),
        **return_semantics(config.cost_model, config.slippage_model),
        "survivorship_status": config.survivorship_status,
        "profitable_claim": False,
        "shuffle_used": False,
    }


def _run_engine(
    config: ValidationConfig, window: ValidationWindow
) -> tuple[dict[str, Any] | None, Any]:
    """Single execution path: injected evaluator (tests) or ``run_backtest``."""
    if config.evaluate_fn is not None:
        return config.evaluate_fn(
            config.engine_strategy,
            config.holding_days,
            window.start,
            window.end,
            dict(config.parameters),
        )

    from idx.backtest import run_backtest

    kwargs: dict[str, Any] = {
        "strategy": config.engine_strategy,
        "holding_days": config.holding_days,
        "top_n": int(config.parameters.get("top_n", 10)),
        "min_turnover_rp": float(config.parameters.get("min_turnover_rp", 1e9)),
        "start_date": window.start,
        "end_date": window.end,
    }
    for rule in ("stop_loss_pct", "take_profit_pct"):
        if config.parameters.get(rule) is not None:
            kwargs[rule] = float(config.parameters[rule])
    if config.stock_df is not None:
        kwargs["stock_df"] = config.stock_df
    if config.ratios_df is not None:
        kwargs["ratios_df"] = config.ratios_df
    if config.actions_df is not None:
        kwargs["actions_df"] = config.actions_df
    return run_backtest(**kwargs)


def _evaluate_window(
    config: ValidationConfig,
    window: ValidationWindow,
    *,
    phase: str,
) -> dict[str, Any]:
    """Run one temporal window through existing engine (or dry_run / inject)."""
    return evaluate_window_with_trades(config, window, phase=phase)[0]


def evaluate_window_with_trades(
    config: ValidationConfig,
    window: ValidationWindow,
    *,
    phase: str,
) -> tuple[dict[str, Any], Any]:
    """Like ``_evaluate_window`` but also returns the engine trade ledger (or ``None``)."""
    coverage = check_data_coverage(
        window,
        data_available_start=config.data_available_start,
        data_available_end=config.data_available_end,
    )
    base = {
        **_lineage(config, phase),
        "requested_range": coverage["requested_range"],
        "actual_used_range": coverage["actual_used_range"],
        "coverage_status": coverage["coverage_status"],
        "holding_days": config.holding_days,
        "min_sample": config.min_sample,
        "min_sample_policy": (
            f"engineering_gate min_sample={config.min_sample} "
            f"(aligned with screener MIN_HISTORICAL_SAMPLE={MIN_HISTORICAL_SAMPLE}; "
            f"not a scientific profitability threshold)"
        ),
    }

    # Leakage: features/data_as_of for this phase must not exceed window end;
    # phase must not see beyond its end (caller enforces split).
    signal_ts = window.end
    data_as_of = window.end
    try:
        assert_signal_as_of_ordering(signal_ts, data_as_of)
        assert_no_future_feature(data_as_of, signal_ts, feature_name=f"{phase}_feature_as_of")
    except Exception as exc:  # noqa: BLE001
        return {
            **base,
            "status": "REJECTED",
            "failure_reason": f"leakage_invariant: {exc}",
            "metrics": mark_unavailable_shell(),
            "sample_count": 0,
            "gate": f"{phase}_FAIL",
        }, None

    if not coverage["ok"]:
        return {
            **base,
            "status": "INSUFFICIENT_DATA",
            "failure_reason": coverage["failure_reason"],
            "metrics": mark_unavailable_shell(),
            "sample_count": 0,
            "gate": f"{phase}_INSUFFICIENT_DATA",
        }, None

    if config.dry_run:
        # Deterministic dry-run shell — no fabricated performance
        metrics = mark_unavailable_shell()
        metrics["sample_count"] = None
        metrics["metrics_status"] = "DRY_RUN"
        return {
            **base,
            "status": "DRY_RUN",
            "failure_reason": None,
            "metrics": metrics,
            "sample_count": None,
            "gate": f"{phase}_DRY_RUN",
            "signal_timestamp": signal_ts,
            "data_as_of": data_as_of,
        }, None

    raw, trades = _run_engine(config, window)
    ledger = trades if hasattr(trades, "columns") else None
    metrics = adapt_backtest_metrics(
        raw if isinstance(raw, dict) else None,
        trades_df=ledger,
        holding_days=config.holding_days,
    )
    sample = int(metrics.get("sample_count") or 0)
    net_returns = net_trade_summary(ledger, config.cost_model, config.slippage_model)

    if sample < config.min_sample:
        return {
            **base,
            "status": "INSUFFICIENT_DATA",
            "failure_reason": (
                f"sample_count={sample} < min_sample={config.min_sample} (engineering gate)"
            ),
            "metrics": metrics,
            "net_returns": net_returns,
            "sample_count": sample,
            "gate": f"{phase}_INSUFFICIENT_DATA",
            "signal_timestamp": signal_ts,
            "data_as_of": data_as_of,
        }, ledger

    return {
        **base,
        "status": "OK",
        "failure_reason": None,
        "metrics": metrics,
        "net_returns": net_returns,
        "sample_count": sample,
        "gate": f"{phase}_SUCCESS",
        "signal_timestamp": signal_ts,
        "data_as_of": data_as_of,
    }, ledger


def _phase_sees_forbidden(
    phase: str,
    *,
    discovery: ValidationWindow,
    validation: ValidationWindow,
    oos: ValidationWindow,
    used_end: str,
) -> str | None:
    """Guard: earlier phases must not use later windows' dates."""
    used = _parse_date(used_end)
    if phase == "IS" and used > _parse_date(discovery.end):
        return "IS window must not extend into validation/OOS"
    if phase == "VALIDATION" and used > _parse_date(validation.end):
        return "VALIDATION window must not extend into OOS"
    if phase == "VALIDATION" and used <= _parse_date(discovery.end):
        # validation start already > discovery end via split; used_end within validation is fine
        pass
    if phase == "OOS" and used < _parse_date(oos.start):
        return "OOS actual range inconsistent"
    return None


def run_walk_forward(config: ValidationConfig) -> dict[str, Any]:
    """Execute expanding-window walk-forward with locked parameters."""
    if config.walk_forward is None:
        return {
            "status": "SKIPPED",
            "failure_reason": "walk_forward config not provided",
            "folds": [],
            "aggregate": None,
        }

    wf = config.walk_forward
    try:
        folds_spec = build_walk_forward_folds(wf)
        assert_fold_temporal_integrity(folds_spec)
    except ValidationConfigError as exc:
        return {
            "status": "REJECTED",
            "failure_reason": str(exc),
            "folds": [],
            "aggregate": None,
        }

    fold_results: list[dict[str, Any]] = []
    for spec in folds_spec:
        test_window = ValidationWindow(start=spec["test_start"], end=spec["test_end"])
        # Coverage check on test window
        coverage = check_data_coverage(
            test_window,
            data_available_start=config.data_available_start,
            data_available_end=config.data_available_end,
        )
        if not coverage["ok"]:
            fold_results.append(
                {
                    **spec,
                    "status": "INSUFFICIENT_DATA",
                    "failure_reason": coverage["failure_reason"],
                    "requested_range": coverage["requested_range"],
                    "actual_used_range": None,
                    "metrics": mark_unavailable_shell(),
                    "sample_count": 0,
                    "parameter_version": wf.parameter_version,
                    "parameters_locked": deepcopy(config.parameters),
                    "oos_parameter_retune_forbidden": True,
                }
            )
            continue

        if config.dry_run:
            fold_results.append(
                {
                    **spec,
                    "status": "DRY_RUN",
                    "failure_reason": None,
                    "requested_range": coverage["requested_range"],
                    "actual_used_range": coverage["actual_used_range"],
                    "metrics": mark_unavailable_shell(),
                    "sample_count": None,
                    "parameter_version": wf.parameter_version,
                    "parameters_locked": deepcopy(config.parameters),
                    "oos_parameter_retune_forbidden": True,
                }
            )
            continue

        # Evaluate TEST only with locked params (train used for selection elsewhere)
        phase_cfg_window = test_window
        result = _evaluate_window(config, phase_cfg_window, phase="WALK_FORWARD")
        fold_results.append(
            {
                **spec,
                "status": result["status"],
                "failure_reason": result.get("failure_reason"),
                "requested_range": result.get("requested_range"),
                "actual_used_range": result.get("actual_used_range"),
                "metrics": result.get("metrics"),
                "sample_count": result.get("sample_count"),
                "gate": result.get("gate"),
                "parameter_version": wf.parameter_version,
                "parameters_locked": deepcopy(config.parameters),
                "oos_parameter_retune_forbidden": True,
            }
        )

    aggregate = aggregate_walk_forward(fold_results)
    success_n = aggregate["fold_success_count"]
    status = "OK" if success_n > 0 and aggregate["fold_failure_count"] == 0 else "PARTIAL"
    if all(f.get("status") == "INSUFFICIENT_DATA" for f in fold_results):
        status = "INSUFFICIENT_DATA"
    if config.dry_run:
        status = "DRY_RUN"

    return {
        "status": status,
        "parameter_version": wf.parameter_version,
        "parameters_locked": deepcopy(config.parameters),
        "folds": fold_results,
        "aggregate": aggregate,
        "notes": [
            "Walk-forward test folds use locked parameters selected from IS/TRAIN only.",
            "Do not retune on OOS/test then re-pick best OOS.",
            "Aggregate does not hide per-fold dispersion — see folds[].",
        ],
    }


def aggregate_walk_forward(folds: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate fold metrics without hiding failures or dispersion."""
    import statistics

    def _vals(key: str) -> list[float]:
        out: list[float] = []
        for f in folds:
            m = f.get("metrics") or {}
            v = m.get(key)
            if v is None:
                continue
            try:
                out.append(float(v))
            except (TypeError, ValueError):
                continue
        return out

    success = [f for f in folds if f.get("status") == "OK"]
    failure = [f for f in folds if f.get("status") not in ("OK", "DRY_RUN")]
    samples = []
    for f in folds:
        sc = f.get("sample_count")
        if sc is not None:
            try:
                samples.append(int(sc))
            except (TypeError, ValueError):
                pass

    def _med(xs: list[float]) -> float | None:
        return round(statistics.median(xs), 4) if xs else None

    def _mean(xs: list[float]) -> float | None:
        return round(statistics.fmean(xs), 4) if xs else None

    rets = _vals("total_return_pct")
    mfes = _vals("mfe")
    maes = _vals("mae")
    wins = _vals("win_rate_pct")
    dds = _vals("max_drawdown_pct")

    return {
        "fold_count": len(folds),
        "total_samples": sum(samples) if samples else 0,
        "median_return": _med(rets),
        "mean_return": _mean(rets),
        "median_MFE": _med(mfes),
        "median_MAE": _med(maes),
        "win_rate": _med(wins),
        "drawdown": _med(dds),
        "fold_success_count": len(success),
        "fold_failure_count": len(failure),
        "dispersion_note": "Per-fold metrics retained in folds[]; aggregate is descriptive only",
    }


def evaluate_research_eligibility(
    *,
    is_result: dict[str, Any],
    validation_result: dict[str, Any],
    oos_result: dict[str, Any],
    walk_forward_result: dict[str, Any] | None,
    require_walk_forward: bool = False,
) -> dict[str, Any]:
    """Research gate: VALIDATED_FOR_RESEARCH only — never PRODUCTION*.

    Walk-forward passes only when every fold is OK; one good fold is not enough.
    """
    wf_aggregate = (walk_forward_result or {}).get("aggregate") or {}
    gates = {
        "IS_SUCCESS": is_result.get("status") == "OK",
        "VALIDATION_SUCCESS": validation_result.get("status") == "OK",
        "OOS_SUCCESS": oos_result.get("status") == "OK",
        "WALK_FORWARD_SUCCESS": bool(
            walk_forward_result.get("status") == "OK"
            and wf_aggregate.get("fold_count", 0) > 0
            and wf_aggregate.get("fold_success_count") == wf_aggregate.get("fold_count")
        )
        if walk_forward_result and walk_forward_result.get("status") != "SKIPPED"
        else (not require_walk_forward),
    }

    # Dry-run path: never research-validated
    if any(r.get("status") == "DRY_RUN" for r in (is_result, validation_result, oos_result)):
        return {
            "eligibility_status": "INCONCLUSIVE",
            "gates": gates,
            "eligibility_basis": ELIGIBILITY_BASIS,
            "production_status": None,
            "notes": "Dry-run cannot yield VALIDATED_FOR_RESEARCH",
            "forbidden": list(FORBIDDEN_VALIDATION_STATUSES),
        }

    required = ["IS_SUCCESS", "VALIDATION_SUCCESS", "OOS_SUCCESS"]
    if require_walk_forward:
        required.append("WALK_FORWARD_SUCCESS")

    if all(gates[k] for k in required):
        status = RESEARCH_ELIGIBLE_STATUS
    elif any(
        r.get("status") == "INSUFFICIENT_DATA" for r in (is_result, validation_result, oos_result)
    ):
        status = "INSUFFICIENT_DATA"
    else:
        status = "INCONCLUSIVE"

    return {
        "eligibility_status": status,
        "eligibility_basis": ELIGIBILITY_BASIS,
        "gates": gates,
        "production_status": None,
        "production_buy_emitted": False,
        "notes": (
            "VALIDATED_FOR_RESEARCH is not PRODUCTION eligibility. "
            "No BUY wiring. No profitability claim. "
            "See run-level cost/slippage and survivorship status."
        ),
        "forbidden": list(FORBIDDEN_VALIDATION_STATUSES),
    }


def assert_no_oos_parameter_selection(
    *,
    parameters_before_oos: dict[str, Any],
    parameters_after_oos: dict[str, Any],
) -> None:
    """OOS must not mutate parameters; changes require a new trial/version."""
    if parameters_before_oos != parameters_after_oos:
        raise ValidationConfigError(
            "OOS parameter retune forbidden — create a new trial/version and new OOS"
        )


def run_validation(config: ValidationConfig) -> dict[str, Any]:
    """Run IS → VALIDATION → OOS (+ optional walk-forward) with locked parameters."""
    created_at = datetime.now(UTC).isoformat()

    if not is_valid_horizon(config.horizon):
        return {
            "status": "REJECTED",
            "failure_reason": f"invalid horizon: {config.horizon}",
            "eligibility": None,
            "created_at": created_at,
        }

    if config.parameter_selection_phase not in ("IS", "TRAIN", "VALIDATION"):
        return {
            "status": "REJECTED",
            "failure_reason": (
                f"parameter_selection_phase={config.parameter_selection_phase!r} "
                f"invalid — OOS selection forbidden"
            ),
            "eligibility": None,
            "created_at": created_at,
        }

    try:
        validate_temporal_split(config.discovery, config.validation, config.oos)
    except ValidationConfigError as exc:
        return {
            "status": "REJECTED",
            "failure_reason": str(exc),
            "eligibility": None,
            "created_at": created_at,
            "shuffle_used": False,
        }

    params_locked = deepcopy(config.parameters)

    is_result = _evaluate_window(config, config.discovery, phase="IS")
    val_result = _evaluate_window(config, config.validation, phase="VALIDATION")
    oos_result = _evaluate_window(config, config.oos, phase="OOS")

    # Ensure OOS did not change parameters
    try:
        assert_no_oos_parameter_selection(
            parameters_before_oos=params_locked,
            parameters_after_oos=dict(config.parameters),
        )
    except ValidationConfigError as exc:
        return {
            "status": "REJECTED",
            "failure_reason": str(exc),
            "phases": {"IS": is_result, "VALIDATION": val_result, "OOS": oos_result},
            "created_at": created_at,
        }

    for phase_name, result, window in (
        ("IS", is_result, config.discovery),
        ("VALIDATION", val_result, config.validation),
        ("OOS", oos_result, config.oos),
    ):
        leak = _phase_sees_forbidden(
            phase_name,
            discovery=config.discovery,
            validation=config.validation,
            oos=config.oos,
            used_end=(result.get("actual_used_range") or {}).get("end") or window.end,
        )
        if leak:
            result["status"] = "REJECTED"
            result["failure_reason"] = leak

    wf_result = (
        run_walk_forward(config)
        if config.walk_forward
        else {
            "status": "SKIPPED",
            "folds": [],
            "aggregate": None,
        }
    )

    eligibility = evaluate_research_eligibility(
        is_result=is_result,
        validation_result=val_result,
        oos_result=oos_result,
        walk_forward_result=wf_result if config.walk_forward else None,
        require_walk_forward=config.walk_forward is not None,
    )

    # Hard safety: never attach production statuses
    if eligibility["eligibility_status"] in FORBIDDEN_VALIDATION_STATUSES:
        eligibility["eligibility_status"] = "INCONCLUSIVE"

    overall = "COMPLETED"
    if any(r.get("status") == "REJECTED" for r in (is_result, val_result, oos_result, wf_result)):
        overall = "REJECTED"
    elif config.dry_run:
        overall = "DRY_RUN"

    semantics = return_semantics(config.cost_model, config.slippage_model)
    return {
        "status": overall,
        "trial_id": config.trial_id,
        "strategy_id": config.strategy_id,
        "strategy_version": config.strategy_version,
        "horizon": config.horizon,
        "engine_version": config.engine_version,
        "data_version": config.data_version,
        "feature_version": config.feature_version,
        "universe_definition": config.universe_definition,
        "parameters_locked": params_locked,
        "parameter_selection_phase": config.parameter_selection_phase,
        "min_sample": config.min_sample,
        **semantics,
        "survivorship_status": config.survivorship_status,
        "survivorship_assessment": deepcopy(config.survivorship_assessment),
        "profitable_claim": False,
        "production_buy_emitted": False,
        "shuffle_used": False,
        "phases": {
            "IS": is_result,
            "VALIDATION": val_result,
            "OOS": oos_result,
            "WALK_FORWARD": wf_result,
        },
        "eligibility": eligibility,
        "robustness": {
            "status": "NOT_EXECUTED",
            "entrypoint": "idx.signal_discovery.robustness.run_robustness",
        },
        "notes": [
            "Temporal validation only — no random shuffle.",
            f"Gross unadjusted Close; net_return_status={semantics['net_return_status']}.",
            "VALIDATED_FOR_RESEARCH ≠ production BUY.",
            f"Survivorship {config.survivorship_status}.",
        ],
        "created_at": created_at,
        "DATA_SCHEMA_VERSION": DATA_SCHEMA_VERSION,
    }


def window_to_dict(window: ValidationWindow) -> dict[str, str]:
    return window.as_dict()


def validation_config_fingerprint(config: ValidationConfig) -> dict[str, Any]:
    """Serializable config subset (no DataFrames / callables)."""
    return {
        "trial_id": config.trial_id,
        "strategy_id": config.strategy_id,
        "strategy_version": config.strategy_version,
        "horizon": config.horizon,
        "engine_strategy": config.engine_strategy,
        "parameters": config.parameters,
        "holding_days": config.holding_days,
        "discovery": asdict(config.discovery),
        "validation": asdict(config.validation),
        "oos": asdict(config.oos),
        "min_sample": config.min_sample,
        "walk_forward": asdict(config.walk_forward) if config.walk_forward else None,
        "data_available_start": config.data_available_start,
        "data_available_end": config.data_available_end,
        "parameter_selection_phase": config.parameter_selection_phase,
        "cost_model": config.cost_model.as_dict(),
        "slippage_model": config.slippage_model.as_dict(),
        "survivorship_status": config.survivorship_status,
        "shuffle_used": False,
    }
