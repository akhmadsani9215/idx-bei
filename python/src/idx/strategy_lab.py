"""Strategy Lab — wrap existing backtest engine with honest validation flags.

Does not invent new strategies. Maps product names onto existing run_backtest
strategies or marks UNAVAILABLE / INSUFFICIENT OOS VALIDATION.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from idx.schema_version import DATA_SCHEMA_VERSION

ENGINE_VERSION = "strategy-lab-1.0"

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
        "notes": "Market-wide broker concentration proxy — not actor attribution.",
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
        "engine": None,
        "status": "UNAVAILABLE",
        "oos": "INSUFFICIENT OOS VALIDATION",
        "notes": "Research-only in backtest_v3*; not productized in run_backtest.",
    },
    "pullback": {
        "engine": None,
        "status": "UNAVAILABLE",
        "oos": "INSUFFICIENT OOS VALIDATION",
        "notes": "Research-only in backtest_v3*; not productized.",
    },
    "breakout": {
        "engine": None,
        "status": "UNAVAILABLE",
        "oos": "INSUFFICIENT OOS VALIDATION",
        "notes": "Research-only in backtest_v3*; not productized.",
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


def list_strategies() -> dict[str, Any]:
    return {
        "strategies": [
            {"id": k, **v, "profitable_claim": False}
            for k, v in STRATEGY_CATALOG.items()
        ],
        "engine_version": ENGINE_VERSION,
        "DATA_SCHEMA_VERSION": DATA_SCHEMA_VERSION,
        "notes": [
            "Do not treat positive historical metrics as proven profitability.",
            "Walk-forward / OOS validation is INSUFFICIENT for all listed strategies.",
            "Offline backtest_v3* labs remain research artifacts, not production proof.",
        ],
        "calculated_at": datetime.now(timezone.utc).isoformat(),
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
        "max_drawdown_pct",
        "tp_hit_rate_pct",
        "cl_hit_rate_pct",
        "total_return_pct",
        "sharpe_ratio",
        "sortino_ratio",
        "profit_factor",
    )
    out: dict[str, Any] = {}
    src = metrics or {}
    # Aliases from run_backtest naming
    if "total_trades" in src and "sample" not in src:
        out["sample"] = src.get("total_trades")
    for k in keys:
        if k in src and src[k] is not None:
            out[k] = src[k]
        elif k == "sample" and "sample" in out:
            continue
        elif k in ("mfe", "mae", "median_mfe_pct", "median_mae_pct", "median_days", "tp_hit_rate_pct", "cl_hit_rate_pct"):
            out[k] = None  # UNAVAILABLE in structured response
            out[f"{k}_status"] = "UNAVAILABLE"
        elif k in src:
            out[k] = src[k]
    # distribution placeholder
    out["distribution"] = src.get("distribution")
    out["distribution_status"] = (
        "OK" if src.get("distribution") is not None else "UNAVAILABLE"
    )
    return out


def validation_flags(
    *,
    sample_size: int | None,
    has_oos: bool = False,
) -> dict[str, Any]:
    return {
        "lookahead_guard": "PIT entry_date slicing enforced in idx.backtest",
        "leakage_risk": "LOW_IF_PIT_HONORED",
        "survivorship": "UNADDRESSED — listed universe only, no delisting reconstruction",
        "overfit": "UNKNOWN — no walk-forward/OOS harness in production path",
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
            "calculated_at": datetime.now(timezone.utc).isoformat(),
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
        "profitable_claim": False,
        "disclaimer": (
            "Historical metrics are descriptive only. "
            "INSUFFICIENT OOS VALIDATION — do not treat as production edge. "
            "MFE/MAE/TP-hit may be UNAVAILABLE when the engine does not compute them."
        ),
        "engine_version": ENGINE_VERSION,
        "DATA_SCHEMA_VERSION": DATA_SCHEMA_VERSION,
        "calculated_at": datetime.now(timezone.utc).isoformat(),
    }
