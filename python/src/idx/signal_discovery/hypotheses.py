"""Stage-1 curated hypothesis catalog (small, interpretable).

Maps families onto existing ``run_backtest`` strategies when available.
Families without a productized engine stay ``engine_strategy=None`` →
evaluation yields ``INSUFFICIENT_DATA`` (no fabricated features).
"""

from __future__ import annotations

from typing import Any

from idx.backtest import TECHNICAL_RULES

STRATEGY_VERSION = "stage1-0.2.0"
FEATURE_VERSION = "signals-parquet-1.0"

# Horizon execution policy for Cluster 2 — explicit, no silent fallback.
HORIZON_EXECUTION: dict[str, dict[str, Any]] = {
    "INTRADAY": {
        "executable": False,
        "holding_days": None,
        "reason": "No intraday tape — cannot evaluate INTRADAY horizon",
    },
    "NEXT_DAY_1_3D": {
        "executable": True,
        "holding_days": 2,
        "reason": None,
    },
    "SWING_3_10D": {
        "executable": True,
        "holding_days": 7,
        "reason": None,
    },
    "SWING_2_4W": {
        "executable": True,
        "holding_days": 15,
        "reason": None,
    },
    "POSITION_1_3M": {
        "executable": True,
        "holding_days": 42,
        "reason": None,
    },
    "LONG_TERM_3_12M": {
        "executable": False,
        "holding_days": None,
        "reason": (
            "Long-term expectancy not validated in production path; "
            "screener labels CANDIDATE only — no silent fallback"
        ),
    },
    "MULTIBAGGER_1_5Y": {
        "executable": False,
        "holding_days": None,
        "reason": (
            "Multibagger horizon unsupported without survivorship-safe "
            "multi-year universe and CA-adjusted series"
        ),
    },
}


def _technical_hypothesis(
    strategy_id: str,
    family: str,
    hypothesis: str,
    features: list[str],
    engine_strategy: str,
) -> dict[str, Any]:
    return {
        "strategy_id": strategy_id,
        "hypothesis_family": family,
        "hypothesis": hypothesis,
        "feature_set": features,
        "engine_strategy": engine_strategy,
        "entry_rule": f"{TECHNICAL_RULES[engine_strategy]} (entry-session Close, PIT)",
        "exit_rule": "Close after holding_days sessions (optional fixed SL/TP)",
        "tp_methodology": "NOT_CONFIGURED — fixed holding / optional take_profit_pct",
        "cl_methodology": "NOT_CONFIGURED — optional stop_loss_pct only",
        "parameter_set": {"top_n": 10, "min_turnover_rp": 1_000_000_000},
        "parameter_count": 2,
    }


# Stage-1: one interpretable hypothesis per required family (no parameter explosion).
STAGE1_HYPOTHESES: tuple[dict[str, Any], ...] = (
    {
        "strategy_id": "s1_trend_composite",
        "hypothesis_family": "TREND",
        "hypothesis": (
            "Composite alpha ranking with PIT trend/technical features "
            "identifies relative outperformers over the horizon holding window"
        ),
        "feature_set": ["composite_alpha", "ema_trend", "rsi", "turnover"],
        "engine_strategy": "composite_alpha",
        "entry_rule": "Top-N composite_alpha on entry_date (PIT)",
        "exit_rule": "Close after holding_days sessions (optional fixed SL/TP)",
        "tp_methodology": "NOT_CONFIGURED — fixed holding / optional take_profit_pct",
        "cl_methodology": "NOT_CONFIGURED — optional stop_loss_pct only",
        "parameter_set": {"top_n": 10, "min_turnover_rp": 1_000_000_000},
        "parameter_count": 2,
    },
    _technical_hypothesis(
        "s1_momentum_standalone",
        "MOMENTUM",
        "Top trailing 20-session return among liquid names continues over the holding window",
        ["ret20", "turnover20"],
        "momentum",
    ),
    _technical_hypothesis(
        "s1_breakout_structure",
        "BREAKOUT",
        "Close above the prior 20-session high on expanding volume continues",
        ["prior_high20", "vol_ratio20", "turnover20"],
        "breakout",
    ),
    _technical_hypothesis(
        "s1_pullback_trend",
        "PULLBACK",
        "Oversold RSI pullback inside an EMA20>EMA50 uptrend resumes the trend",
        ["ema20", "ema50", "rsi14", "turnover20"],
        "pullback",
    ),
    _technical_hypothesis(
        "s1_mean_reversion",
        "MEAN_REVERSION",
        "Close below the lower Bollinger band reverts toward the mean",
        ["bb_pctb", "turnover20"],
        "mean_reversion",
    ),
    _technical_hypothesis(
        "s1_volume_expansion",
        "VOLUME_EXPANSION",
        "Volume >= 2x its 20-session average in a bullish EMA regime confirms continuation",
        ["vol_ratio20", "trend_regime", "turnover20"],
        "volume_expansion",
    ),
    {
        "strategy_id": "s1_relative_strength_foreign",
        "hypothesis_family": "RELATIVE_STRENGTH",
        "hypothesis": (
            "Positive foreign net flow ranks as relative-strength proxy for forward holding returns"
        ),
        "feature_set": ["foreign_buy", "foreign_sell", "foreign_net", "turnover"],
        "engine_strategy": "foreign_flow",
        "entry_rule": "Top-N foreign_flow radar on entry_date (PIT)",
        "exit_rule": "Close after holding_days sessions (optional fixed SL/TP)",
        "tp_methodology": "NOT_CONFIGURED — fixed holding / optional take_profit_pct",
        "cl_methodology": "NOT_CONFIGURED — optional stop_loss_pct only",
        "parameter_set": {"top_n": 10, "min_turnover_rp": 1_000_000_000},
        "parameter_count": 2,
    },
)


def list_stage1_hypotheses() -> list[dict[str, Any]]:
    """Return a deep-ish copy of the Stage-1 catalog (mutable-safe for callers)."""
    out: list[dict[str, Any]] = []
    for h in STAGE1_HYPOTHESES:
        item = dict(h)
        item["parameter_set"] = dict(h.get("parameter_set") or {})
        item["feature_set"] = list(h.get("feature_set") or [])
        item["strategy_version"] = STRATEGY_VERSION
        item["feature_version"] = FEATURE_VERSION
        out.append(item)
    return out


def horizon_policy(horizon: str) -> dict[str, Any]:
    return dict(HORIZON_EXECUTION.get(horizon, {}))
