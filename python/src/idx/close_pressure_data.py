"""
Close Pressure Engine - IDX stock-level data layer.

Source:
    /ListedCompany/GetTradingInfoSS

This module deliberately does NOT invent broker BUY/SELL attribution.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from idx.close_pressure_config import classify_time_window
from idx.core.client import IDXClient

ENDPOINT = "/ListedCompany/GetTradingInfoSS"


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _date(value: Any) -> str:
    if not value:
        return ""
    return str(value)[:10]


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    foreign_buy = _num(row.get("ForeignBuy"))
    foreign_sell = _num(row.get("ForeignSell"))

    bid = _num(row.get("Bid"))
    offer = _num(row.get("Offer"))
    bid_volume = _num(row.get("BidVolume"))
    offer_volume = _num(row.get("OfferVolume"))

    return {
        "date": _date(row.get("Date")),
        "stock_code": str(row.get("StockCode") or ""),
        "stock_name": str(row.get("StockName") or ""),
        "previous": _num(row.get("Previous")),
        "open": _num(row.get("OpenPrice")),
        "first_trade": _num(row.get("FirstTrade")),
        "high": _num(row.get("High")),
        "low": _num(row.get("Low")),
        "close": _num(row.get("Close")),
        "change": _num(row.get("Change")),
        "volume": _num(row.get("Volume")),
        "value": _num(row.get("Value")),
        "frequency": _num(row.get("Frequency")),
        "bid": bid,
        "bid_volume": bid_volume,
        "offer": offer,
        "offer_volume": offer_volume,
        "foreign_buy": foreign_buy,
        "foreign_sell": foreign_sell,
        "foreign_net": foreign_buy - foreign_sell,
        "non_regular_volume": _num(row.get("NonRegularVolume")),
        "non_regular_value": _num(row.get("NonRegularValue")),
        "non_regular_frequency": _num(row.get("NonRegularFrequency")),
        # EOD order-book pressure proxy only.
        # This is NOT transaction-level buy/sell volume.
        "book_imbalance": (
            (bid_volume - offer_volume) / (bid_volume + offer_volume)
            if (bid_volume + offer_volume) > 0
            else 0.0
        ),
        "book_pressure_quality": "EOD_SNAPSHOT_ONLY",
        "intraday_trade_side_available": False,
        "broker_attribution_available": False,
    }


def fetch_trading_info(
    client: IDXClient,
    code: str,
    length: int = 1000,
) -> list[dict[str, Any]]:
    """
    Fetch stock-level IDX trading history.

    IDX currently behaves inconsistently for small `length` values:
    some valid symbols can return HTTP 200 with `replies: null`.
    Therefore we retry with larger page sizes before declaring no data.
    """
    code = str(code).upper().strip()

    if not code:
        return []

    lengths = []

    for candidate in (length, 1000):
        candidate = int(candidate)
        if candidate > 0 and candidate not in lengths:
            lengths.append(candidate)

    for page_length in lengths:
        response = client.get(
            ENDPOINT,
            params={
                "code": code,
                "start": 0,
                "length": page_length,
            },
        )

        if response is None:
            continue

        try:
            payload = response.json()
        except Exception:
            continue

        if not isinstance(payload, dict):
            continue

        rows = payload.get("replies")

        if not isinstance(rows, list) or not rows:
            continue

        normalized = [normalize_row(row) for row in rows if isinstance(row, dict)]

        if normalized:
            return normalized

    return []


def enrich_with_intraday_phase(
    row: dict[str, Any],
    timestamp: datetime,
) -> dict[str, Any]:
    """
    Add an INTERNAL screening phase.

    Timestamp must already be converted to Jakarta market time.
    It is intentionally not a dashboard field.
    """
    result = dict(row)

    phase = classify_time_window(timestamp.time())

    result["_cpe_phase"] = phase
    result["_cpe_timestamp"] = timestamp.isoformat()

    return result
