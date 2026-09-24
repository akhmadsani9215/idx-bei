"""Controlled multi-horizon discovery study (Clusters 6–8).

Every Stage-1 family × every horizon runs through the same pre-registered
protocol — IS → VALIDATION → OOS → walk-forward → illustrative cost stress →
IS robustness → baseline comparison → Deflated Sharpe → BH-FDR — and gets an
explicit verdict. Nothing is tuned on results; nothing becomes a production BUY.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from idx.backtest import MAX_SESSION_GAP_DAYS, _ca_event_index, run_backtest
from idx.core.price_adjustment import forward_adjust
from idx.signal_discovery.contract import ENGINE_VERSION, HORIZON_HOLDING_BOUNDS, HORIZONS
from idx.signal_discovery.costs import (
    CostModel,
    SlippageModel,
    illustrative_cost_model,
    illustrative_slippage_model,
)
from idx.signal_discovery.hypotheses import (
    STRATEGY_VERSION,
    horizon_policy,
    list_stage1_hypotheses,
)
from idx.signal_discovery.multiple_testing import (
    DEFAULT_FDR_ALPHA,
    benjamini_hochberg,
    deflated_sharpe_ratio,
    mean_return_pvalue,
    return_moments,
)
from idx.signal_discovery.registry import TrialRegistry
from idx.signal_discovery.robustness import RobustnessConfig, run_robustness
from idx.signal_discovery.survivorship import audit_survivorship_evidence
from idx.signal_discovery.validation import (
    DEFAULT_MIN_SAMPLE,
    RESEARCH_ELIGIBLE_STATUS,
    ValidationConfig,
    ValidationWindow,
    WalkForwardConfig,
    run_validation,
)

STUDY_VERSION = "controlled-study-1.0"

VERDICTS: tuple[str, ...] = (
    "SURVIVES_RESEARCH_VALIDATION",
    "FAILED",
    "FRAGILE",
    "INCONCLUSIVE",
    "INSUFFICIENT_DATA",
    "UNAVAILABLE",
)

VERDICT_RULES: dict[str, str] = {
    "UNAVAILABLE": "horizon not executable with current data (no fabricated evaluation)",
    "INSUFFICIENT_DATA": "any IS/VALIDATION/OOS phase below min_sample or outside coverage",
    "FAILED": (
        "OOS gross expectancy <= 0, or <= liquid-universe baseline, "
        "or OOS illustrative-net expectancy <= 0"
    ),
    "FRAGILE": "IS robustness FRAGILE, or any evaluable walk-forward fold expectancy <= 0",
    "SURVIVES_RESEARCH_VALIDATION": (
        "VALIDATED_FOR_RESEARCH (all phases + all WF folds sample-sufficient) AND gross "
        "expectancy > 0 and > baseline in IS, VALIDATION and OOS AND OOS illustrative-net > 0 "
        "AND robustness ROBUST AND DSR PASS AND BH-FDR DISCOVERY"
    ),
    "INCONCLUSIVE": "none of the above; reasons list the unmet SURVIVES checks",
}

STUDY_PARAMETERS: dict[str, Any] = {"top_n": 10, "min_turnover_rp": 1_000_000_000}


@dataclass
class StudyPlan:
    """Pre-registered study protocol; every field is explicit (no date defaults)."""

    discovery: ValidationWindow
    validation: ValidationWindow
    oos: ValidationWindow
    walk_forward: WalkForwardConfig
    stress_cost: CostModel
    stress_slippage: SlippageModel
    max_trials: int
    horizons: tuple[str, ...] = HORIZONS
    min_sample: int = DEFAULT_MIN_SAMPLE
    robustness_max_variants: int = 8
    fdr_alpha: float = DEFAULT_FDR_ALPHA
    parameters: dict[str, Any] = field(default_factory=lambda: dict(STUDY_PARAMETERS))


def default_plan_for_local_data() -> StudyPlan:
    """Protocol fixed on 2026-09-23 for the local 2025-01-02 → 2026-09-22 dataset."""
    return StudyPlan(
        discovery=ValidationWindow("2025-01-02", "2025-10-31"),
        validation=ValidationWindow("2025-11-01", "2026-03-31"),
        oos=ValidationWindow("2026-04-01", "2026-09-22"),
        walk_forward=WalkForwardConfig(
            train_start="2025-01-02",
            first_train_end="2025-10-31",
            test_span_calendar_days=60,
            step_calendar_days=60,
            n_folds=5,
            parameter_version="stage1-locked",
        ),
        stress_cost=illustrative_cost_model(buy_fee_bps=15, sell_fee_bps=25, label="stress-15-25"),
        stress_slippage=illustrative_slippage_model(per_side_bps=10, label="stress-10"),
        max_trials=64,
    )


def holding_neighbors(horizon: str, holding: int) -> list[int]:
    """Two neighbours around ``holding`` clipped to the horizon's session bounds."""
    lo, hi = HORIZON_HOLDING_BOUNDS[horizon]
    if lo is None or hi is None:
        return []
    step = max(1, holding // 4)
    return sorted({h for h in (max(lo, holding - step), min(hi, holding + step)) if h != holding})


class _CachedEngine:
    """``evaluate_fn`` over the real ``run_backtest`` that keeps each ledger once.

    Each call slices prices to ``[start - 180d, end]`` so feature warm-up is
    intact without re-scanning 2023–2024 on every window.
    """

    _WARMUP_CALENDAR_DAYS = 180

    def __init__(self, stock_df: pd.DataFrame, ratios_df: pd.DataFrame, actions_df: Any) -> None:
        stock = stock_df.copy()
        stock["Date"] = pd.to_datetime(stock["Date"], errors="coerce")
        stock = stock.dropna(subset=["Date"])
        self.ca_event_index = _ca_event_index(stock, actions_df)
        self.stock_df = forward_adjust(stock)
        self.ratios_df, self.actions_df = ratios_df, actions_df
        self.ledgers: dict[tuple, pd.DataFrame] = {}
        self._raw: dict[tuple, dict[str, Any]] = {}
        self.engine_runs = 0

    def _slice(self, start: str, end: str) -> pd.DataFrame:
        start_ts = pd.to_datetime(start)
        end_ts = pd.to_datetime(end)
        warm = start_ts - pd.Timedelta(days=self._WARMUP_CALENDAR_DAYS)
        mask = (self.stock_df["Date"] >= warm) & (self.stock_df["Date"] <= end_ts)
        return self.stock_df.loc[mask]

    @staticmethod
    def key(strategy: str, holding: int, start: str, end: str, params: dict[str, Any]) -> tuple:
        return (strategy, holding, start, end, tuple(sorted(params.items())))

    def __call__(self, strategy, holding, start, end, params):
        k = self.key(strategy, holding, start, end, params)
        if k not in self._raw:
            kwargs: dict[str, Any] = {
                "strategy": strategy,
                "holding_days": holding,
                "top_n": int(params.get("top_n", 10)),
                "min_turnover_rp": float(params.get("min_turnover_rp", 1e9)),
                "start_date": start,
                "end_date": end,
                "stock_df": self._slice(start, end),
                "ratios_df": self.ratios_df,
                "actions_df": self.actions_df,
                "adjust_prices": False,
                "exclude_ca_events": True,
                "ca_event_index": self.ca_event_index,
            }
            for rule in ("stop_loss_pct", "take_profit_pct"):
                if params.get(rule) is not None:
                    kwargs[rule] = float(params[rule])
            raw, trades = run_backtest(**kwargs)
            self._raw[k], self.ledgers[k] = raw, trades
            self.engine_runs += 1
        return self._raw[k], self.ledgers[k]


def report_json_safe(value: Any) -> Any:
    """NaN/Inf → None, numpy scalars → Python, recursively (strict JSON output)."""
    if isinstance(value, dict):
        return {str(k): report_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [report_json_safe(v) for v in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def _period_returns(ledgers: list[pd.DataFrame]) -> list[float]:
    frames = [t for t in ledgers if t is not None and len(t) and "Return" in t.columns]
    if not frames:
        return []
    allt = pd.concat(frames, ignore_index=True)
    return allt.groupby("ExitDate", sort=True)["Return"].mean().astype(float).tolist()


def _data_profile(stock_df: pd.DataFrame) -> dict[str, Any]:
    dates = pd.Series(
        pd.to_datetime(stock_df["Date"], errors="coerce").dropna().unique()
    ).sort_values()
    gaps = []
    prev = None
    for d in dates:
        if prev is not None and (d - prev).days > MAX_SESSION_GAP_DAYS:
            gaps.append(
                {
                    "from": prev.strftime("%Y-%m-%d"),
                    "to": d.strftime("%Y-%m-%d"),
                    "calendar_days": int((d - prev).days),
                }
            )
        prev = d
    return {
        "start": dates.iloc[0].strftime("%Y-%m-%d") if len(dates) else None,
        "end": dates.iloc[-1].strftime("%Y-%m-%d") if len(dates) else None,
        "sessions": int(len(dates)),
        "tickers": int(stock_df["StockCode"].nunique()),
        "data_gaps": gaps,
    }


class _Baseline:
    """Liquid-universe forward return at the engine's rebalance dates (same gap rules)."""

    def __init__(self, stock_df: pd.DataFrame) -> None:
        df = stock_df[["Date", "StockCode", "Close", "Value"]].copy()
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.dropna(subset=["Date"])
        self.close = df.pivot_table(
            index="Date", columns="StockCode", values="Close", aggfunc="last"
        )
        value = df.pivot_table(index="Date", columns="StockCode", values="Value", aggfunc="last")
        dates = self.close.index
        seg = np.cumsum(
            np.r_[
                0,
                (np.diff(dates.values).astype("timedelta64[D]").astype(int) > MAX_SESSION_GAP_DAYS),
            ]
        )
        self.segment = pd.Series(seg, index=dates)
        self.avg_value = value.groupby(self.segment.values).transform(
            lambda s: s.rolling(20, min_periods=5).mean()
        )

    def expectancy_pct(
        self, window: ValidationWindow, holding: int, min_turnover: float
    ) -> float | None:
        idx = self.close.index
        in_win = idx[(idx >= window.start) & (idx <= window.end)]
        rets: list[np.ndarray] = []
        for i in range(0, len(in_win) - holding, holding):
            d0, d1 = in_win[i], in_win[i + holding]
            if self.segment[d0] != self.segment[d1]:
                continue
            c0, c1 = self.close.loc[d0], self.close.loc[d1]
            liquid = (self.avg_value.loc[d0] >= min_turnover) & (c0 > 0) & c1.notna()
            r = (c1[liquid] / c0[liquid] - 1.0).to_numpy(dtype=float)
            rets.append(r[np.isfinite(r)])
        allr = np.concatenate(rets) if rets else np.array([])
        return round(float(allr.mean()) * 100.0, 4) if allr.size else None


def _phase_summary(phase: dict[str, Any], baseline: float | None) -> dict[str, Any]:
    m = phase.get("metrics") or {}
    net = phase.get("net_returns") or {}
    exp = m.get("expectancy_pct")
    return {
        "status": phase.get("status"),
        "sample_count": phase.get("sample_count"),
        "gross_expectancy_pct": exp,
        "illustrative_net_expectancy_pct": net.get("net_expectancy_pct"),
        "baseline_expectancy_pct": baseline,
        "excess_vs_baseline_pct": (
            round(exp - baseline, 4) if exp is not None and baseline is not None else None
        ),
        "win_rate_pct": m.get("win_rate_pct"),
        "median_mfe_pct": m.get("mfe"),
        "median_mae_pct": m.get("mae"),
        "median_holding_sessions": m.get("median_holding_sessions"),
        "sharpe_ratio": m.get("sharpe_ratio"),
        "max_drawdown_pct": m.get("max_drawdown_pct"),
        "failure_reason": phase.get("failure_reason"),
    }


def _positive(x: float | None) -> bool:
    return x is not None and x > 0


def _verdict(trial: dict[str, Any]) -> tuple[str, list[str]]:
    phases = trial["phases"]
    if any(phases[p]["status"] != "OK" for p in ("IS", "VALIDATION", "OOS")):
        return "INSUFFICIENT_DATA", [
            f"{p}: {phases[p]['status']} ({phases[p]['failure_reason']})"
            for p in ("IS", "VALIDATION", "OOS")
            if phases[p]["status"] != "OK"
        ]
    oos = phases["OOS"]
    failed = []
    if not _positive(oos["gross_expectancy_pct"]):
        failed.append("OOS gross expectancy <= 0")
    if oos["excess_vs_baseline_pct"] is None or oos["excess_vs_baseline_pct"] <= 0:
        failed.append("OOS expectancy not above liquid-universe baseline")
    if not _positive(oos["illustrative_net_expectancy_pct"]):
        failed.append("OOS illustrative-net expectancy <= 0")
    if failed:
        return "FAILED", failed

    fragile = []
    if trial["robustness_status"] == "FRAGILE":
        fragile.append(f"robustness FRAGILE ({trial['robustness_reasons']})")
    wf_exps = [
        f["gross_expectancy_pct"] for f in trial["walk_forward_folds"] if f["status"] == "OK"
    ]
    if any(e is not None and e <= 0 for e in wf_exps):
        fragile.append("walk-forward fold with expectancy <= 0")
    if fragile:
        return "FRAGILE", fragile

    unmet = []
    if trial["eligibility_status"] != RESEARCH_ELIGIBLE_STATUS:
        unmet.append(f"eligibility {trial['eligibility_status']}")
    for p in ("IS", "VALIDATION"):
        if not _positive(phases[p]["gross_expectancy_pct"]):
            unmet.append(f"{p} gross expectancy <= 0")
        if not _positive(phases[p]["excess_vs_baseline_pct"]):
            unmet.append(f"{p} not above baseline")
    if trial["robustness_status"] != "ROBUST":
        unmet.append(f"robustness {trial['robustness_status']}")
    if trial["deflated_sharpe"]["status"] != "PASS":
        unmet.append(f"DSR {trial['deflated_sharpe']['status']}")
    if trial["fdr_decision"] != "DISCOVERY":
        unmet.append(f"BH-FDR {trial['fdr_decision']}")
    if unmet:
        return "INCONCLUSIVE", unmet
    return "SURVIVES_RESEARCH_VALIDATION", []


def run_controlled_study(
    plan: StudyPlan,
    stock_df: pd.DataFrame,
    ratios_df: pd.DataFrame,
    actions_df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Run the pre-registered protocol for every Stage-1 family × horizon."""
    engine = _CachedEngine(stock_df, ratios_df, actions_df)
    baseline = _Baseline(stock_df)
    profile = _data_profile(stock_df)
    survivorship = audit_survivorship_evidence(
        stock_df[["Date", "StockCode"]],
        actions_df[["TanggalPencatatan", "caType"]]
        if actions_df is not None and {"TanggalPencatatan", "caType"} <= set(actions_df.columns)
        else None,
    )
    registry = TrialRegistry()
    trials: list[dict[str, Any]] = []
    not_evaluated: list[dict[str, Any]] = []
    period_returns: dict[str, list[float]] = {}
    oos_returns: dict[str, list[float]] = {}
    limit_reached = False

    for horizon in plan.horizons:
        policy = horizon_policy(horizon)
        for hyp in list_stage1_hypotheses():
            trial_id = f"study::{hyp['strategy_id']}::{horizon}"
            if not policy.get("executable") or policy.get("holding_days") is None:
                not_evaluated.append(
                    {
                        "trial_id": trial_id,
                        "strategy_id": hyp["strategy_id"],
                        "family": hyp["hypothesis_family"],
                        "horizon": horizon,
                        "verdict": "UNAVAILABLE",
                        "reason": policy.get("reason") or "horizon not executable",
                    }
                )
                continue
            if len(trials) >= plan.max_trials:
                limit_reached = True
                not_evaluated.append(
                    {"trial_id": trial_id, "horizon": horizon, "verdict": "TRIAL_LIMIT_REACHED"}
                )
                continue

            holding = int(policy["holding_days"])
            cfg = ValidationConfig(
                trial_id=trial_id,
                strategy_id=hyp["strategy_id"],
                strategy_version=STRATEGY_VERSION,
                horizon=horizon,
                engine_strategy=hyp["engine_strategy"],
                parameters=dict(plan.parameters),
                holding_days=holding,
                discovery=plan.discovery,
                validation=plan.validation,
                oos=plan.oos,
                universe_definition=(
                    f"all IDX stock_summary tickers with 20-session avg Value >= "
                    f"{plan.parameters['min_turnover_rp']:.0f} (survivorship "
                    f"{survivorship['survivorship_status']})"
                ),
                min_sample=plan.min_sample,
                data_available_start=profile["start"],
                data_available_end=profile["end"],
                walk_forward=plan.walk_forward,
                evaluate_fn=engine,
                cost_model=plan.stress_cost,
                slippage_model=plan.stress_slippage,
                survivorship_assessment=survivorship["policy"],
            )
            val = run_validation(cfg)
            rob = run_robustness(
                RobustnessConfig(
                    base=cfg,
                    evaluation_phase="IS",
                    max_variants=plan.robustness_max_variants,
                    parameter_neighbors={"top_n": [5, 15]},
                    universe_neighbors={"min_turnover_rp": [5e8, 2e9]},
                    holding_days_neighbors=holding_neighbors(horizon, holding),
                )
            )

            phases = {}
            ledgers = []
            for name, window in (
                ("IS", plan.discovery),
                ("VALIDATION", plan.validation),
                ("OOS", plan.oos),
            ):
                base = baseline.expectancy_pct(window, holding, plan.parameters["min_turnover_rp"])
                phases[name] = _phase_summary(val["phases"][name], base)
                k = engine.key(
                    hyp["engine_strategy"], holding, window.start, window.end, plan.parameters
                )
                ledgers.append(engine.ledgers.get(k))
            period_returns[trial_id] = _period_returns(ledgers)
            oos_returns[trial_id] = _period_returns(ledgers[2:])

            wf = val["phases"]["WALK_FORWARD"]
            folds = []
            for f in wf.get("folds") or []:
                fm = f.get("metrics") or {}
                folds.append(
                    {
                        "fold_id": f.get("fold_id"),
                        "test": [f.get("test_start"), f.get("test_end")],
                        "status": f.get("status"),
                        "sample_count": f.get("sample_count"),
                        "gross_expectancy_pct": fm.get("expectancy_pct"),
                    }
                )

            record = {
                "trial_id": trial_id,
                "strategy_id": hyp["strategy_id"],
                "family": hyp["hypothesis_family"],
                "hypothesis": hyp["hypothesis"],
                "entry_rule": hyp["entry_rule"],
                "exit_rule": hyp["exit_rule"],
                "horizon": horizon,
                "holding_days": holding,
                "parameters": dict(plan.parameters),
                "phases": phases,
                "walk_forward_status": wf.get("status"),
                "walk_forward_folds": folds,
                "eligibility_status": val["eligibility"]["eligibility_status"]
                if val.get("eligibility")
                else None,
                "robustness_status": rob.get("robustness_status"),
                "robustness_reasons": rob.get("robustness_reasons"),
                "robustness_dimensions": {
                    d: {k: v for k, v in r.items() if k != "reasons"}
                    | {"reasons": r.get("reasons")}
                    for d, r in (rob.get("dimensions") or {}).items()
                },
                "cost_semantics": {
                    "cost_model": plan.stress_cost.model_id,
                    "slippage_model": plan.stress_slippage.model_id,
                    "net_return_status": val.get("net_return_status"),
                    "return_is_net_tradable": val.get("return_is_net_tradable"),
                },
                "production_status": None,
                "production_buy_emitted": False,
            }
            trials.append(record)
            registry.register(
                {
                    "trial_id": trial_id,
                    "strategy_id": hyp["strategy_id"],
                    "strategy_version": STRATEGY_VERSION,
                    "horizon": horizon,
                    "hypothesis": hyp["hypothesis"],
                    "hypothesis_family": hyp["hypothesis_family"],
                    "feature_set": hyp["feature_set"],
                    "parameters": dict(plan.parameters) | {"holding_days": holding},
                    "holding_days": holding,
                    "universe_definition": cfg.universe_definition,
                    "discovery_period": plan.discovery.as_dict(),
                    "validation_period": plan.validation.as_dict(),
                    "oos_period": plan.oos.as_dict(),
                    "cost_model": plan.stress_cost.model_id,
                    "slippage_model": plan.stress_slippage.model_id,
                    "engine_version": ENGINE_VERSION,
                    "data_version": cfg.data_version,
                    "data_quality": (
                        "C (EOD OHLCV, exchange-reference adjusted; CA-event trades excluded)"
                    ),
                    "created_at": val.get("created_at"),
                    "status": "VALIDATION",
                    "metrics": val["phases"]["OOS"].get("metrics") or {},
                    "failure_reason": None,
                }
            )
            registry.record_robustness_run(rob)

    mt = registry.multiple_testing_summary()
    n_evals = int(mt["evaluations_upper_bound"])
    sharpes = {tid: return_moments(r)["sharpe"] for tid, r in period_returns.items()}
    trial_sharpes = [s for s in sharpes.values() if s is not None]
    fdr = benjamini_hochberg(
        {tid: mean_return_pvalue(r) for tid, r in oos_returns.items()}, alpha=plan.fdr_alpha
    )
    for t in trials:
        dsr = deflated_sharpe_ratio(
            period_returns[t["trial_id"]], trial_sharpes=trial_sharpes, n_trials=n_evals
        )
        t["deflated_sharpe"] = {
            k: (round(v, 6) if isinstance(v, float) and math.isfinite(v) else v)
            for k, v in dsr.items()
            if k != "method_notes"
        }
        t["fdr_decision"] = fdr["decisions"].get(t["trial_id"], "UNTESTABLE")
        t["verdict"], t["verdict_reasons"] = _verdict(t)

    counts: dict[str, int] = {v: 0 for v in VERDICTS}
    for t in trials:
        counts[t["verdict"]] += 1
    counts["UNAVAILABLE"] += sum(1 for n in not_evaluated if n["verdict"] == "UNAVAILABLE")

    return {
        "study_version": STUDY_VERSION,
        "engine_version": ENGINE_VERSION,
        "strategy_version": STRATEGY_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "data_profile": profile,
        "survivorship": {
            "status": survivorship["survivorship_status"],
            "observations": survivorship["observations"],
        },
        "protocol": {
            "discovery": plan.discovery.as_dict(),
            "validation": plan.validation.as_dict(),
            "oos": plan.oos.as_dict(),
            "walk_forward": {
                "train_start": plan.walk_forward.train_start,
                "first_train_end": plan.walk_forward.first_train_end,
                "test_span_calendar_days": plan.walk_forward.test_span_calendar_days,
                "step_calendar_days": plan.walk_forward.step_calendar_days,
                "n_folds": plan.walk_forward.n_folds,
            },
            "parameters": plan.parameters,
            "price_basis": "EXCHANGE_REFERENCE_ADJUSTED",
            "exclude_ca_events": True,
            "min_sample": plan.min_sample,
            "robustness": "IS only; top_n [5,15]; min_turnover_rp [5e8,2e9]; holding ±max(1,h//4)",
            "stress_cost": plan.stress_cost.as_dict(),
            "stress_slippage": plan.stress_slippage.as_dict(),
            "fdr_alpha": plan.fdr_alpha,
            "verdict_rules": VERDICT_RULES,
        },
        "verdict_counts": counts,
        "trials": trials,
        "not_evaluated": not_evaluated,
        "trial_limit_reached": limit_reached,
        "multiple_testing": mt | {"fdr": {k: v for k, v in fdr.items() if k != "decisions"}},
        "engine_runs": engine.engine_runs,
        "profitable_claim": False,
        "production_buy_emitted": False,
        "notes": [
            "Research study only; no verdict wires a BUY into screener/production.",
            "Illustrative stress costs are not an IDX fee schedule; net returns are not tradable.",
            "Close-to-close on exchange-reference adjusted prices; trades spanning "
            "price-distorting CA events are excluded; survivorship NOT_VALIDATED.",
        ],
    }
