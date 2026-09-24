"""Strategy Lab — wrap existing backtest engine with honest validation flags.

Does not invent new strategies. Maps product names onto existing run_backtest
strategies or marks UNAVAILABLE / INSUFFICIENT OOS VALIDATION.
"""

from __future__ import annotations

import glob
import json
import os
from datetime import UTC, datetime
from typing import Any

from idx.backtest import TECHNICAL_RULES
from idx.core.utils import DATA_DIR
from idx.schema_version import DATA_SCHEMA_VERSION

ENGINE_VERSION = "strategy-lab-2.0"
RESEARCH_DIR = os.path.join(DATA_DIR, "research")
_STUDY_CACHE: dict[str, Any] = {"path": None, "mtime": None, "report": None}

# Product label → existing engine strategy id (or None if not implemented)
STRATEGY_CATALOG: dict[str, dict[str, Any]] = {
    "foreign_flow": {
        "engine": "foreign_flow",
        "status": "AVAILABLE",
        "oos": "INSUFFICIENT OOS VALIDATION",
        "notes": "Existing idx.backtest foreign_flow screen.",
    },
    "foreign_accumulation": {
        "engine": "foreign_flow",
        "status": "PARTIAL",
        "oos": "INSUFFICIENT OOS VALIDATION",
        "notes": "Alias of foreign_flow — not a separate validated edge.",
    },
    "bandarmology": {
        "engine": "bandarmology",
        "status": "PARTIAL",
        "oos": "INSUFFICIENT OOS VALIDATION",
        "notes": (
            "Legacy engine id: bullish EMA regime ranked by 20-session volume ratio. "
            "Uses no broker data — not actor attribution."
        ),
    },
    "sharia_value": {
        "engine": "sharia_value",
        "status": "AVAILABLE",
        "oos": "INSUFFICIENT OOS VALIDATION",
    },
    "composite_alpha": {
        "engine": "composite_alpha",
        "status": "AVAILABLE",
        "oos": "INSUFFICIENT OOS VALIDATION",
    },
    "dividend_arbitrage": {
        "engine": "dividend_arbitrage",
        "status": "AVAILABLE",
        "oos": "INSUFFICIENT OOS VALIDATION",
    },
    "close_pressure": {
        "engine": None,
        "status": "UNAVAILABLE",
        "oos": "INSUFFICIENT OOS VALIDATION",
        "notes": "Screener mode exists; dedicated backtest strategy not wired to run_backtest.",
    },
    "intraday": {
        "engine": None,
        "status": "UNAVAILABLE",
        "oos": "INSUFFICIENT OOS VALIDATION",
        "notes": "No intraday tape — cannot validate.",
    },
    "momentum": {
        "engine": "momentum",
        "status": "AVAILABLE",
        "oos": "INSUFFICIENT OOS VALIDATION",
        "notes": "Signal Discovery Stage-1 rule: " + TECHNICAL_RULES["momentum"],
    },
    "pullback": {
        "engine": "pullback",
        "status": "AVAILABLE",
        "oos": "INSUFFICIENT OOS VALIDATION",
        "notes": "Signal Discovery Stage-1 rule: " + TECHNICAL_RULES["pullback"],
    },
    "breakout": {
        "engine": "breakout",
        "status": "AVAILABLE",
        "oos": "INSUFFICIENT OOS VALIDATION",
        "notes": "Signal Discovery Stage-1 rule: " + TECHNICAL_RULES["breakout"],
    },
    "mean_reversion": {
        "engine": "mean_reversion",
        "status": "AVAILABLE",
        "oos": "INSUFFICIENT OOS VALIDATION",
        "notes": "Signal Discovery Stage-1 rule: " + TECHNICAL_RULES["mean_reversion"],
    },
    "volume_expansion": {
        "engine": "volume_expansion",
        "status": "AVAILABLE",
        "oos": "INSUFFICIENT OOS VALIDATION",
        "notes": "Signal Discovery Stage-1 rule: " + TECHNICAL_RULES["volume_expansion"],
    },
    "absorption": {
        "engine": None,
        "status": "UNAVAILABLE",
        "oos": "INSUFFICIENT OOS VALIDATION",
        "notes": "Research-only in backtest_v3*; not productized.",
    },
    "big_money_follow": {
        "engine": None,
        "status": "UNAVAILABLE",
        "oos": "INSUFFICIENT OOS VALIDATION",
        "notes": "DATA INSUFFICIENT — no stock-specific actor transactions.",
    },
    "swing": {
        "engine": None,
        "status": "UNAVAILABLE",
        "oos": "INSUFFICIENT OOS VALIDATION",
        "notes": "Screener swing engine exists; no dedicated run_backtest strategy id.",
    },
    "long_term": {
        "engine": None,
        "status": "UNAVAILABLE",
        "oos": "INSUFFICIENT OOS VALIDATION",
        "notes": "Long-term candidates are CANDIDATE labels only — expectancy not validated.",
    },
}


