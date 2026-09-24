"""Signal Discovery candidate contract, horizon taxonomy, and invariants.

Cluster 1 foundation — audit/design/validation helpers only.
Does not run discovery search or alter production screener/backtest paths.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

ENGINE_VERSION = "signal-discovery-4.0"

# ---------------------------------------------------------------------------
# Horizon taxonomy (discovery MUST separate horizons)
# ---------------------------------------------------------------------------

HORIZONS: tuple[str, ...] = (
    "INTRADAY",
    "NEXT_DAY_1_3D",
    "SWING_3_10D",
    "SWING_2_4W",
    "POSITION_1_3M",
    "LONG_TERM_3_12M",
    "MULTIBAGGER_1_5Y",
)

# Explicit map to existing screener TIMEFRAMES (idx.screener.contract.TIMEFRAMES).
# Do not duplicate screener modes; discovery horizons are finer-grained.
SCREENER_TIMEFRAME_TO_HORIZON: dict[str, str] = {
    "close_pressure": "NEXT_DAY_1_3D",
    "swing": "SWING_3_10D",
    "long_term": "LONG_TERM_3_12M",
}

# Reverse: primary screener mode for a discovery horizon (None = no production mode).
HORIZON_TO_SCREENER_TIMEFRAME: dict[str, str | None] = {
    "INTRADAY": None,  # UNAVAILABLE — no tape
    "NEXT_DAY_1_3D": "close_pressure",
    "SWING_3_10D": "swing",
    "SWING_2_4W": "swing",  # same screener engine; different holding/TP-CL contract
    "POSITION_1_3M": None,
    "LONG_TERM_3_12M": "long_term",
    "MULTIBAGGER_1_5Y": "long_term",  # labels CANDIDATE only in production screener
}

# Default holding-session bounds (sessions, not calendar days). Design guidance only.
HORIZON_HOLDING_BOUNDS: dict[str, tuple[int | None, int | None]] = {
    "INTRADAY": (None, None),  # requires intraday bars
    "NEXT_DAY_1_3D": (1, 3),
    "SWING_3_10D": (3, 10),
    "SWING_2_4W": (10, 20),
    "POSITION_1_3M": (20, 63),
    "LONG_TERM_3_12M": (63, 252),
    "MULTIBAGGER_1_5Y": (252, 1260),
}

# ---------------------------------------------------------------------------
# Candidate lifecycle status
# ---------------------------------------------------------------------------

CANDIDATE_STATUSES: tuple[str, ...] = (
    "DISCOVERED",
    "BACKTESTING",
    "VALIDATION",
    "OOS_TESTING",
    "WALK_FORWARD",
    "ROBUSTNESS",
    "CANDIDATE",
    "PRODUCTION_CANDIDATE",
    "REJECTED",
    "INCONCLUSIVE",
    "INSUFFICIENT_DATA",
)

TERMINAL_STATUSES: frozenset[str] = frozenset({"REJECTED", "INCONCLUSIVE", "INSUFFICIENT_DATA"})

# Only these may be considered for production wiring (still not auto-wired).
PRODUCTION_ELIGIBLE_STATUSES: frozenset[str] = frozenset({"PRODUCTION_CANDIDATE"})

# Allowed forward transitions (revalidation restarts from DISCOVERED/BACKTESTING).
ALLOWED_STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    "DISCOVERED": frozenset({"BACKTESTING", "INSUFFICIENT_DATA", "REJECTED", "INCONCLUSIVE"}),
    "BACKTESTING": frozenset({"VALIDATION", "INSUFFICIENT_DATA", "REJECTED", "INCONCLUSIVE"}),
    "VALIDATION": frozenset({"OOS_TESTING", "INSUFFICIENT_DATA", "REJECTED", "INCONCLUSIVE"}),
    "OOS_TESTING": frozenset(
        {"WALK_FORWARD", "ROBUSTNESS", "CANDIDATE", "REJECTED", "INCONCLUSIVE", "INSUFFICIENT_DATA"}
    ),
    "WALK_FORWARD": frozenset(
        {"ROBUSTNESS", "CANDIDATE", "REJECTED", "INCONCLUSIVE", "INSUFFICIENT_DATA"}
    ),
    "ROBUSTNESS": frozenset({"CANDIDATE", "REJECTED", "INCONCLUSIVE", "INSUFFICIENT_DATA"}),
    "CANDIDATE": frozenset(
        {"PRODUCTION_CANDIDATE", "REJECTED", "INCONCLUSIVE", "INSUFFICIENT_DATA"}
    ),
    "PRODUCTION_CANDIDATE": frozenset({"REJECTED", "INCONCLUSIVE"}),
    "REJECTED": frozenset({"DISCOVERED", "BACKTESTING"}),  # only via explicit revalidation
    "INCONCLUSIVE": frozenset({"DISCOVERED", "BACKTESTING"}),
    "INSUFFICIENT_DATA": frozenset({"DISCOVERED", "BACKTESTING"}),
}

# ---------------------------------------------------------------------------
# Staged discovery (no brute-force in Cluster 1)
# ---------------------------------------------------------------------------

DISCOVERY_STAGES: tuple[str, ...] = (
    "STAGE_1_HYPOTHESIS",
    "STAGE_2_PARAMETER_VARIATION",
    "STAGE_3_FEATURE_INTERACTION",
    "STAGE_4_ROBUSTNESS_REGIME",
    "STAGE_5_OOS_WALK_FORWARD",
    "STAGE_6_PRODUCTION_CANDIDATE_GATE",
)

FEATURE_FAMILIES: tuple[str, ...] = (
    "trend",
    "momentum",
    "pullback",
    "breakout",
    "mean_reversion",
    "volatility",
    "volume",
    "relative_strength",
    "foreign_flow",
    "valuation",
    "profitability_quality",
    "liquidity",
    "market_regime",
    "sector_industry",
    "price_structure",
    "cross_sectional_ranking",
    "feature_interactions",
    "event_corporate_action",
)

# ---------------------------------------------------------------------------
# Required lineage / metadata
# ---------------------------------------------------------------------------

REQUIRED_LINEAGE_FIELDS: tuple[str, ...] = (
    "strategy_id",
    "strategy_version",
    "horizon",
    "universe_definition",
    "feature_set",
    "entry_rule",
    "exit_rule",
    "tp_methodology",
    "cl_methodology",
    "minimum_rr",
    "holding_period_limit",
    "signal_timestamp",
    "data_as_of",
    "data_quality",
    "source",
    "engine_version",
    "discovery_method",
    "hypothesis",
    "parameter_set",
    "cost_model",
    "slippage_model",
    "status",
)

MULTIPLE_TESTING_FIELDS: tuple[str, ...] = (
    "hypotheses_tested",
    "candidate_count",
    "parameter_count",
    "selection_rule",
    "discovery_period",
    "validation_period",
    "oos_period",
    "seed",
    "number_of_trials",
    "best_in_sample_result",
    "selected_candidate_result",
    "oos_result",
)

# BUY is never a status fallback — only an explicit entry_rule outcome.
BUY_SIGNAL_LABEL = "BUY"
NON_BUY_FALLBACK_STATUSES: frozenset[str] = frozenset(
    {"INSUFFICIENT_DATA", "INCONCLUSIVE", "REJECTED", "DISCOVERED"}
)


class CandidateValidationError(ValueError):
    """Raised when a discovery candidate violates contract invariants."""


def is_valid_horizon(horizon: str | None) -> bool:
    return horizon in HORIZONS


def is_valid_status(status: str | None) -> bool:
    return status in CANDIDATE_STATUSES


def empty_multiple_testing_record() -> dict[str, Any]:
    """Null-safe multiple-testing metadata — no fabricated significance."""
    return {k: None for k in MULTIPLE_TESTING_FIELDS} | {
        "statistical_significance_claimed": False,
        "notes": "Significance not computed unless an explicit test is run and recorded.",
    }


def _parse_ts(value: Any) -> datetime | date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            if "T" in s or " " in s:
                return datetime.fromisoformat(s.replace("Z", "+00:00"))
            return date.fromisoformat(s[:10])
        except ValueError:
            return None
    return None


def _as_comparable(value: datetime | date) -> date:
    if isinstance(value, datetime):
        return value.date()
    return value


def assert_signal_as_of_ordering(
    signal_timestamp: Any,
    data_as_of: Any,
    *,
    raise_error: bool = True,
) -> bool:
    """data_as_of must be on or before signal_timestamp (no future data at signal)."""
    sig = _parse_ts(signal_timestamp)
    as_of = _parse_ts(data_as_of)
    if sig is None or as_of is None:
        if raise_error:
            raise CandidateValidationError(
                "signal_timestamp and data_as_of must be parseable timestamps/dates"
            )
        return False
    ok = _as_comparable(as_of) <= _as_comparable(sig)
    if not ok and raise_error:
        raise CandidateValidationError(
            f"data_as_of ({data_as_of}) must be <= signal_timestamp ({signal_timestamp})"
        )
    return ok


def assert_no_future_feature(
    feature_as_of: Any,
    signal_timestamp: Any,
    *,
    feature_name: str = "feature",
    raise_error: bool = True,
) -> bool:
    """Feature availability timestamp must not exceed signal timestamp."""
    feat = _parse_ts(feature_as_of)
    sig = _parse_ts(signal_timestamp)
    if feat is None or sig is None:
        if raise_error:
            raise CandidateValidationError(
                f"{feature_name}: feature_as_of and signal_timestamp must be parseable"
            )
        return False
    ok = _as_comparable(feat) <= _as_comparable(sig)
    if not ok and raise_error:
        raise CandidateValidationError(
            f"Future feature forbidden: {feature_name} as_of={feature_as_of} "
            f"> signal_timestamp={signal_timestamp}"
        )
    return ok


def assert_buy_not_from_insufficient_data(
    status: str | None,
    signal_label: str | None,
    *,
    raise_error: bool = True,
) -> bool:
    """INSUFFICIENT_DATA / INCONCLUSIVE / REJECTED must never coerce to BUY."""
    if status in NON_BUY_FALLBACK_STATUSES and signal_label == BUY_SIGNAL_LABEL:
        if raise_error:
            raise CandidateValidationError(
                f"status={status} cannot emit BUY — use INSUFFICIENT_DATA/INCONCLUSIVE/REJECTED"
            )
        return False
    return True


def assert_production_eligibility(
    status: str | None,
    *,
    has_oos: bool,
    oos_status: str | None = None,
    raise_error: bool = True,
) -> bool:
    """PRODUCTION_CANDIDATE requires completed OOS; cannot bypass OOS gate."""
    if status != "PRODUCTION_CANDIDATE":
        return True
    oos_ok = has_oos and (oos_status in (None, "OK", "PASSED"))
    if not oos_ok:
        if raise_error:
            raise CandidateValidationError(
                "PRODUCTION_CANDIDATE requires successful OOS (has_oos=True); "
                "cannot bypass OOS gate"
            )
        return False
    return True


def assert_rejected_cannot_skip_to_production(
    previous_status: str | None,
    new_status: str | None,
    *,
    raise_error: bool = True,
) -> bool:
    """REJECTED → PRODUCTION_CANDIDATE without revalidation is forbidden."""
    if previous_status == "REJECTED" and new_status == "PRODUCTION_CANDIDATE":
        if raise_error:
            raise CandidateValidationError(
                "REJECTED cannot become PRODUCTION_CANDIDATE without revalidation "
                "(restart via DISCOVERED/BACKTESTING)"
            )
        return False
    return True


def assert_status_transition(
    previous_status: str | None,
    new_status: str | None,
    *,
    raise_error: bool = True,
) -> bool:
    if not is_valid_status(new_status):
        if raise_error:
            raise CandidateValidationError(f"Invalid status: {new_status!r}")
        return False
    if previous_status is None:
        return True
    if not is_valid_status(previous_status):
        if raise_error:
            raise CandidateValidationError(f"Invalid previous status: {previous_status!r}")
        return False
    if not assert_rejected_cannot_skip_to_production(
        previous_status, new_status, raise_error=raise_error
    ):
        return False
    allowed = ALLOWED_STATUS_TRANSITIONS.get(previous_status, frozenset())
    if new_status not in allowed:
        if raise_error:
            raise CandidateValidationError(
                f"Illegal status transition {previous_status} → {new_status}"
            )
        return False
    return True


def validate_candidate_metadata(
    meta: Mapping[str, Any],
    *,
    previous_status: str | None = None,
    has_oos: bool = False,
    oos_status: str | None = None,
    feature_as_of_map: Mapping[str, Any] | None = None,
) -> list[str]:
    """Validate candidate contract; return list of error strings (empty = ok)."""
    errors: list[str] = []

    for field in REQUIRED_LINEAGE_FIELDS:
        if field not in meta or meta[field] is None or meta[field] == "":
            errors.append(f"missing required field: {field}")

    horizon = meta.get("horizon")
    if horizon is not None and not is_valid_horizon(str(horizon)):
        errors.append(f"invalid horizon: {horizon!r}")

    status = meta.get("status")
    if status is not None and not is_valid_status(str(status)):
        errors.append(f"invalid status: {status!r}")

    try:
        assert_signal_as_of_ordering(meta.get("signal_timestamp"), meta.get("data_as_of"))
    except CandidateValidationError as exc:
        errors.append(str(exc))

    if feature_as_of_map:
        for name, feat_as_of in feature_as_of_map.items():
            try:
                assert_no_future_feature(
                    feat_as_of, meta.get("signal_timestamp"), feature_name=str(name)
                )
            except CandidateValidationError as exc:
                errors.append(str(exc))

    try:
        assert_buy_not_from_insufficient_data(
            str(status) if status is not None else None,
            meta.get("signal") or meta.get("signal_label"),
        )
    except CandidateValidationError as exc:
        errors.append(str(exc))

    try:
        assert_production_eligibility(
            str(status) if status is not None else None,
            has_oos=has_oos,
            oos_status=oos_status,
        )
    except CandidateValidationError as exc:
        errors.append(str(exc))

    if previous_status is not None and status is not None:
        try:
            assert_status_transition(str(previous_status), str(status))
        except CandidateValidationError as exc:
            errors.append(str(exc))

    # Cost/slippage honesty: unknown models must be explicit, not silent zeros.
    for model_key in ("cost_model", "slippage_model"):
        val = meta.get(model_key)
        if val is not None and str(val).strip().upper() in ("0", "ZERO", "NONE"):
            # Explicit NONE/UNAVAILABLE is OK; bare "0" without model name is ambiguous.
            if str(val).strip().upper() == "0":
                errors.append(f"{model_key}='0' is ambiguous — use 'UNAVAILABLE' or a named model")

    return errors
