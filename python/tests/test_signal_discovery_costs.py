"""Cluster 4 — cost / slippage model contracts."""

from __future__ import annotations

import pandas as pd
import pytest

from idx.signal_discovery.costs import (
    COST_STATUS_CONFIGURED,
    NOT_CONFIGURED_COST_MODEL,
    NOT_CONFIGURED_SLIPPAGE_MODEL,
    CostModel,
    CostModelError,
    SlippageModel,
    illustrative_cost_model,
    illustrative_slippage_model,
    net_return_from_gross,
    net_trade_summary,
    personal_operator_cost_model,
    personal_operator_slippage_model,
    return_semantics,
    round_trip_cost_pct,
)


def _illustrative():
    return (
        illustrative_cost_model(buy_fee_bps=15, sell_fee_bps=25, label="stress"),
        illustrative_slippage_model(per_side_bps=10, label="stress"),
    )


def test_not_configured_defaults_carry_no_values():
    assert NOT_CONFIGURED_COST_MODEL.buy_fee_bps is None
    assert NOT_CONFIGURED_COST_MODEL.sell_fee_bps is None
    assert NOT_CONFIGURED_SLIPPAGE_MODEL.per_side_bps is None
    with pytest.raises(CostModelError):
        CostModel(model_id="x", status="NOT_CONFIGURED", buy_fee_bps=10)


def test_not_configured_means_net_not_available():
    sem = return_semantics(NOT_CONFIGURED_COST_MODEL, NOT_CONFIGURED_SLIPPAGE_MODEL)
    assert sem["net_return_status"] == "NOT_AVAILABLE"
    assert sem["return_is_net_tradable"] is False
    assert (
        net_return_from_gross(0.05, NOT_CONFIGURED_COST_MODEL, NOT_CONFIGURED_SLIPPAGE_MODEL)
        is None
    )
    assert round_trip_cost_pct(NOT_CONFIGURED_COST_MODEL, NOT_CONFIGURED_SLIPPAGE_MODEL) is None


def test_partial_configuration_still_not_available():
    cost, _ = _illustrative()
    sem = return_semantics(cost, NOT_CONFIGURED_SLIPPAGE_MODEL)
    assert sem["net_return_status"] == "NOT_AVAILABLE"
    assert net_return_from_gross(0.05, cost, NOT_CONFIGURED_SLIPPAGE_MODEL) is None


def test_illustrative_is_labelled_and_never_net_tradable():
    cost, slip = _illustrative()
    assert "ILLUSTRATIVE" in cost.notes
    sem = return_semantics(cost, slip)
    assert sem["net_return_status"] == "RESEARCH_ILLUSTRATIVE"
    assert sem["return_is_net_tradable"] is False


def test_configured_requires_provenance():
    with pytest.raises(CostModelError, match="source and as_of"):
        CostModel(model_id="broker", status=COST_STATUS_CONFIGURED, buy_fee_bps=10, sell_fee_bps=20)
    with pytest.raises(CostModelError, match="source and as_of"):
        SlippageModel(model_id="fills", status=COST_STATUS_CONFIGURED, per_side_bps=5, source="x")
    cost = CostModel(
        model_id="broker",
        status=COST_STATUS_CONFIGURED,
        buy_fee_bps=10,
        sell_fee_bps=20,
        source="contract",
        as_of="2026-09-01",
    )
    slip = SlippageModel(
        model_id="fills",
        status=COST_STATUS_CONFIGURED,
        per_side_bps=5,
        source="tca",
        as_of="2026-09-01",
    )
    assert return_semantics(cost, slip)["return_is_net_tradable"] is True


def test_invalid_values_rejected():
    with pytest.raises(CostModelError):
        illustrative_cost_model(buy_fee_bps=-1, sell_fee_bps=10, label="bad")
    with pytest.raises(CostModelError):
        illustrative_slippage_model(per_side_bps=float("nan"), label="bad")
    with pytest.raises(CostModelError):
        CostModel(model_id="x", status="MADE_UP", buy_fee_bps=1, sell_fee_bps=1)


def test_net_return_is_exact_multiplicative():
    cost, slip = _illustrative()
    # buy side = 25 bps, sell side = 35 bps
    expected = 1.10 * (1 - 0.0035) / (1 + 0.0025) - 1
    assert net_return_from_gross(0.10, cost, slip) == pytest.approx(expected)
    rt = round_trip_cost_pct(cost, slip)
    assert rt == pytest.approx((1 - (1 - 0.0035) / 1.0025) * 100, rel=1e-6)
    assert 0.59 < rt < 0.60


def test_net_trade_summary_gross_vs_net():
    cost, slip = _illustrative()
    trades = pd.DataFrame({"Return": [0.004, 0.02, -0.01]})
    out = net_trade_summary(trades, cost, slip)
    assert out["ledger_status"] == "OK"
    assert out["sample_count"] == 3
    assert out["gross_win_rate_pct"] == pytest.approx(66.67)
    assert out["net_expectancy_pct"] < out["gross_expectancy_pct"]
    # the +0.4% trade loses after ~0.6% round-trip drag
    assert out["net_win_rate_pct"] == pytest.approx(33.33)


def test_net_trade_summary_without_models_or_ledger():
    trades = pd.DataFrame({"Return": [0.01, 0.02]})
    out = net_trade_summary(trades, NOT_CONFIGURED_COST_MODEL, NOT_CONFIGURED_SLIPPAGE_MODEL)
    assert out["gross_expectancy_pct"] == pytest.approx(1.5)
    assert out["net_expectancy_pct"] is None
    assert out["net_win_rate_pct"] is None
    empty = net_trade_summary(None, *_illustrative())
    assert empty["ledger_status"] == "NO_TRADE_LEDGER"
    assert empty["gross_expectancy_pct"] is None
    assert empty["sample_count"] == 0


def test_personal_operator_models_are_configured_with_provenance():
    cost = personal_operator_cost_model()
    slip = personal_operator_slippage_model()
    assert cost.status == COST_STATUS_CONFIGURED
    assert slip.status == COST_STATUS_CONFIGURED
    assert cost.buy_fee_bps == 15.0
    assert cost.sell_fee_bps == 25.0
    assert cost.source and cost.as_of
    assert slip.source and slip.as_of
    sem = return_semantics(cost, slip)
    assert sem["return_is_net_tradable"] is True
    assert sem["net_return_status"] == "AVAILABLE"
