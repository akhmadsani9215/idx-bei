"""Screener production result contract.

Nullable fields are preferred over fabricated values.
Compatible field names reused from existing codebase where possible.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

ENGINE_VERSION = "screener-1.0"

# Close Pressure product threshold: minimum opportunity filter, NOT a fixed TP.
MIN_OPPORTUNITY_PCT = 3.0

# Risk/reward gate for qualified setups.
MIN_RR = 2.0

# Historical sample gate — below this, stats are Insufficient Sample.
MIN_HISTORICAL_SAMPLE = 30

SETUP_NOT_QUALIFIED = "NOT_QUALIFIED"
STATUS_PARTIAL = "PARTIAL"
STATUS_UNAVAILABLE = "UNAVAILABLE"
STATUS_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
STATUS_INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"

TIMEFRAMES = ("close_pressure", "swing", "long_term")

# No screener setup has passed OOS + walk-forward + robustness + cost + multiple-testing
# validation (see docs/SIGNAL_DISCOVERY_STUDY.md); rows are decision support only.
PRODUCTION_ELIGIBILITY_STATUS = "NOT_VALIDATED"
PRODUCTION_ELIGIBILITY_REASON = (
    "Setup rules not validated OOS/walk-forward with configured costs; survivorship "
    "NOT_VALIDATED; historical stats are per-ticker descriptive only."
)

LIFECYCLE_STATES = (
    "DORMANT",
    "EARLY_ACTIVITY",
    "ACCUMULATION",
    "ACTIVE",
    "BREAKOUT",
    "EXPANSION",
    "UNKNOWN",
    "UNAVAILABLE",
)

DATA_QUALITY_GRADES = {
    "A": "REAL_INTRADAY",
    "B": "REAL_DAILY_COMPLETE",
    "C": "DERIVED",
    "D": "PROXY",
    "E": "EOD_SNAPSHOT_ONLY",
    "U": "UNAVAILABLE",
}


def empty_levels() -> dict[str, Any]:
    return {
        "entry_zone": None,
        "tp1": None,
        "tp2": None,
        "tp3": None,
        "cl1": None,
        "cl2": None,
        "cl3": None,
        "rr1": None,
        "rr2": None,
        "rr3": None,
        "tp1_source": None,
        "tp2_source": None,
        "tp3_source": None,
        "cl1_source": None,
        "cl2_source": None,
        "cl3_source": None,
        "entry_source": None,
    }


def empty_historical_stats() -> dict[str, Any]:
    return {
        "historical_tp_probability": None,
        "historical_cl_probability": None,
        "median_days": None,
        "mfe": None,
        "mae": None,
        "sample_size": 0,
        "stats_status": STATUS_UNAVAILABLE,
        "stats_note": "No historical sample computed.",
    }


def empty_lineage(
    *,
    source: str | None = None,
    as_of: str | None = None,
    quality: str = "U",
    confidence: float | None = None,
) -> dict[str, Any]:
    return {
        "source": source,
        "as_of": as_of,
        "quality": quality,
        "data_quality": quality,
        "confidence": confidence,
        "calculated_at": datetime.now(UTC).isoformat(),
        "engine_version": ENGINE_VERSION,
    }


def base_result(
    *,
    ticker: str,
    company: str | None = None,
    timeframe: str = "close_pressure",
) -> dict[str, Any]:
    """Canonical screener row with null-safe defaults."""
    levels = empty_levels()
    hist = empty_historical_stats()
    lineage = empty_lineage()
    return {
        "ticker": ticker.upper().strip(),
        "company": company,
        "price": None,
        "change": None,
        "change_pct": None,
        "volume": None,
        "value": None,
        "setup": SETUP_NOT_QUALIFIED,
        "signal": None,
        "engine_score": None,
        "trend": None,
        "pressure": None,
        "foreign": None,
        "liquidity": None,
        "lifecycle": "UNKNOWN",
        "timeframe": timeframe,
        **levels,
        **hist,
        "data_quality": "U",
        "source": None,
        "as_of": None,
        "confidence": None,
        "why_signal": None,
        "status": STATUS_UNAVAILABLE,
        "lineage": lineage,
        "engine_version": ENGINE_VERSION,
        "production_eligibility": PRODUCTION_ELIGIBILITY_STATUS,
        "production_eligibility_reason": PRODUCTION_ELIGIBILITY_REASON,
    }


def null_if_nan(value: Any) -> Any:
    """Convert NaN/Inf to None for JSON-safe contracts."""
    try:
        import math

        if value is None:
            return None
        if isinstance(value, (float, int)):
            f = float(value)
            if math.isnan(f) or math.isinf(f):
                return None
            return f if isinstance(value, float) else value
        return value
    except (TypeError, ValueError):
        return None


def sanitize_result(row: dict[str, Any]) -> dict[str, Any]:
    """Ensure numeric fields are JSON-safe nulls when missing/invalid."""
    out = dict(row)
    numeric_keys = (
        "price",
        "change",
        "change_pct",
        "volume",
        "value",
        "engine_score",
        "pressure",
        "foreign",
        "liquidity",
        "entry_zone",
        "tp1",
        "tp2",
        "tp3",
        "cl1",
        "cl2",
        "cl3",
        "rr1",
        "rr2",
        "rr3",
        "historical_tp_probability",
        "historical_cl_probability",
        "median_days",
        "mfe",
        "mae",
        "confidence",
    )
    for key in numeric_keys:
        if key in out:
            out[key] = null_if_nan(out[key])
    if "sample_size" in out:
        ss = out["sample_size"]
        try:
            out["sample_size"] = int(ss) if ss is not None else 0
        except (TypeError, ValueError):
            out["sample_size"] = 0
    return out