def latest_study_report() -> dict[str, Any] | None:
    """Newest ``idx discovery-study`` report under ``DATA_DIR/research`` (mtime-cached)."""
    paths = sorted(glob.glob(os.path.join(RESEARCH_DIR, "discovery_study_*.json")))
    if not paths:
        return None
    path = paths[-1]
    mtime = os.path.getmtime(path)
    if _STUDY_CACHE["path"] != path or _STUDY_CACHE["mtime"] != mtime:
        try:
            with open(path, encoding="utf-8") as fh:
                report = json.load(fh)
        except (OSError, ValueError):
            return None
        _STUDY_CACHE.update({"path": path, "mtime": mtime, "report": report})
    return _STUDY_CACHE["report"]


def research_validation(engine: str | None) -> dict[str, Any]:
    """Per-horizon study verdicts for an engine strategy; never a production status."""
    if engine is None:
        return {"status": "UNAVAILABLE", "by_horizon": {}, "report": None}
    report = latest_study_report()
    if report is None:
        return {
            "status": "NOT_VALIDATED",
            "reason": "no discovery study report",
            "by_horizon": {},
            "report": None,
        }
    from idx.signal_discovery.hypotheses import list_stage1_hypotheses

    ids = {h["strategy_id"] for h in list_stage1_hypotheses() if h["engine_strategy"] == engine}
    by_horizon = {
        t["horizon"]: t["verdict"] for t in report.get("trials", []) if t.get("strategy_id") in ids
    }
    if not by_horizon:
        status = "NOT_VALIDATED"
    elif "SURVIVES_RESEARCH_VALIDATION" in by_horizon.values():
        status = "SURVIVES_RESEARCH_VALIDATION"
    else:
        status = "NOT_VALIDATED"
    return {
        "status": status,
        "by_horizon": by_horizon,
        "report": os.path.basename(_STUDY_CACHE["path"] or "") or None,
        "study_generated_at": report.get("generated_at"),
        "production_status": None,
    }


def _oos_label(engine: str | None, default: str) -> str:
    rv = research_validation(engine)
    if not rv["by_horizon"]:
        return default
    summary = ", ".join(f"{h}={v}" for h, v in sorted(rv["by_horizon"].items()))
    return f"{rv['status']} (research study: {summary})"


def list_strategies() -> dict[str, Any]:
    return {
        "strategies": [
            {
                "id": k,
                **v,
                "oos": _oos_label(v.get("engine"), v["oos"]),
                "research_validation": research_validation(v.get("engine")),
                "profitable_claim": False,
            }
            for k, v in STRATEGY_CATALOG.items()
        ],
        "engine_version": ENGINE_VERSION,
        "DATA_SCHEMA_VERSION": DATA_SCHEMA_VERSION,
        "notes": [
            "Do not treat positive historical metrics as proven profitability.",
            "OOS/walk-forward/robustness/DSR verdicts come from the pre-registered discovery study.",
            "SURVIVES_RESEARCH_VALIDATION is research evidence only — never a production BUY.",
            "Offline backtest_v3* labs remain research artifacts, not production proof.",
        ],
        "calculated_at": datetime.now(UTC).isoformat(),
    }


