"""Survivorship policy + observational universe audit (Cluster 4).

Data observation can never produce ``VERIFIED`` evidence; verification must be
declared explicitly with ``verified_by`` + ``source``. Without that, the policy
stays ``NOT_VALIDATED``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from idx.core.price_adjustment import DELISTING_ACTION_TYPES, PRICE_DISTORTING_ACTION_TYPES

SURVIVORSHIP_SAFE = "SURVIVORSHIP_SAFE"
SURVIVORSHIP_PARTIAL = "SURVIVORSHIP_PARTIAL"
SURVIVORSHIP_NOT_VALIDATED = "NOT_VALIDATED"

SURVIVORSHIP_STATUSES: tuple[str, ...] = (
    SURVIVORSHIP_SAFE,
    SURVIVORSHIP_PARTIAL,
    SURVIVORSHIP_NOT_VALIDATED,
)

EVIDENCE_VERIFIED = "VERIFIED"
EVIDENCE_OBSERVED_UNVERIFIED = "OBSERVED_UNVERIFIED"
EVIDENCE_NOT_AVAILABLE = "NOT_AVAILABLE"

EVIDENCE_STATES: tuple[str, ...] = (
    EVIDENCE_VERIFIED,
    EVIDENCE_OBSERVED_UNVERIFIED,
    EVIDENCE_NOT_AVAILABLE,
)

SURVIVORSHIP_COMPONENTS: tuple[str, ...] = (
    "point_in_time_universe",
    "delisted_companies",
    "suspended_companies",
    "historical_index_constituents",
    "ticker_changes",
    "corporate_action_price_adjustment",
)

SURVIVORSHIP_RULE = (
    "SURVIVORSHIP_SAFE: every component VERIFIED. "
    "SURVIVORSHIP_PARTIAL: point_in_time_universe VERIFIED plus >=1 other component VERIFIED. "
    "Otherwise NOT_VALIDATED. Observation alone is never verification."
)

_AUDIT_SAMPLE_CAP = 20


class SurvivorshipPolicyError(ValueError):
    """Invalid survivorship evidence declaration."""


def evaluate_survivorship_policy(
    evidence: Mapping[str, str],
    *,
    verified_by: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """Map per-component evidence to a survivorship status (explicit rule)."""
    unknown = sorted(set(evidence) - set(SURVIVORSHIP_COMPONENTS))
    if unknown:
        raise SurvivorshipPolicyError(f"unknown survivorship components: {unknown}")

    components: dict[str, str] = {}
    for name in SURVIVORSHIP_COMPONENTS:
        state = evidence.get(name, EVIDENCE_NOT_AVAILABLE)
        if state not in EVIDENCE_STATES:
            raise SurvivorshipPolicyError(f"{name}: invalid evidence state {state!r}")
        components[name] = state

    if EVIDENCE_VERIFIED in components.values() and not (
        (verified_by or "").strip() and (source or "").strip()
    ):
        raise SurvivorshipPolicyError("VERIFIED evidence requires non-empty verified_by and source")

    verified = [k for k, v in components.items() if v == EVIDENCE_VERIFIED]
    if len(verified) == len(SURVIVORSHIP_COMPONENTS):
        status = SURVIVORSHIP_SAFE
    elif "point_in_time_universe" in verified and len(verified) >= 2:
        status = SURVIVORSHIP_PARTIAL
    else:
        status = SURVIVORSHIP_NOT_VALIDATED

    return {
        "survivorship_status": status,
        "components": components,
        "unverified_components": [k for k, v in components.items() if v != EVIDENCE_VERIFIED],
        "rule": SURVIVORSHIP_RULE,
        "verified_by": verified_by if verified else None,
        "source": source if verified else None,
    }


def audit_survivorship_evidence(
    stock_df: pd.DataFrame,
    actions_df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Observational audit of the price universe (``Date``/``StockCode``) and corporate actions.

    Reports what the data shows; never upgrades any component to VERIFIED.
    """
    observations: dict[str, Any] = {
        "date_range": None,
        "ticker_count": 0,
        "tickers_last_seen_before_end": 0,
        "tickers_last_seen_before_end_sample": [],
        "tickers_first_seen_after_start": 0,
        "corporate_actions_in_range": {},
        "price_distorting_events_in_range": 0,
        "full_delisting_records_in_range": 0,
    }
    evidence = {name: EVIDENCE_NOT_AVAILABLE for name in SURVIVORSHIP_COMPONENTS}
    notes: list[str] = []

    if stock_df is None or len(stock_df) == 0 or not {"Date", "StockCode"} <= set(stock_df.columns):
        notes.append("No price universe supplied — nothing observable.")
        return _audit_result(observations, evidence, notes)

    prices = stock_df[["Date", "StockCode"]].copy()
    prices["Date"] = pd.to_datetime(prices["Date"], errors="coerce")
    prices = prices.dropna()
    if prices.empty:
        notes.append("Price universe has no valid dates.")
        return _audit_result(observations, evidence, notes)

    start, end = prices["Date"].min(), prices["Date"].max()
    spans = prices.groupby("StockCode")["Date"].agg(["min", "max"])
    gone = sorted(spans.index[spans["max"] < end].astype(str))
    observations.update(
        {
            "date_range": {"start": start.strftime("%Y-%m-%d"), "end": end.strftime("%Y-%m-%d")},
            "ticker_count": int(len(spans)),
            "tickers_last_seen_before_end": len(gone),
            "tickers_last_seen_before_end_sample": gone[:_AUDIT_SAMPLE_CAP],
            "tickers_first_seen_after_start": int((spans["min"] > start).sum()),
        }
    )
    if gone:
        evidence["point_in_time_universe"] = EVIDENCE_OBSERVED_UNVERIFIED
        notes.append(
            f"{len(gone)} tickers disappear before the dataset end — consistent with retention of "
            "exited names, but cause (delisting/suspension/code change/scrape gap) is unknown."
        )
    else:
        notes.append(
            "No ticker disappears before dataset end — cannot evidence exited-name retention."
        )

    if actions_df is not None and {"TanggalPencatatan", "caType"} <= set(actions_df.columns):
        acts = actions_df[["TanggalPencatatan", "caType"]].copy()
        acts["TanggalPencatatan"] = pd.to_datetime(acts["TanggalPencatatan"], errors="coerce")
        acts = acts[(acts["TanggalPencatatan"] >= start) & (acts["TanggalPencatatan"] <= end)]
        by_type = acts["caType"].astype(str).value_counts().sort_index()
        observations["corporate_actions_in_range"] = {k: int(v) for k, v in by_type.items()}
        distorting = int(by_type[by_type.index.isin(PRICE_DISTORTING_ACTION_TYPES)].sum())
        delist = int(by_type[by_type.index.isin(DELISTING_ACTION_TYPES)].sum())
        observations["price_distorting_events_in_range"] = distorting
        observations["full_delisting_records_in_range"] = delist
        if delist:
            evidence["delisted_companies"] = EVIDENCE_OBSERVED_UNVERIFIED
        if distorting:
            notes.append(
                f"{distorting} share-count/price-basis events in range; engine forward-adjusts "
                "via exchange reference and excludes trades whose hold spans a distorting event."
            )
    else:
        notes.append("No corporate actions supplied — adjustment risk not assessed.")

    notes.append(
        "No suspension registry, ticker-change map or historical index constituents available."
    )
    return _audit_result(observations, evidence, notes)


def _audit_result(
    observations: dict[str, Any],
    evidence: dict[str, str],
    notes: list[str],
) -> dict[str, Any]:
    policy = evaluate_survivorship_policy(evidence)
    return {
        "audit_basis": "OBSERVATIONAL — does not verify universe completeness",
        "observations": observations,
        "evidence": evidence,
        "policy": policy,
        "survivorship_status": policy["survivorship_status"],
        "notes": notes,
    }
