"""RitelInsight Screener production engine package."""

from idx.screener.contract import (
    ENGINE_VERSION,
    MIN_OPPORTUNITY_PCT,
    MIN_RR,
    SETUP_NOT_QUALIFIED,
)
from idx.screener.engine import run_screener
from idx.screener.structure import (
    classify_lifecycle,
    select_dynamic_levels,
)

__all__ = [
    "ENGINE_VERSION",
    "MIN_OPPORTUNITY_PCT",
    "MIN_RR",
    "SETUP_NOT_QUALIFIED",
    "run_screener",
    "classify_lifecycle",
    "select_dynamic_levels",
]
