"""Cluster 4 — survivorship policy + observational audit."""

from __future__ import annotations

import pandas as pd
import pytest

from idx.signal_discovery.survivorship import (
    EVIDENCE_NOT_AVAILABLE,
    EVIDENCE_OBSERVED_UNVERIFIED,
    EVIDENCE_VERIFIED,
    SURVIVORSHIP_COMPONENTS,
    SurvivorshipPolicyError,
    audit_survivorship_evidence,
    evaluate_survivorship_policy,
)


def _all(state: str) -> dict[str, str]:
    return {k: state for k in SURVIVORSHIP_COMPONENTS}


def test_default_is_not_validated():
    out = evaluate_survivorship_policy({})
    assert out["survivorship_status"] == "NOT_VALIDATED"
    assert set(out["unverified_components"]) == set(SURVIVORSHIP_COMPONENTS)


def test_observed_evidence_never_upgrades_status():
    out = evaluate_survivorship_policy(_all(EVIDENCE_OBSERVED_UNVERIFIED))
    assert out["survivorship_status"] == "NOT_VALIDATED"


def test_verified_requires_provenance():
    with pytest.raises(SurvivorshipPolicyError, match="verified_by"):
        evaluate_survivorship_policy({"point_in_time_universe": EVIDENCE_VERIFIED})


def test_safe_requires_every_component_verified():
    out = evaluate_survivorship_policy(
        _all(EVIDENCE_VERIFIED), verified_by="auditor", source="vendor"
    )
    assert out["survivorship_status"] == "SURVIVORSHIP_SAFE"
    missing_one = _all(EVIDENCE_VERIFIED) | {"ticker_changes": EVIDENCE_NOT_AVAILABLE}
    out = evaluate_survivorship_policy(missing_one, verified_by="auditor", source="vendor")
    assert out["survivorship_status"] == "SURVIVORSHIP_PARTIAL"


def test_partial_requires_point_in_time_universe():
    ev = {"ticker_changes": EVIDENCE_VERIFIED, "delisted_companies": EVIDENCE_VERIFIED}
    out = evaluate_survivorship_policy(ev, verified_by="a", source="s")
    assert out["survivorship_status"] == "NOT_VALIDATED"
    only_pit = {"point_in_time_universe": EVIDENCE_VERIFIED}
    out = evaluate_survivorship_policy(only_pit, verified_by="a", source="s")
    assert out["survivorship_status"] == "NOT_VALIDATED"


def test_unknown_component_or_state_rejected():
    with pytest.raises(SurvivorshipPolicyError):
        evaluate_survivorship_policy({"made_up": EVIDENCE_VERIFIED})
    with pytest.raises(SurvivorshipPolicyError):
        evaluate_survivorship_policy({"ticker_changes": "PROBABLY"})


def test_audit_observes_but_stays_not_validated():
    stock = pd.DataFrame(
        {
            "Date": [
                "2025-01-02",
                "2025-01-03",
                "2025-01-02",
                "2025-01-02",
                "2025-01-03",
                "2025-01-03",
            ],
            "StockCode": ["AAAA", "AAAA", "GONE", "BBBB", "BBBB", "NEWW"],
        }
    )
    actions = pd.DataFrame(
        {
            "KodeEmiten": ["AAAA", "BBBB", "CCCC", "OLD1"],
            "TanggalPencatatan": ["2025-01-02", "2025-01-03", "2025-01-03", "2020-01-01"],
            "caType": ["stockSplit", "partialDelisting", "ipo", "stockSplit"],
        }
    )
    out = audit_survivorship_evidence(stock, actions)
    obs = out["observations"]
    assert out["survivorship_status"] == "NOT_VALIDATED"
    assert obs["tickers_last_seen_before_end"] == 1
    assert obs["tickers_last_seen_before_end_sample"] == ["GONE"]
    assert obs["tickers_first_seen_after_start"] == 1
    assert obs["price_distorting_events_in_range"] == 1  # out-of-range split excluded
    assert obs["full_delisting_records_in_range"] == 0  # partialDelisting is not delisting
    assert out["evidence"]["point_in_time_universe"] == EVIDENCE_OBSERVED_UNVERIFIED
    assert out["evidence"]["delisted_companies"] == EVIDENCE_NOT_AVAILABLE
    assert EVIDENCE_VERIFIED not in out["evidence"].values()


def test_audit_empty_input():
    out = audit_survivorship_evidence(pd.DataFrame())
    assert out["survivorship_status"] == "NOT_VALIDATED"
    assert out["observations"]["ticker_count"] == 0
