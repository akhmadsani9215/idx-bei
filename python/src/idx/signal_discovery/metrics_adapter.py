"""Metrics adapter for discovery validation (Cluster 3).

Normalizes existing ``run_backtest`` outputs without rewriting the engine.
Unavailable metrics stay null / NOT_AVAILABLE — never fake tradable zeros.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from idx.signal_discovery.registry import empty_metrics_record, normalize_engine_metrics

# Canonical keys exposed by the validation harness.
ADAPTER_METRIC_KEYS: tuple[str, ...] = (
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
    "expectancy_pct",
    "tp_hit_rate_pct",
    "cl_hit_rate_pct",
    "profit_factor",
)

# Outcome metrics that run_backtest supplies only when trades exist (TP/CL only with a rule).
ENGINE_UNAVAILABLE_METRICS: frozenset[str] = frozenset(
    {"mfe", "mae", "tp_hit_rate_pct", "cl_hit_rate_pct"}
)
_RULE_DEPENDENT_METRICS: frozenset[str] = frozenset({"tp_hit_rate_pct", "cl_hit_rate_pct"})


def adapt_backtest_metrics(
    raw: dict[str, Any] | None,
    *,
    trades_df: pd.DataFrame | None = None,
    holding_days: int | None = None,
) -> dict[str, Any]:
    """Adapt engine metrics for validation records.

    Expectancy: if engine lacks ``expectancy_pct`` but trades have a return
    column, use mean trade return (%). Still gross / not net tradable.

    MFE / MAE / TP_hit / CL_hit come from the engine trade paths; with trades but
    no TP/SL rule the hit rates are NOT_CONFIGURED. Never invented.
    """
    out = normalize_engine_metrics(raw)
    if holding_days is not None and out.get("holding_period") is None:
        out["holding_period"] = holding_days
    has_trades = bool(out.get("sample_count"))

    # Expectancy from trade ledger when missing from metrics dict
    if out.get("expectancy_pct") is None and trades_df is not None and len(trades_df) > 0:
        exp = _expectancy_from_trades(trades_df)
        if exp is not None:
            out["expectancy_pct"] = exp
            out.pop("expectancy_pct_status", None)

    for key in ENGINE_UNAVAILABLE_METRICS:
        if out.get(key) is None:
            configured_gap = has_trades and key in _RULE_DEPENDENT_METRICS
            out[f"{key}_status"] = "NOT_CONFIGURED" if configured_gap else "NOT_AVAILABLE"
        else:
            out.pop(f"{key}_status", None)

    out["return_is_net_tradable"] = False
    out["return_basis"] = "GROSS_UNADJUSTED_CLOSE — not net tradable return"
    if out.get("sample_count", 0) and out.get("sample_count", 0) > 0:
        if out.get("metrics_status") == "NOT_AVAILABLE":
            out["metrics_status"] = "PARTIAL"
    return out


# run_backtest ledger columns with fixed units: column -> multiplier to percent.
_LEDGER_RETURN_UNITS: tuple[tuple[str, float], ...] = (("Return", 100.0), ("ReturnPct", 1.0))


def _expectancy_from_trades(trades_df: pd.DataFrame) -> float | None:
    """Mean gross trade return in percent from the engine ledger (explicit units only)."""
    for col, to_pct in _LEDGER_RETURN_UNITS:
        if col in trades_df.columns:
            series = pd.to_numeric(trades_df[col], errors="coerce").dropna()
            if len(series) == 0:
                return None
            return round(float(series.mean()) * to_pct, 4)
    return None


def mark_unavailable_shell() -> dict[str, Any]:
    out = empty_metrics_record()
    out["return_is_net_tradable"] = False
    for key in ENGINE_UNAVAILABLE_METRICS:
        out[f"{key}_status"] = "NOT_AVAILABLE"
    return out