def normalize_lab_metrics(metrics: dict[str, Any] | None) -> dict[str, Any]:
    """Expose Strategy Lab metrics; missing → UNAVAILABLE (never fake 0)."""
    keys = (
        "sample",
        "total_trades",
        "win_rate_pct",
        "expectancy_pct",
        "mfe",
        "mae",
        "median_mfe_pct",
        "median_mae_pct",
        "median_days",
        "median_holding_sessions",
        "max_drawdown_pct",
        "tp_hit_rate_pct",
        "cl_hit_rate_pct",
        "total_return_pct",
        "sharpe_ratio",
        "sortino_ratio",
        "profit_factor",
    )
    optional = (
        "mfe",
        "mae",
        "median_mfe_pct",
        "median_mae_pct",
        "median_days",
        "median_holding_sessions",
        "tp_hit_rate_pct",
        "cl_hit_rate_pct",
    )
    out: dict[str, Any] = {}
    src = metrics or {}
    # Aliases from run_backtest naming
    if "total_trades" in src and "sample" not in src:
        out["sample"] = src.get("total_trades")
    has_trades = bool(src.get("total_trades"))
    for k in keys:
        if k in src and src[k] is not None:
            out[k] = src[k]
        elif k == "sample" and "sample" in out:
            continue
        elif k in optional:
            out[k] = None
            rule_gap = has_trades and k in ("tp_hit_rate_pct", "cl_hit_rate_pct")
            out[f"{k}_status"] = "NOT_CONFIGURED" if rule_gap else "UNAVAILABLE"
        elif k in src:
            out[k] = src[k]
    # distribution placeholder
    out["distribution"] = src.get("distribution")
    out["distribution_status"] = "OK" if src.get("distribution") is not None else "UNAVAILABLE"
    return out


def validation_flags(
    *,
    sample_size: int | None,
    has_oos: bool = False,
) -> dict[str, Any]:
    return {
        "lookahead_guard": "PIT entry_date slicing; trailing features; no data-gap crossing",
        "leakage_risk": "LOW_IF_PIT_HONORED",
        "survivorship": "NOT_VALIDATED — no delisting/suspension/ticker-change data",
        "overfit": (
            "Single run is not overfit-controlled; use /api/strategy/validate (IS/VAL/OOS/WF) "
            "and the discovery study (robustness, DSR, BH-FDR)"
        ),
        "cost_slippage": "NOT_CONFIGURED — returns are gross, unadjusted Close",
        "insufficient_sample": bool(sample_size is not None and sample_size < 30),
        "oos_status": "OK" if has_oos else "INSUFFICIENT OOS VALIDATION",
        "profitable_claim_allowed": False,
    }


