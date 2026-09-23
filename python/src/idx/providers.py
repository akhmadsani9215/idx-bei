"""Integration capability providers — honest NOT_CONFIGURED when absent."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# Realtime data-quality contract (never invent buy-side dominance from Bid/Offer volumes).
REALTIME_DATA_QUALITY = {
    "A": "Actual trade/tick with reliable side when provider supplies it",
    "B": "Trade/volume with inferred side only",
    "C": "OHLCV / proxy bar — not tick tape",
    "EOD_SNAPSHOT": "End-of-day / session snapshot only",
}


@dataclass(frozen=True)
class ProviderCapability:
    name: str
    available: bool
    status: str  # AVAILABLE | PARTIAL | UNAVAILABLE | NOT_CONFIGURED
    notes: str = ""


@dataclass
class ProviderStatus:
    provider: str
    status: str
    capabilities: list[ProviderCapability] = field(default_factory=list)
    configured: bool = False
    as_of: str | None = None
    source: str | None = None
    quality: str = "U"
    confidence: float | None = None
    calculated_at: str = field(default_factory=_utc_now)
    engine_version: str = "providers-1.1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "status": self.status,
            "configured": self.configured,
            "capabilities": [
                {
                    "name": c.name,
                    "available": c.available,
                    "status": c.status,
                    "notes": c.notes,
                }
                for c in self.capabilities
            ],
            "as_of": self.as_of,
            "source": self.source,
            "quality": self.quality,
            "confidence": self.confidence,
            "calculated_at": self.calculated_at,
            "engine_version": self.engine_version,
        }


class MarketDataProvider:
    """EOD Parquet/IDX path is available; realtime/tick/tape/depth are not.

    Capability map documents what a production realtime adapter must satisfy.
    Abstraction is status/capability oriented — NOT a live feed client.
    """

    name = "eod_parquet_idx"

    def status(self) -> ProviderStatus:
        nc = "NOT_CONFIGURED"
        caps = [
            ProviderCapability("historical_daily", True, "AVAILABLE", "stock_summary partitions"),
            ProviderCapability("foreign", True, "PARTIAL", "ForeignBuy/Sell aggregates in EOD"),
            ProviderCapability("broker_market_wide", True, "PARTIAL", "broker_summary concentration only"),
            ProviderCapability("broker_stock_specific", False, "UNAVAILABLE", "No stock↔broker attribution"),
            ProviderCapability("realtime_quote", False, nc, "Last/bid/ask quote stream"),
            ProviderCapability("tick", False, nc, "Trade/tick events"),
            ProviderCapability("trade_timestamp", False, nc),
            ProviderCapability("trade_price", False, nc),
            ProviderCapability("trade_volume", False, nc),
            ProviderCapability("trade_side", False, nc, "Only if provider supplies; never invent"),
            ProviderCapability("bid", False, nc),
            ProviderCapability("ask", False, nc),
            ProviderCapability("bid_volume", False, nc),
            ProviderCapability("ask_volume", False, nc),
            ProviderCapability("orderbook", False, nc),
            ProviderCapability("depth", False, nc),
            ProviderCapability("historical_intraday", False, nc),
            ProviderCapability("websocket", False, nc, "Upstream WS — users must not connect directly"),
            ProviderCapability("rest", False, nc),
            ProviderCapability("reconnect", False, nc),
            ProviderCapability("heartbeat", False, nc),
            ProviderCapability("sequence", False, nc),
            ProviderCapability("latency", False, nc),
            ProviderCapability("market_status", False, nc),
            ProviderCapability("symbol_mapping", False, nc),
            ProviderCapability("corporate_actions", False, nc),
            ProviderCapability("rate_limits", False, nc),
            ProviderCapability("commercial_usage", False, nc, "LICENSE REVIEW REQUIRED"),
            ProviderCapability("redistribution_rights", False, nc, "LICENSE REVIEW REQUIRED"),
            ProviderCapability("realtime", False, nc, "Alias — no realtime feed configured"),
            ProviderCapability("tape", False, nc),
        ]
        return ProviderStatus(
            provider=self.name,
            status="PARTIAL",
            configured=True,
            capabilities=caps,
            source="stock_summary/broker_summary parquet",
            quality="EOD_SNAPSHOT",
            confidence=0.7,
        )

    def realtime_quality_contract(self) -> dict[str, Any]:
        return {
            "grades": dict(REALTIME_DATA_QUALITY),
            "forbidden": [
                "Label BidVolume>OfferVolume as actual buy dominance",
                "Infer broker/actor identity without source",
                "Claim quality A without provider-supplied trade side",
            ],
            "lineage_fields": [
                "value",
                "source",
                "as_of",
                "quality",
                "confidence",
                "calculated_at",
                "engine_version",
            ],
        }


class AIProvider:
    name = "ai"

    def status(self) -> ProviderStatus:
        key = os.environ.get("RITELINSIGHT_AI_API_KEY") or os.environ.get("OPENAI_API_KEY")
        key_present = bool(key)
        if not key_present:
            status = "NOT_CONFIGURED"
            configured = False
            notes = "No AI API key in environment"
        else:
            status = "PARTIAL"
            configured = True
            notes = (
                "Key present but outbound provider adapter not approved — "
                "generate() will not call external AI."
            )
        return ProviderStatus(
            provider=self.name,
            status=status,
            configured=configured,
            capabilities=[
                ProviderCapability("research_brief", False, status, notes),
                ProviderCapability("signal_explanation", False, status, notes),
                ProviderCapability("investment_memo", False, status, notes),
                ProviderCapability("outbound_adapter", False, "NOT_CONFIGURED", notes),
                ProviderCapability("cost_visibility", False, "NOT_CONFIGURED"),
                ProviderCapability("timeout_enforced", True, "AVAILABLE", "Local guard only"),
            ],
            source="env RITELINSIGHT_AI_API_KEY" if key_present else None,
            quality="U",
            confidence=None,
        )

    def generate(self, prompt: str, *, purpose: str = "generic") -> dict[str, Any]:
        _ = prompt
        st = self.status()
        if not st.configured:
            return {
                "status": "NOT_CONFIGURED",
                "text": None,
                "is_ai_generated": False,
                "purpose": purpose,
                "error": "AI provider credentials are not configured.",
                "usage": None,
                "lineage": st.to_dict(),
            }
        return {
            "status": "NOT_CONFIGURED",
            "text": None,
            "is_ai_generated": False,
            "purpose": purpose,
            "error": (
                "AI key present but outbound provider call is intentionally disabled "
                "until a production provider adapter is approved."
            ),
            "usage": None,
            "lineage": st.to_dict(),
        }


class NotificationProvider:
    name = "telegram"

    def status(self) -> ProviderStatus:
        token = os.environ.get("RITELINSIGHT_TELEGRAM_BOT_TOKEN")
        token_present = bool(token)
        if not token_present:
            status = "NOT_CONFIGURED"
            configured = False
            notes = "No Telegram bot token"
        else:
            status = "PARTIAL"
            configured = True
            notes = "Token present; outbound Telegram send not approved/wired — sent always false"
        return ProviderStatus(
            provider=self.name,
            status=status,
            configured=configured,
            capabilities=[
                ProviderCapability("send_message", False, status, notes),
                ProviderCapability(
                    "delivery_status",
                    True,
                    "AVAILABLE",
                    "Local event log only — never implies upstream ack",
                ),
                ProviderCapability("retry", True, "PARTIAL", "Local enqueue only"),
            ],
            source="env RITELINSIGHT_TELEGRAM_BOT_TOKEN" if token_present else None,
            quality="U",
        )

    def enqueue(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        st = self.status()
        return {
            "event_id": f"evt_{int(datetime.now(timezone.utc).timestamp() * 1000)}",
            "event_type": event_type,
            "payload_keys": sorted(payload.keys()),
            "delivery_status": "NOT_CONFIGURED" if not st.configured else "QUEUED_LOCAL",
            "sent": False,
            "retry_safe": True,
            "calculated_at": _utc_now(),
            "provider": st.to_dict(),
        }


class PaymentProvider:
    name = "payment"

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            provider=self.name,
            status="NOT_CONFIGURED",
            configured=False,
            capabilities=[
                ProviderCapability("checkout", False, "NOT_CONFIGURED"),
                ProviderCapability("subscription", False, "NOT_CONFIGURED"),
                ProviderCapability("webhook", False, "NOT_CONFIGURED"),
                ProviderCapability("webhook_signature", False, "NOT_CONFIGURED"),
                ProviderCapability("idempotency", False, "NOT_CONFIGURED"),
                ProviderCapability("entitlement_grant", False, "NOT_CONFIGURED"),
            ],
            source=None,
            quality="U",
            confidence=None,
        )

    def webhook(self, *, headers: dict[str, str], body: bytes) -> dict[str, Any]:
        _ = headers, body
        return {
            "accepted": False,
            "status": "NOT_CONFIGURED",
            "paid": False,
            "entitlement": None,
            "error": "Payment provider not configured — webhook ignored.",
            "calculated_at": _utc_now(),
        }


def integrations_overview() -> dict[str, Any]:
    from idx.core.currency import fx_status

    return {
        "market_data": MarketDataProvider().status().to_dict(),
        "ai": AIProvider().status().to_dict(),
        "notifications": NotificationProvider().status().to_dict(),
        "payment": PaymentProvider().status().to_dict(),
        "fx": fx_status(),
        "realtime": "NOT_CONFIGURED",
        "realtime_quality_contract": MarketDataProvider().realtime_quality_contract(),
        "calculated_at": _utc_now(),
    }
