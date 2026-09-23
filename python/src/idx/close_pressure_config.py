"""
Close Pressure Engine configuration.

Time windows are INTERNAL screener criteria.
They are intentionally not exposed as dashboard columns.
"""

from dataclasses import dataclass
from datetime import time


@dataclass(frozen=True)
class ClosePressureWindow:
    watch_start: time = time(14, 30)
    pressure_start: time = time(15, 0)
    primary_start: time = time(15, 30)
    primary_end: time = time(15, 50)
    preclose_start: time = time(15, 50)
    preclose_end: time = time(16, 0)
    closing_match_start: time = time(16, 0)
    closing_match_end: time = time(16, 2)

    # Next-session validation.
    next_open_check_start: time = time(8, 45)
    next_open_check_end: time = time(9, 0)


WINDOW = ClosePressureWindow()


def classify_time_window(t: time) -> str:
    """Return the internal CPE phase for a Jakarta market timestamp."""

    if WINDOW.watch_start <= t < WINDOW.pressure_start:
        return "WATCH"

    if WINDOW.pressure_start <= t < WINDOW.primary_start:
        return "PRESSURE_BUILDING"

    if WINDOW.primary_start <= t < WINDOW.primary_end:
        return "PRIMARY_SIGNAL"

    if WINDOW.preclose_start <= t < WINDOW.preclose_end:
        return "PRE_CLOSING"

    if WINDOW.closing_match_start <= t < WINDOW.closing_match_end:
        return "CLOSING_MATCH"

    return "OUTSIDE"


def is_primary_signal_time(t: time) -> bool:
    return WINDOW.primary_start <= t < WINDOW.primary_end


def is_preclosing_time(t: time) -> bool:
    return WINDOW.preclose_start <= t < WINDOW.preclose_end


def is_close_entry_time(t: time) -> bool:
    return is_primary_signal_time(t) or is_preclosing_time(t)
