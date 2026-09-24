"""Cost / slippage model contracts for Signal Discovery (Cluster 4).

No IDX fee schedule and no measured slippage ship with this module. Models are
either ``NOT_CONFIGURED`` (net return unavailable), ``RESEARCH_ILLUSTRATIVE``
(caller-supplied stress assumption, never net tradable), or ``CONFIGURED``
(caller-supplied with explicit ``source`` + ``as_of``).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

COST_STATUS_NOT_CONFIGURED = "NOT_CONFIGURED"
COST_STATUS_ILLUSTRATIVE = "RESEARCH_ILLUSTRATIVE"
COST_STATUS_CONFIGURED = "CONFIGURED"

COST_MODEL_STATUSES: tuple[str, ...] = (
    COST_STATUS_NOT_CONFIGURED,
    COST_STATUS_ILLUSTRATIVE,
    COST_STATUS_CONFIGURED,
)

ILLUSTRATIVE_NOTE = (
    "RESEARCH/ILLUSTRATIVE stress assumption — not an IDX fee schedule or measured fill"
)
EXECUTION_FEASIBILITY_NOTE = "NOT_MODELED — lot size, auto-rejection limits, liquidity/market impact and fill probability ignored"

# Ledger contract of idx.backtest.run_backtest: ``Return`` is a fraction.
LEDGER_RETURN_COLUMN = "Return"


class CostModelError(ValueError):
    """Invalid cost / slippage model definition."""


def _check_bps(name: str, value: float | None) -> None:
    if value is None:
        raise CostModelError(f"{name} is required for configured/illustrative models")
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value < 0:
        raise CostModelError(f"{name} must be a finite non-negative number, got {value!r}")


def _check_provenance(status: str, source: str | None, as_of: str | None) -> None:
    if status == COST_STATUS_CONFIGURED and (
        not (source or "").strip() or not (as_of or "").strip()
    ):
        raise CostModelError("CONFIGURED models require non-empty source and as_of")


@dataclass(frozen=True)
class CostModel:
    """Per-side proportional fees in basis points (sell side includes any sell tax)."""

    model_id: str
    status: str
    buy_fee_bps: float | None = None
    sell_fee_bps: float | None = None
    source: str | None = None
    as_of: str | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if self.status not in COST_MODEL_STATUSES:
            raise CostModelError(f"invalid cost model status: {self.status!r}")
        if self.status == COST_STATUS_NOT_CONFIGURED:
            if self.buy_fee_bps is not None or self.sell_fee_bps is not None:
                raise CostModelError("NOT_CONFIGURED cost model must not carry fee values")
            return
        _check_bps("buy_fee_bps", self.buy_fee_bps)
        _check_bps("sell_fee_bps", self.sell_fee_bps)
        _check_provenance(self.status, self.source, self.as_of)

    @property
    def is_applicable(self) -> bool:
        return self.status != COST_STATUS_NOT_CONFIGURED

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SlippageModel:
    """Symmetric per-side slippage in basis points of the fill price."""

    model_id: str
    status: str
    per_side_bps: float | None = None
    source: str | None = None
    as_of: str | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if self.status not in COST_MODEL_STATUSES:
            raise CostModelError(f"invalid slippage model status: {self.status!r}")
        if self.status == COST_STATUS_NOT_CONFIGURED:
            if self.per_side_bps is not None:
                raise CostModelError("NOT_CONFIGURED slippage model must not carry values")
            return
        _check_bps("per_side_bps", self.per_side_bps)
        _check_provenance(self.status, self.source, self.as_of)

    @property
    def is_applicable(self) -> bool:
        return self.status != COST_STATUS_NOT_CONFIGURED

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


NOT_CONFIGURED_COST_MODEL = CostModel(model_id="NOT_CONFIGURED", status=COST_STATUS_NOT_CONFIGURED)
NOT_CONFIGURED_SLIPPAGE_MODEL = SlippageModel(
    model_id="NOT_CONFIGURED", status=COST_STATUS_NOT_CONFIGURED
)


def illustrative_cost_model(*, buy_fee_bps: float, sell_fee_bps: float, label: str) -> CostModel:
    """Caller-chosen stress assumption. Values are never defaulted here."""
    return CostModel(
        model_id=f"illustrative:{label}",
        status=COST_STATUS_ILLUSTRATIVE,
        buy_fee_bps=buy_fee_bps,
        sell_fee_bps=sell_fee_bps,
        notes=ILLUSTRATIVE_NOTE,
    )


def illustrative_slippage_model(*, per_side_bps: float, label: str) -> SlippageModel:
    """Caller-chosen stress assumption. Values are never defaulted here."""
    return SlippageModel(
        model_id=f"illustrative:{label}",
        status=COST_STATUS_ILLUSTRATIVE,
        per_side_bps=per_side_bps,
        notes=ILLUSTRATIVE_NOTE,
    )


# Personal-use operator defaults (not a broker quote, not commercial redistribution).
# Exchange/levy/tax floor published by IDX (Regular Market), as of page check 2026-09-24:
#   buy 0.0433% / sell 0.1433% (sell includes 0.1% final WHT) —
#   https://www.idx.co.id/en/products-services/trading-hours-and-mechanism/
# All-in retail wrap used here matches Trading Plan defaults (0.15% buy / 0.25% sell)
# which already embed typical brokerage + levy + tax for personal P&L worksheets.
PERSONAL_BUY_FEE_BPS = 15.0
PERSONAL_SELL_FEE_BPS = 25.0
PERSONAL_SLIPPAGE_PER_SIDE_BPS = 5.0
PERSONAL_COST_AS_OF = "2026-09-24"
PERSONAL_COST_SOURCE = (
    "personal-operator: idx.trading_plan.DEFAULT_FEE_BUY/SELL (0.15%/0.25% all-in) "
    "aligned with IDX Regular Market published exchange+levy+VAT+sell-WHT floor "
    "(buy 0.0433% / sell 0.1433%; idx.co.id trading-hours-and-mechanism, checked 2026-09-24). "
    "Broker commission is operator-specific — replace when your broker schedule is known."
)
PERSONAL_SLIPPAGE_SOURCE = (
    "personal-operator assumption 5 bps/side — not measured fills; replace with your own."
)


def personal_operator_cost_model() -> CostModel:
    """CONFIGURED cost for personal use only (explicit source + as_of)."""
    return CostModel(
        model_id="personal:trading-plan-default-all-in",
        status=COST_STATUS_CONFIGURED,
        buy_fee_bps=PERSONAL_BUY_FEE_BPS,
        sell_fee_bps=PERSONAL_SELL_FEE_BPS,
        source=PERSONAL_COST_SOURCE,
        as_of=PERSONAL_COST_AS_OF,
        notes=(
            "Personal operator default for private research/P&L. "
            "Not a verified quote from a named broker."
        ),
    )


def personal_operator_slippage_model() -> SlippageModel:
    """CONFIGURED slippage for personal use only (explicit source + as_of)."""
    return SlippageModel(
        model_id="personal:5bps-side-assumption",
        status=COST_STATUS_CONFIGURED,
        per_side_bps=PERSONAL_SLIPPAGE_PER_SIDE_BPS,
        source=PERSONAL_SLIPPAGE_SOURCE,
        as_of=PERSONAL_COST_AS_OF,
        notes="Personal operator assumption — not measured IDX fill slippage.",
    )


def _side_fractions(cost: CostModel, slippage: SlippageModel) -> tuple[float, float] | None:
    if not (cost.is_applicable and slippage.is_applicable):
        return None
    slip = float(slippage.per_side_bps or 0.0)
    buy = (float(cost.buy_fee_bps or 0.0) + slip) / 10_000.0
    sell = (float(cost.sell_fee_bps or 0.0) + slip) / 10_000.0
    if sell >= 1.0:
        raise CostModelError("sell-side cost + slippage must be < 100%")
    return buy, sell


def net_return_from_gross(
    gross_return: float,
    cost: CostModel,
    slippage: SlippageModel,
) -> float | None:
    """Exact multiplicative net return (fractions); ``None`` if any model is NOT_CONFIGURED.

    entry fill = P0 * (1 + buy_fee + slip); exit fill = P1 * (1 - sell_fee - slip)
    """
    sides = _side_fractions(cost, slippage)
    if sides is None:
        return None
    buy, sell = sides
    return (1.0 + float(gross_return)) * (1.0 - sell) / (1.0 + buy) - 1.0


def round_trip_cost_pct(cost: CostModel, slippage: SlippageModel) -> float | None:
    """Return drag (percent) of a zero-gross round trip; ``None`` when not configured."""
    net = net_return_from_gross(0.0, cost, slippage)
    return None if net is None else round(-net * 100.0, 6)


def return_semantics(cost: CostModel, slippage: SlippageModel) -> dict[str, Any]:
    """Gross vs net labelling shared by validation, robustness and registry records."""
    if not (cost.is_applicable and slippage.is_applicable):
        net_status = "NOT_AVAILABLE"
    elif COST_STATUS_ILLUSTRATIVE in (cost.status, slippage.status):
        net_status = COST_STATUS_ILLUSTRATIVE
    else:
        net_status = "AVAILABLE"
    return {
        "cost_model": cost.model_id,
        "cost_model_status": cost.status,
        "slippage_model": slippage.model_id,
        "slippage_model_status": slippage.status,
        "gross_return_basis": "GROSS_UNADJUSTED_CLOSE",
        "net_return_status": net_status,
        "return_is_net_tradable": net_status == "AVAILABLE",
        "execution_feasibility": EXECUTION_FEASIBILITY_NOTE,
    }


def net_trade_summary(
    trades_df: pd.DataFrame | None,
    cost: CostModel,
    slippage: SlippageModel,
) -> dict[str, Any]:
    """Per-trade gross vs net expectancy / win rate from the engine ledger."""
    out: dict[str, Any] = {
        **return_semantics(cost, slippage),
        "sample_count": 0,
        "gross_expectancy_pct": None,
        "gross_win_rate_pct": None,
        "net_expectancy_pct": None,
        "net_win_rate_pct": None,
        "round_trip_cost_pct": round_trip_cost_pct(cost, slippage),
        "ledger_status": "NO_TRADE_LEDGER",
    }
    if trades_df is None or LEDGER_RETURN_COLUMN not in getattr(trades_df, "columns", ()):
        return out
    gross = pd.to_numeric(trades_df[LEDGER_RETURN_COLUMN], errors="coerce").dropna()
    if len(gross) == 0:
        out["ledger_status"] = "EMPTY_LEDGER"
        return out

    out["ledger_status"] = "OK"
    out["sample_count"] = int(len(gross))
    out["gross_expectancy_pct"] = round(float(gross.mean()) * 100.0, 4)
    out["gross_win_rate_pct"] = round(float((gross > 0).mean()) * 100.0, 2)

    sides = _side_fractions(cost, slippage)
    if sides is not None:
        buy, sell = sides
        net = (1.0 + gross) * (1.0 - sell) / (1.0 + buy) - 1.0
        out["net_expectancy_pct"] = round(float(net.mean()) * 100.0, 4)
        out["net_win_rate_pct"] = round(float((net > 0).mean()) * 100.0, 2)
    return out
