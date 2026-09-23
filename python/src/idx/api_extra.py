"""Additional production API routes registered onto the FastAPI app."""

from __future__ import annotations

from typing import Any

from fastapi import Header, HTTPException, Query, Request
from pydantic import BaseModel, Field


class WatchlistItemIn(BaseModel):
    ticker: str
    company: str | None = None
    group: str | None = "default"
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)
    priority: int | None = None
    setup: str | None = None
    current_price: float | None = None
    score: float | None = None
    signal: str | None = None
    entry: float | None = None
    tp: float | None = None
    cl: float | None = None
    rr: float | None = None


class StrategyLabRequest(BaseModel):
    strategy: str
    holding_days: int = 20
    top_n: int = 10
    min_turnover_rp: float = 1_000_000_000.0
    start_date: str | None = None
    end_date: str | None = None
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None


def register_extra_routes(app) -> None:
    from idx.auth_session import (
        auth_status,
        create_session,
        invalidate_session,
        require_session,
        strip_client_identity_fields,
    )
    from idx.big_money import build_big_money
    from idx.core.query import query_dataset
    from idx.core.utils import DATA_DIR, load_json
    from idx.providers import (
        AIProvider,
        NotificationProvider,
        PaymentProvider,
        integrations_overview,
    )
    from idx.schema_version import DATA_SCHEMA_VERSION, attach_schema, normalize_company_record
    from idx.stock_terminal import build_stock_terminal
    from idx.strategy_lab import list_strategies, run_strategy_lab
    from idx.ticker_safe import sanitize_ticker
    from idx.trading_plan import (
        enrich_plan,
        list_journals,
        list_plans,
        upsert_journal,
        upsert_plan,
        weekly_recap,
    )
    from idx import watchlist_store as wl

    def _session_token(
        authorization: str | None,
        x_ritel_session: str | None,
    ) -> str | None:
        if x_ritel_session:
            return x_ritel_session.strip()
        if authorization and authorization.lower().startswith("bearer "):
            return authorization[7:].strip()
        return None

    def _principal(authorization: str | None, x_ritel_session: str | None):
        token = _session_token(authorization, x_ritel_session)
        try:
            return require_session(token)
        except PermissionError as exc:
            raise HTTPException(
                status_code=401,
                detail={
                    "error": "UNAUTHORIZED",
                    "auth": auth_status(),
                    "message": str(exc),
                },
            ) from exc

    @app.get("/schema", tags=["System"], include_in_schema=False)
    @app.get("/api/schema", tags=["System"])
    async def api_schema():
        from idx.schema_version import schema_meta

        return attach_schema(schema_meta())

    @app.get("/api/data-status", tags=["System"])
    async def api_data_status():
        """Alias of ingestion-status for stable frontend / ops contracts."""
        from idx.ingestion import get_full_ingestion_status

        return get_full_ingestion_status()

    @app.get("/api/integrations", tags=["System"])
    async def api_integrations():
        return attach_schema(integrations_overview())

    @app.get("/api/auth/status", tags=["Auth"])
    async def api_auth_status():
        return attach_schema(auth_status())

    @app.post("/api/auth/session", tags=["Auth"])
    async def api_auth_session(label: str | None = None):
        return attach_schema(create_session(label=label))

    @app.post("/api/auth/logout", tags=["Auth"])
    @app.delete("/api/auth/session", tags=["Auth"])
    async def api_auth_logout(
        authorization: str | None = Header(default=None),
        x_ritel_session: str | None = Header(default=None, alias="X-Ritel-Session"),
    ):
        token = _session_token(authorization, x_ritel_session)
        ok = invalidate_session(token)
        return attach_schema(
            {
                "logged_out": ok,
                "auth": auth_status(),
                "message": "Session invalidated" if ok else "No active session",
            }
        )

    @app.get("/api/stock/{ticker}/terminal", tags=["Market Data"])
    @app.get("/api/stock/{ticker}/chart", tags=["Market Data"])
    async def api_stock_terminal(
        ticker: str,
        limit: int = Query(120, ge=1, le=500),
    ):
        import os

        try:
            ticker = sanitize_ticker(ticker)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        company = None
        alpha = os.path.join(DATA_DIR, "network_alpha_data.json")
        if os.path.isfile(alpha):
            try:
                blob = load_json(alpha)
                for c in blob.get("companies") or []:
                    if str(c.get("code") or "").upper() == ticker:
                        company = normalize_company_record(c)
                        break
            except Exception:
                company = None
        try:
            df = query_dataset("stock_summary", where=f"StockCode = '{ticker}'")
        except Exception:
            df = __import__("pandas").DataFrame()
        if len(df) == 0:
            raise HTTPException(status_code=404, detail=f"Ticker '{ticker}' not found.")
        return build_stock_terminal(df, ticker, limit=limit, company=company)

    @app.get("/api/stock/{ticker}/foreign", tags=["Market Data"])
    @app.get("/api/stock/{ticker}/flow", tags=["Market Data"])
    async def api_stock_foreign(ticker: str):
        try:
            ticker = sanitize_ticker(ticker)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            df = query_dataset("stock_summary", where=f"StockCode = '{ticker}'")
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if len(df) == 0:
            raise HTTPException(status_code=404, detail=f"Ticker '{ticker}' not found.")
        import pandas as pd

        df = df.copy()
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.dropna(subset=["Date"]).sort_values("Date")
        last = df.iloc[-1]
        fb = last.get("ForeignBuy")
        fs = last.get("ForeignSell")
        try:
            fb_f = float(fb) if fb is not None and str(fb) != "nan" else None
            fs_f = float(fs) if fs is not None and str(fs) != "nan" else None
            net = (fb_f - fs_f) if fb_f is not None and fs_f is not None else last.get("NetForeignFlow")
        except (TypeError, ValueError):
            fb_f = fs_f = net = None
        return attach_schema(
            {
                "ticker": ticker,
                "foreign_buy": fb_f,
                "foreign_sell": fs_f,
                "foreign_net": float(net) if net is not None and str(net) != "nan" else None,
                "as_of": str(last.get("Date"))[:10],
                "source": "stock_summary",
                "quality": "B",
                "note": "Aggregate foreign flow — not smart-money attribution.",
                "orderbook": "NOT_CONFIGURED",
                "tape": "NOT_CONFIGURED",
            }
        )

    @app.get("/api/stock/{ticker}/broker", tags=["Market Data"])
    async def api_stock_broker(ticker: str):
        try:
            ticker = sanitize_ticker(ticker)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return attach_schema(
            {
                "ticker": ticker,
                "scope": "MARKET-WIDE",
                "stock_specific": False,
                "status": "UNAVAILABLE",
                "blocks": [],
                "broker_blocks_available": False,
                "message": (
                    "Stock-specific broker attribution unavailable. "
                    "Use /api/broker-flow for MARKET-WIDE concentration."
                ),
                "DATA_SCHEMA_VERSION": DATA_SCHEMA_VERSION,
            }
        )

    @app.get("/api/stock/{ticker}/ownership", tags=["Ownership"])
    async def api_stock_ownership(ticker: str):
        """Per-ticker ownership disclosure layer (honest UNAVAILABLE when no CSV)."""
        try:
            ticker = sanitize_ticker(ticker)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        payload = build_big_money(ticker=ticker, foreign_row=None, broker_summary=None)
        ownership = payload.get("ownership") or {}
        return attach_schema(
            {
                "ticker": ticker,
                "status": ownership.get("status") or "UNAVAILABLE",
                "basis": ownership.get("basis") or "disclosure",
                "ownership": ownership,
                "note": (
                    "Disclosure-based ownership only — not transaction tape, "
                    "not Fast-In/Fast-Out."
                ),
                "fast_in_fast_out": "UNAVAILABLE",
            }
        )

    @app.get("/api/stock/{ticker}/signals", tags=["Signals"])
    async def api_stock_signals(ticker: str):
        """Per-ticker screener/signal slice from the stock terminal builder."""
        import os

        try:
            ticker = sanitize_ticker(ticker)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        company = None
        alpha = os.path.join(DATA_DIR, "network_alpha_data.json")
        if os.path.isfile(alpha):
            try:
                blob = load_json(alpha)
                for c in blob.get("companies") or []:
                    if str(c.get("code") or "").upper() == ticker:
                        company = normalize_company_record(c)
                        break
            except Exception:
                company = None
        try:
            df = query_dataset("stock_summary", where=f"StockCode = '{ticker}'")
        except Exception:
            df = __import__("pandas").DataFrame()
        if len(df) == 0:
            return attach_schema(
                {
                    "ticker": ticker,
                    "status": "UNAVAILABLE",
                    "screener": None,
                    "message": f"No stock_summary rows for '{ticker}'.",
                    "realtime": "NOT_CONFIGURED",
                }
            )
        terminal = build_stock_terminal(df, ticker, limit=80, company=company)
        return attach_schema(
            {
                "ticker": ticker,
                "status": terminal.get("status") or "ok",
                "as_of": terminal.get("as_of"),
                "source": terminal.get("source"),
                "screener": terminal.get("screener"),
                "realtime": "NOT_CONFIGURED",
                "note": "EOD-derived screener signals only — not live ticks.",
            }
        )

    @app.get("/api/big-money", tags=["Big Money"])
    async def api_big_money(ticker: str | None = None):
        foreign_row = None
        if ticker:
            try:
                ticker = sanitize_ticker(ticker)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            try:
                df = query_dataset(
                    "stock_summary",
                    where=f"StockCode = '{ticker}'",
                )
                if len(df) > 0:
                    import pandas as pd

                    df = df.copy()
                    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
                    last = df.dropna(subset=["Date"]).sort_values("Date").iloc[-1]
                    foreign_row = last.to_dict()
                    foreign_row["as_of"] = str(last.get("Date"))[:10]
            except Exception:
                foreign_row = None
        broker_df = None
        try:
            broker_df = query_dataset("broker_summary")
        except Exception:
            broker_df = None
        return build_big_money(
            ticker=ticker,
            broker_summary=broker_df,
            foreign_row=foreign_row,
        )

    @app.get("/api/strategy", tags=["Strategy Lab"])
    async def api_strategy_catalog():
        return list_strategies()

    @app.post("/api/strategy/run", tags=["Strategy Lab"])
    async def api_strategy_run(req: StrategyLabRequest):
        return run_strategy_lab(
            req.strategy,
            holding_days=req.holding_days,
            top_n=req.top_n,
            min_turnover_rp=req.min_turnover_rp,
            start_date=req.start_date,
            end_date=req.end_date,
            stop_loss_pct=req.stop_loss_pct,
            take_profit_pct=req.take_profit_pct,
        )

    @app.get("/api/watchlist", tags=["Watchlist"])
    async def api_watchlist_list(
        authorization: str | None = Header(default=None),
        x_ritel_session: str | None = Header(default=None, alias="X-Ritel-Session"),
    ):
        principal = _principal(authorization, x_ritel_session)
        return wl.list_items(principal)

    @app.post("/api/watchlist", tags=["Watchlist"])
    async def api_watchlist_add(
        item: WatchlistItemIn,
        authorization: str | None = Header(default=None),
        x_ritel_session: str | None = Header(default=None, alias="X-Ritel-Session"),
    ):
        principal = _principal(authorization, x_ritel_session)
        try:
            payload = strip_client_identity_fields(item.model_dump())
            return wl.add_item(principal, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.patch("/api/watchlist/{ticker}", tags=["Watchlist"])
    async def api_watchlist_patch(
        ticker: str,
        body: dict[str, Any],
        authorization: str | None = Header(default=None),
        x_ritel_session: str | None = Header(default=None, alias="X-Ritel-Session"),
    ):
        principal = _principal(authorization, x_ritel_session)
        try:
            return wl.update_item(
                principal, ticker, strip_client_identity_fields(body)
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Not found: {ticker}") from exc

    @app.delete("/api/watchlist/{ticker}", tags=["Watchlist"])
    async def api_watchlist_delete(
        ticker: str,
        authorization: str | None = Header(default=None),
        x_ritel_session: str | None = Header(default=None, alias="X-Ritel-Session"),
    ):
        principal = _principal(authorization, x_ritel_session)
        try:
            return wl.remove_item(principal, ticker)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Not found: {ticker}") from exc

    @app.get("/api/trading-plan", tags=["Trading Plan"])
    async def api_trading_plan_list(
        authorization: str | None = Header(default=None),
        x_ritel_session: str | None = Header(default=None, alias="X-Ritel-Session"),
    ):
        principal = _principal(authorization, x_ritel_session)
        return attach_schema({"plans": list_plans(principal)})

    @app.post("/api/trading-plan", tags=["Trading Plan"])
    async def api_trading_plan_upsert(
        body: dict[str, Any],
        authorization: str | None = Header(default=None),
        x_ritel_session: str | None = Header(default=None, alias="X-Ritel-Session"),
    ):
        principal = _principal(authorization, x_ritel_session)
        return upsert_plan(principal, strip_client_identity_fields(body))

    @app.post("/api/trading-plan/compute", tags=["Trading Plan"])
    async def api_trading_plan_compute(body: dict[str, Any]):
        """Stateless Excel-semantics compute (no auth required for pure calc)."""
        return enrich_plan(strip_client_identity_fields(body))

    @app.get("/api/journal", tags=["Trading Plan"])
    async def api_journal_list(
        authorization: str | None = Header(default=None),
        x_ritel_session: str | None = Header(default=None, alias="X-Ritel-Session"),
    ):
        principal = _principal(authorization, x_ritel_session)
        rows = list_journals(principal)
        return attach_schema({"journals": rows, "weekly": weekly_recap(rows)})

    @app.post("/api/journal", tags=["Trading Plan"])
    async def api_journal_upsert(
        body: dict[str, Any],
        authorization: str | None = Header(default=None),
        x_ritel_session: str | None = Header(default=None, alias="X-Ritel-Session"),
    ):
        principal = _principal(authorization, x_ritel_session)
        return upsert_journal(principal, strip_client_identity_fields(body))

    @app.get("/api/ai", tags=["AI"], include_in_schema=False)
    @app.get("/api/ai/status", tags=["AI"])
    async def api_ai_status():
        return attach_schema(AIProvider().status().to_dict())

    @app.post("/api/ai/generate", tags=["AI"])
    async def api_ai_generate(body: dict[str, Any]):
        prompt = str(body.get("prompt") or "")
        purpose = str(body.get("purpose") or "generic")
        return AIProvider().generate(prompt, purpose=purpose)

    @app.get("/api/notifications", tags=["Notifications"], include_in_schema=False)
    @app.get("/api/notifications/status", tags=["Notifications"])
    async def api_notifications_status():
        return attach_schema(NotificationProvider().status().to_dict())

    @app.post("/api/notifications/enqueue", tags=["Notifications"])
    async def api_notifications_enqueue(body: dict[str, Any]):
        event_type = str(body.get("event_type") or "generic")
        payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
        return NotificationProvider().enqueue(event_type, payload)

    @app.get("/api/payment", tags=["Payment"], include_in_schema=False)
    @app.get("/api/payment/status", tags=["Payment"])
    async def api_payment_status():
        return attach_schema(PaymentProvider().status().to_dict())

    @app.post("/api/payment/webhook", tags=["Payment"])
    async def api_payment_webhook(request: Request):
        body = await request.body()
        headers = {k: v for k, v in request.headers.items()}
        result = PaymentProvider().webhook(headers=headers, body=body)
        # Never grant entitlement from unsigned / unconfigured webhooks.
        return attach_schema(result)

    @app.get("/api/realtime/status", tags=["Market Data"])
    async def api_realtime_status():
        from idx.providers import MarketDataProvider

        st = MarketDataProvider().status().to_dict()
        return attach_schema(
            {
                "realtime": "NOT_CONFIGURED",
                "market_data": st,
                "quality_contract": MarketDataProvider().realtime_quality_contract(),
                "message": "REALTIME NOT CONFIGURED",
            }
        )