def run_strategy_lab(
    strategy_id: str,
    *,
    holding_days: int = 20,
    top_n: int = 10,
    min_turnover_rp: float = 1_000_000_000,
    start_date: str | None = None,
    end_date: str | None = None,
    stop_loss_pct: float | None = None,
    take_profit_pct: float | None = None,
    injected_frames: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = STRATEGY_CATALOG.get(strategy_id)
    if meta is None:
        return {
            "status": "UNAVAILABLE",
            "error": f"Unknown strategy '{strategy_id}'",
            "catalog": list_strategies(),
        }
    if meta.get("engine") is None:
        return {
            "status": meta["status"],
            "strategy": strategy_id,
            "oos": meta.get("oos"),
            "notes": meta.get("notes"),
            "metrics": None,
            "validation": validation_flags(sample_size=0, has_oos=False),
            "profitable_claim": False,
            "engine_version": ENGINE_VERSION,
            "DATA_SCHEMA_VERSION": DATA_SCHEMA_VERSION,
            "calculated_at": datetime.now(UTC).isoformat(),
        }

    from idx.backtest import run_backtest

    kwargs: dict[str, Any] = {
        "strategy": meta["engine"],
        "holding_days": holding_days,
        "top_n": top_n,
        "min_turnover_rp": min_turnover_rp,
    }
    if start_date:
        kwargs["start_date"] = start_date
    if end_date:
        kwargs["end_date"] = end_date
    if stop_loss_pct is not None:
        kwargs["stop_loss_pct"] = stop_loss_pct
    if take_profit_pct is not None:
        kwargs["take_profit_pct"] = take_profit_pct
    if injected_frames:
        if "stock_df" in injected_frames:
            kwargs["stock_df"] = injected_frames["stock_df"]
        if "ratios_df" in injected_frames:
            kwargs["ratios_df"] = injected_frames["ratios_df"]
        if "actions_df" in injected_frames:
            kwargs["actions_df"] = injected_frames["actions_df"]

    raw = run_backtest(**kwargs)
    metrics: dict[str, Any]
    trades_n = None
    if isinstance(raw, tuple) and len(raw) >= 1:
        metrics = raw[0] if isinstance(raw[0], dict) else {"raw": raw[0]}
        if len(raw) > 1 and hasattr(raw[1], "__len__"):
            try:
                trades_n = int(len(raw[1]))
            except Exception:
                trades_n = None
    elif isinstance(raw, dict):
        metrics = raw
    else:
        metrics = {"raw": raw}

    sample = metrics.get("total_trades") if isinstance(metrics, dict) else None
    if sample is None:
        sample = trades_n

    return {
        "status": "PARTIAL",
        "strategy": strategy_id,
        "engine_strategy": meta["engine"],
        "oos": "INSUFFICIENT OOS VALIDATION",
        "notes": meta.get("notes"),
        "metrics": metrics,
        "lab_metrics": normalize_lab_metrics(metrics),
        "validation": validation_flags(
            sample_size=int(sample) if sample is not None else None,
            has_oos=False,
        ),
        "research_validation": research_validation(meta["engine"]),
        "profitable_claim": False,
        "disclaimer": (
            "Historical metrics are descriptive only. "
            "INSUFFICIENT OOS VALIDATION — do not treat as production edge. "
            "MFE/MAE come from realised trade paths; TP/CL hit rates need a configured rule."
        ),
        "engine_version": ENGINE_VERSION,
        "DATA_SCHEMA_VERSION": DATA_SCHEMA_VERSION,
        "calculated_at": datetime.now(UTC).isoformat(),
    }


def run_strategy_validation(
    strategy_id: str,
    *,
    horizon: str,
    holding_days: int,
    discovery: tuple[str, str],
    validation: tuple[str, str],
    oos: tuple[str, str],
    top_n: int = 10,
    min_turnover_rp: float = 1_000_000_000,
    walk_forward: dict[str, Any] | None = None,
    injected_frames: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """IS → VALIDATION → OOS (+ optional walk-forward) through the discovery harness."""
    from idx.signal_discovery.validation import (
        ValidationConfig,
        ValidationConfigError,
        ValidationWindow,
        WalkForwardConfig,
        run_validation,
    )

    meta = STRATEGY_CATALOG.get(strategy_id)
    if meta is None or meta.get("engine") is None:
        return {
            "status": "UNAVAILABLE",
            "strategy": strategy_id,
            "reason": "unknown strategy" if meta is None else meta.get("notes"),
            "production_buy_emitted": False,
        }
    try:
        wf = WalkForwardConfig(**walk_forward) if walk_forward else None
    except (TypeError, ValidationConfigError) as exc:
        return {"status": "REJECTED", "failure_reason": f"walk_forward: {exc}"}

    frames = injected_frames or {}
    stock_df = frames.get("stock_df")
    if stock_df is None:
        from idx.backtest import _load_data

        stock_df, ratios_df, actions_df = _load_data()
    else:
        ratios_df, actions_df = frames.get("ratios_df"), frames.get("actions_df")
    dates = stock_df["Date"].astype(str).str[:10] if len(stock_df) else None

    cfg = ValidationConfig(
        trial_id=f"lab::{strategy_id}::{horizon}::{holding_days}",
        strategy_id=strategy_id,
        strategy_version=ENGINE_VERSION,
        horizon=horizon,
        engine_strategy=meta["engine"],
        parameters={"top_n": int(top_n), "min_turnover_rp": float(min_turnover_rp)},
        holding_days=int(holding_days),
        discovery=ValidationWindow(*discovery),
        validation=ValidationWindow(*validation),
        oos=ValidationWindow(*oos),
        universe_definition=f"20-session avg Value >= {min_turnover_rp:.0f}",
        data_available_start=dates.min() if dates is not None else None,
        data_available_end=dates.max() if dates is not None else None,
        walk_forward=wf,
        stock_df=stock_df,
        ratios_df=ratios_df,
        actions_df=actions_df,
    )
    try:
        result = run_validation(cfg)
    except ValidationConfigError as exc:
        return {"status": "REJECTED", "failure_reason": str(exc)}
    result["strategy"] = strategy_id
    result["research_validation"] = research_validation(meta["engine"])
    return result
