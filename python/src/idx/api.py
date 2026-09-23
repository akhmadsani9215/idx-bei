"""
High-Performance FastAPI REST & WebSocket Microservice Layer for IDX-BEI Toolkit.
"""

import asyncio
import json
import math
import os
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from idx.core.ownership import get_latest_shareholder_drift
from idx.core.query import query_dataset
from idx.core.utils import DATA_DIR, load_json
from idx.graph import (
    calculate_board_centrality,
    detect_cross_holdings,
    get_company_network,
    get_ubo_tree,
)
from idx.ingestion import (
    get_full_ingestion_status,
    get_job_status,
    list_recent_jobs,
    run_async_ingestion_job,
)
from idx.signals import (
    broker_concentration_screen,
    build_briefing,
    compute_technical_indicators,
)
from idx.screener import run_screener
from idx.api_extra import register_extra_routes
from idx.cors_config import resolve_cors_origins
from idx.public_static import resolve_public_data_path
from idx.ticker_safe import sanitize_ticker

app = FastAPI(
    title="IDX-BEI Quantitative & Microservice API",
    description="High-performance async REST & WebSocket API for Indonesia Stock Exchange data and quantitative intelligence.",
    version="0.2.0",
)

_CORS = resolve_cors_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS["allow_origins"] or ["http://127.0.0.1"],
    allow_credentials=_CORS["allow_credentials"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Extra production routes (watchlist, terminal aliases, strategy lab, providers).
register_extra_routes(app)

REPO_ROOT = os.path.abspath(os.path.join(DATA_DIR, ".."))
DASHBOARD_DIR = os.path.join(REPO_ROOT, "dashboard")
FRONTEND_DIST = os.path.join(REPO_ROOT, "frontend", "dist")

SERVE_DIR = FRONTEND_DIST if os.path.exists(FRONTEND_DIST) else DASHBOARD_DIR

if os.path.exists(SERVE_DIR):
    app.mount(
        "/dashboard",
        StaticFiles(directory=SERVE_DIR, html=True),
        name="dashboard",
    )

# DO NOT mount entire DATA_DIR — private watchlist/journal stores and ownership CSVs
# must not be world-readable. Public artifacts are served via allowlisted /data/{file}.

FRONTEND_ASSETS = os.path.join(FRONTEND_DIST, "assets")

if os.path.exists(FRONTEND_ASSETS):
    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_ASSETS),
        name="assets",
    )


def _is_production_env() -> bool:
    return (os.environ.get("RITELINSIGHT_ENV") or "").strip().lower() in (
        "prod",
        "production",
    )


def safe_http_detail(exc: BaseException, *, public: str = "Internal server error") -> str:
    """Avoid leaking tracebacks / internals in production responses."""
    if _is_production_env():
        return public
    return str(exc) or public


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Sanitize unexpected errors — never return traceback bodies to clients.

    HTTPException / validation errors use FastAPI's more-specific handlers.
    """
    return JSONResponse(
        status_code=500,
        content={
            "error": "INTERNAL_ERROR",
            "detail": safe_http_detail(exc),
            "path": str(request.url.path),
        },
    )


@app.get("/", include_in_schema=False)
async def root_redirect():
    return RedirectResponse(url="/dashboard/")


_TTL_CACHE: dict[str, tuple[float, Any]] = {}


def get_from_cache(key: str, ttl_seconds: float = 60.0) -> Any | None:
    if key in _TTL_CACHE:
        timestamp, value = _TTL_CACHE[key]
        if time.time() - timestamp < ttl_seconds:
            return value
        del _TTL_CACHE[key]
    return None


def set_in_cache(key: str, value: Any) -> None:
    _TTL_CACHE[key] = (time.time(), value)


@app.get("/data/{filename}", tags=["System"])
async def public_data_file(filename: str):
    """Serve allowlisted public data files only (no private stores / CSVs)."""
    path = resolve_public_data_path(filename)
    if path is None:
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path)


class SQLQueryRequest(BaseModel):
    sql: str
    limit: int | None = 50


class BacktestRequest(BaseModel):
    strategy: str = "foreign_flow"
    holding_days: int = 20
    top_n: int = 10
    min_turnover_rp: float = 1_000_000_000.0
    start_date: str | None = None
    end_date: str | None = None
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    position_sizing: str = "equal_weight"



class TriggerIngestionRequest(BaseModel):
    job_type: str = "daily"
    date: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    concurrency: int = 8
    path_or_url: str | None = None


# Allowed job types for Data Center triggers (no fabricated pipelines).
_ALLOWED_INGESTION_JOB_TYPES = frozenset({"daily", "backfill", "sync_all", "ownership"})


def json_safe(value):
    """Recursively convert pandas/NumPy values to strict JSON-safe values."""

    if value is None:
        return None

    # Preserve mappings and recursively sanitize their values.
    if isinstance(value, dict):
        return {
            str(key): json_safe(item)
            for key, item in value.items()
        }

    # Recursively sanitize sequences while preserving list output.
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]

    # Convert NumPy scalar values to native Python values.
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (ValueError, TypeError):
            pass

    if value is None:
        return None

    if isinstance(value, float):
        return value if math.isfinite(value) else None

    try:
        import pandas as pd

        if isinstance(value, pd.Timestamp):
            if pd.isna(value):
                return None
            return value.isoformat()

        # Only evaluate scalar missingness here.
        missing = pd.isna(value)
        if isinstance(missing, bool):
            if missing:
                return None

    except (TypeError, ValueError):
        pass

    return value


def dataframe_to_json_records(df):
    """Convert every DataFrame value to strict JSON-safe Python values."""

    records = []

    for row in df.to_dict(orient="records"):
        records.append(
            {
                key: json_safe(value)
                for key, value in row.items()
            }
        )

    return records


@app.get("/health", tags=["System"])
async def health():
    return {
        "status": "ok",
        "service": "idx-bei-api",
        "version": "0.2.0",
    }


@app.get("/ready", tags=["System"])
@app.get("/api/ready", tags=["System"])
async def ready():
    from idx.ops_status import readiness

    payload = readiness()
    if not payload.get("ready"):
        return JSONResponse(status_code=503, content=payload)
    return payload


@app.get("/api/ops/status", tags=["System"])
async def api_ops_status():
    from idx.ops_status import ops_status

    return ops_status()


@app.get("/api/dashboard-data", tags=["Market Data"])
async def get_dashboard_data():
    """Return unified dashboard dataset."""

    alpha_file = os.path.join(
        DATA_DIR,
        "network_alpha_data.json",
    )

    if os.path.exists(alpha_file):
        return load_json(alpha_file)

    return {
        "companies": [],
        "super_insiders": [],
        "conglomerates": [],
    }


@app.get("/api/companies", tags=["Fundamental"])
async def get_companies():
    """Return all listed companies."""

    alpha_file = os.path.join(
        DATA_DIR,
        "network_alpha_data.json",
    )

    if os.path.exists(alpha_file):
        data = load_json(alpha_file)
        return data.get("companies", [])

    return []


@app.get("/api/signals", tags=["Signals"])
async def get_signals(
    date: str | None = Query(
        None,
        description="Optional trading date (YYYY-MM-DD)",
    ),
):
    cache_key = f"signals:{date or 'latest'}"
    cached = get_from_cache(cache_key, ttl_seconds=60.0)
    if cached is not None:
        return cached

    try:
        res = build_briefing(date=date)

        json_file = res.get("json")

        if json_file and os.path.exists(json_file):
            result = load_json(json_file)
        else:
            # Never return write-metadata (alpha_rows / paths) as the briefing body.
            result = {
                "date": res.get("date"),
                "trade_date": res.get("trade_date"),
                "status": "PARTIAL",
                "message": (
                    "Briefing JSON artifact missing after generation — "
                    "sections unavailable for this request."
                ),
                "composite_alpha_rankings": [],
                "foreign_flow_radar": [],
                "bandarmology_summary": {},
                "top_brokers": [],
                "stealth_accumulation": {
                    "summary": "UNAVAILABLE",
                    "signal": "UNAVAILABLE",
                    "smart_money_delta": None,
                    "anomalies": [],
                },
                "audit_risk_shield": [],
                "dilution_watch": [],
                "sharia_value_screen": [],
                "pasar_nego_crossing": [],
                "meta": {
                    "alpha_rows": res.get("alpha_rows"),
                    "markdown": res.get("markdown"),
                    "json": res.get("json"),
                },
            }
        set_in_cache(cache_key, result)
        return result

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=safe_http_detail(e, public="Signals unavailable"),
        ) from e


@app.get("/api/screener", tags=["Screener"])
async def get_screener(
    timeframe: str = Query(
        "close_pressure",
        description="close_pressure | swing | long_term",
    ),
    ticker: str | None = Query(None, description="Optional ticker filter"),
    date: str | None = Query(None, description="As-of date YYYY-MM-DD"),
    setup: str | None = Query(None, description="Exact setup filter"),
    signal: str | None = Query(None, description="Signal label filter"),
    limit: int = Query(25, ge=1, le=100),
    cursor: int = Query(0, ge=0),
    include_not_qualified: bool = Query(
        False,
        description="Include NOT_QUALIFIED rows (default false)",
    ),
    max_universe: int = Query(
        80,
        ge=1,
        le=300,
        description="Explicit universe scan cap (skipped_due_to_cap reported in meta)",
    ),
):
    """Production screener: structure targets/stops, RR≥1:2, honest data quality.

    Does not stream raw OHLC history to the client — only compact result rows.
    """
    try:
        return run_screener(
            timeframe=timeframe,
            ticker=ticker.upper().strip() if ticker else None,
            date=date,
            setup=setup,
            signal=signal,
            limit=limit,
            cursor=cursor,
            include_not_qualified=include_not_qualified,
            max_universe=max_universe,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=safe_http_detail(e, public="Screener unavailable"),
        ) from e


@app.get("/api/stock/{ticker}", tags=["Market Data"])
async def get_stock_data(
    ticker: str,
    limit: int = 120,
):
    """
    Return historical OHLCV data and technical indicators.

    All NaN / NaT / +/-Inf values are converted to JSON null.
    This prevents FastAPI/Starlette JSON serialization errors.
    """

    import pandas as pd

    try:
        ticker = sanitize_ticker(ticker)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    df = query_dataset(
        "stock_summary",
        where=f"StockCode = '{ticker}'",
    )

    if len(df) == 0:
        raise HTTPException(
            status_code=404,
            detail=f"Ticker '{ticker}' not found.",
        )

    df["Date"] = pd.to_datetime(
        df["Date"],
        errors="coerce",
    )

    df = (
        df
        .dropna(subset=["Date"])
        .sort_values("Date", kind="mergesort")
        .reset_index(drop=True)
    )

    if len(df) == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No valid dated records found for ticker '{ticker}'.",
        )

    # One row per calendar session (keep last write if duplicates exist).
    df["_date_key"] = df["Date"].dt.strftime("%Y-%m-%d")
    df = (
        df
        .drop_duplicates(subset=["_date_key"], keep="last")
        .drop(columns=["_date_key"])
        .reset_index(drop=True)
    )

    tech = compute_technical_indicators(
        df,
        ticker=ticker,
    )

    if limit and limit > 0 and len(tech) > limit:
        tech = (
            tech
            .tail(limit)
            .reset_index(drop=True)
        )

    tech["time"] = tech["Date"].dt.strftime(
        "%Y-%m-%d"
    )

    if "OpenPrice" in tech.columns:
        tech["open"] = tech["OpenPrice"].fillna(
            tech["Close"]
        )
    else:
        tech["open"] = tech["Close"]

    if "High" in tech.columns:
        tech["high"] = tech["High"].fillna(
            tech["Close"]
        )
    else:
        tech["high"] = tech["Close"]

    if "Low" in tech.columns:
        tech["low"] = tech["Low"].fillna(
            tech["Close"]
        )
    else:
        tech["low"] = tech["Close"]

    tech["close"] = tech["Close"]

    if "Volume" in tech.columns:
        tech["volume"] = tech["Volume"].fillna(0)
    else:
        tech["volume"] = 0

    # Keep the normalized lowercase chart fields only.
    # PowerShell treats JSON keys case-insensitively, so keeping both
    # "High" and "high" causes ConvertFrom-Json / Invoke-RestMethod
    # to see duplicate keys.
    output_drop = [
        "OpenPrice",
        "High",
        "Low",
        "Close",
        "Volume",
    ]

    output_df = tech.drop(
        columns=[
            column
            for column in output_drop
            if column in tech.columns
        ],
        errors="ignore",
    )

    records = dataframe_to_json_records(output_df)
    latest = records[-1] if records else {}

    return {
        "ticker": ticker,
        "records": records,
        "latest": latest,
    }


@app.get("/api/stock/{ticker}/blocks", tags=["Market Data"])
async def get_stock_blocks(ticker: str):
    """
    Return stock-level block/flow information using only data that is
    actually present in stock_summary.

    IMPORTANT:
    stock_summary contains aggregate regular/non-regular trading fields,
    but it does NOT contain buyer/seller broker transaction pairs.
    Therefore this endpoint must never synthesize broker blocks.

    When broker transaction detail is unavailable, ``blocks`` is returned
    as an empty list and ``broker_blocks_available`` is False.
    Missing numeric fields are null — never fabricated zeros.
    """

    import pandas as pd

    from idx.schema_version import attach_schema
    from idx.ticker_safe import sanitize_ticker

    try:
        ticker = sanitize_ticker(ticker)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        df = query_dataset(
            "stock_summary",
            where=f"StockCode = '{ticker}'",
        )
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if len(df) == 0:
        raise HTTPException(
            status_code=404,
            detail=f"Ticker '{ticker}' not found.",
        )

    df["Date"] = pd.to_datetime(
        df["Date"],
        errors="coerce",
    )

    df = (
        df
        .dropna(subset=["Date"])
        .sort_values("Date")
        .reset_index(drop=True)
    )

    if len(df) == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No valid dated records found for ticker '{ticker}'.",
        )

    latest_row = df.iloc[-1]

    session_date = str(latest_row["Date"])[:10]

    def _num(value, default=None):
        """Null for missing/NaN — do not map unavailable → 0."""
        try:
            if value is None:
                return default
            if pd.isna(value):
                return default
            out = float(value)
            if not math.isfinite(out):
                return default
            return out
        except (TypeError, ValueError):
            return default

    def _int(value, default=None):
        try:
            if value is None:
                return default
            if pd.isna(value):
                return default
            return int(value)
        except (TypeError, ValueError):
            return default

    def _round_or_none(value, digits=2):
        if value is None:
            return None
        return round(value, digits)

    close_price = _num(latest_row.get("Close"))

    # VWAP only when column present; never silently alias Close as VWAP.
    vwap_price = _num(latest_row.get("VWAP")) if "VWAP" in df.columns else None

    reg_val = _num(latest_row.get("Value"))
    reg_vol = _num(latest_row.get("Volume"))
    non_reg_val = _num(latest_row.get("NonRegularValue"))
    non_reg_vol = _num(latest_row.get("NonRegularVolume"))
    non_reg_freq = _int(latest_row.get("NonRegularFrequency"))
    foreign_buy = _num(latest_row.get("ForeignBuy"))
    foreign_sell = _num(latest_row.get("ForeignSell"))

    # ForeignBuy / ForeignSell are share quantities in stock_summary.
    # Net IDR only when both share legs and close are known.
    nff_val = None
    if (
        foreign_buy is not None
        and foreign_sell is not None
        and close_price is not None
    ):
        nff_val = (foreign_buy - foreign_sell) * close_price

    # stock_summary does not contain broker-level buyer/seller pairs.
    #
    # DO NOT manufacture blocks from:
    #   - broker rankings
    #   - institutional/retail classifications
    #   - regular volume
    #   - non-regular frequency
    #
    # Such calculations would create synthetic transactions that look
    # like actual broker trades.
    blocks: list[dict] = []

    broker_blocks_available = False

    return attach_schema(
        json_safe(
            {
                "ticker": ticker,
                "date": session_date,
                "as_of": session_date,
                "source": "stock_summary",
                "quality": "B",
                "total_turnover_rp": _round_or_none(reg_val),
                "regular_volume_shares": _round_or_none(reg_vol),
                "vwap_price": _round_or_none(vwap_price),
                "vwap_status": (
                    "AVAILABLE" if vwap_price is not None else "UNAVAILABLE"
                ),
                "non_regular_value_rp": _round_or_none(non_reg_val),
                "non_regular_volume_shares": _round_or_none(non_reg_vol),
                "non_regular_frequency": non_reg_freq,
                "foreign_buy_shares": _round_or_none(foreign_buy),
                "foreign_sell_shares": _round_or_none(foreign_sell),
                "net_foreign_flow_rp": _round_or_none(nff_val),
                "broker_blocks_available": broker_blocks_available,
                "broker_blocks_source": "unavailable",
                # Whale / smart-accumulation require transaction tape — never invent 0.
                "total_whale_value_rp": None,
                "smart_accumulation_ratio": None,
                "blocks": blocks,
                "note": (
                    "Aggregate session flow from stock_summary. "
                    "Not broker attribution, not whale radar, not transaction tape."
                ),
            }
        )
    )

@app.get("/api/broker-flow", tags=["Bandarmology"])
async def get_broker_flow(
    date: str | None = None,
    top_k: int = 10,
):
    import pandas as pd

    broker_path = os.path.join(
        DATA_DIR,
        "parquet",
        "broker_summary.parquet",
    )

    if not os.path.exists(broker_path):
        from idx.core.timeseries import read_dataset

        df = read_dataset("broker_summary")
    else:
        df = pd.read_parquet(broker_path)

    if len(df) == 0:
        raise HTTPException(
            status_code=404,
            detail="Broker summary data not available.",
        )

    summary, top_df = broker_concentration_screen(
        df,
        on_date=date,
        top_k=top_k,
    )

    return {
        "summary": json_safe(summary),
        "top_brokers": dataframe_to_json_records(top_df),
    }


@app.get("/api/peers/{ticker}", tags=["Fundamental"])
async def get_peers(ticker: str):
    import pandas as pd

    ratios_path = os.path.join(
        DATA_DIR,
        "parquet",
        "financial_ratios.parquet",
    )

    if not os.path.exists(ratios_path):
        raise HTTPException(
            status_code=404,
            detail="Financial ratios parquet not found.",
        )

    df = pd.read_parquet(ratios_path)

    latest = (
        df
        .sort_values("fsDate")
        .groupby("code")
        .last()
        .reset_index()
    )

    return dataframe_to_json_records(latest)


@app.get("/api/dividend/{ticker}", tags=["Dividends"])
async def get_dividend_analysis(ticker: str):
    from idx.dividend import analyze_stock_dividend

    res = analyze_stock_dividend(ticker)

    if not res.get("has_dividend"):
        raise HTTPException(
            status_code=404,
            detail=res.get(
                "message",
                "Dividend data not found",
            ),
        )

    return json_safe(res)


@app.get("/api/dividend", tags=["Dividends"])
async def screen_dividends(
    min_yield: float = 3.0,
    year: str = "2026",
    limit: int = 25,
):
    from idx.dividend import screen_upcoming_dividends

    df = screen_upcoming_dividends(
        min_yield=min_yield,
        year_filter=year,
        limit=limit,
    )

    return dataframe_to_json_records(df)


@app.get("/api/drift", tags=["Ownership"])
async def get_drift():
    return json_safe(
        get_latest_shareholder_drift()
    )


@app.get("/api/graph/ubo/{ticker}", tags=["Knowledge Graph"])
async def get_ubo(ticker: str):
    return json_safe(
        get_ubo_tree(ticker)
    )


@app.get("/api/graph/network/{ticker}", tags=["Knowledge Graph"])
async def get_network(ticker: str):
    data = get_company_network(ticker)

    if not data.get("nodes"):
        raise HTTPException(
            status_code=404,
            detail=f"No graph network found for {ticker}",
        )

    return json_safe(data)


@app.get("/api/graph/centrality", tags=["Knowledge Graph"])
async def get_centrality(top_n: int = 20):
    df = calculate_board_centrality(top_n=top_n)

    return dataframe_to_json_records(df)


@app.get("/api/graph/cross-holdings", tags=["Knowledge Graph"])
async def get_cross():
    return json_safe(
        detect_cross_holdings()
    )


@app.post("/api/query/sql", tags=["Analytics"])
async def execute_sql(req: SQLQueryRequest):
    if _is_production_env():
        raise HTTPException(
            status_code=403,
            detail="SQL analytics endpoint is disabled in production.",
        )

    sql = req.sql.strip()
    lowered = sql.lower()

    disallowed = [
        "insert ",
        "update ",
        "delete ",
        "drop ",
        "create ",
        "alter ",
        "truncate ",
        "attach ",
        "copy ",
        "export ",
        "pragma ",
        "install ",
        "load ",
        "call ",
    ]

    if any(word in lowered for word in disallowed):
        raise HTTPException(
            status_code=400,
            detail="Only read-only SELECT queries are allowed.",
        )
    if ";" in sql.rstrip(";"):
        raise HTTPException(
            status_code=400,
            detail="Multi-statement SQL is not allowed.",
        )
    if not lowered.lstrip().startswith("select"):
        raise HTTPException(
            status_code=400,
            detail="Only SELECT queries are allowed.",
        )

    import duckdb

    con = duckdb.connect(database=":memory:")

    table_names = [
        "stock_summary",
        "financial_ratios",
        "corporate_actions",
        "broker_summary",
        "index_summary",
    ]

    for name in table_names:

        p_file = os.path.join(
            DATA_DIR,
            "parquet",
            f"{name}.parquet",
        )

        if os.path.exists(p_file):
            con.execute(
                f"CREATE OR REPLACE VIEW {name} "
                f"AS SELECT * FROM read_parquet('{p_file}')"
            )

    try:

        res_df = con.execute(sql).fetchdf()

        return dataframe_to_json_records(
            res_df.head(req.limit)
        )

    except Exception as e:

        raise HTTPException(
            status_code=400,
            detail=safe_http_detail(e, public="Invalid query"),
        ) from e

    finally:
        con.close()


@app.get("/api/stealth-accumulation", tags=["Bandarmology"])
async def get_stealth_accumulation(
    date: str | None = None,
    lookback_days: int = 5,
    min_turnover_rp: float = 1e9,
):
    cache_key = f"stealth:{date or 'latest'}:{lookback_days}:{min_turnover_rp}"
    cached = get_from_cache(cache_key, ttl_seconds=60.0)
    if cached is not None:
        return cached

    import pandas as pd

    from idx.signals import detect_stealth_accumulation

    broker_path = os.path.join(
        DATA_DIR,
        "parquet",
        "broker_summary.parquet",
    )

    stock_path = os.path.join(
        DATA_DIR,
        "parquet",
        "stock_summary.parquet",
    )

    broker_df = (
        pd.read_parquet(broker_path)
        if os.path.exists(broker_path)
        else pd.DataFrame()
    )

    stock_df = (
        pd.read_parquet(stock_path)
        if os.path.exists(stock_path)
        else pd.DataFrame()
    )

    res = detect_stealth_accumulation(
        broker_df,
        stock_df,
        on_date=date,
        lookback_days=lookback_days,
        min_turnover_rp=min_turnover_rp,
    )

    result = {
        "summary": json_safe(
            res["summary"]
        ),
        "signal": json_safe(
            res["signal"]
        ),
        "smart_money_delta": json_safe(
            res["smart_money_delta"]
        ),
        "anomalies": dataframe_to_json_records(
            res["anomalies_df"]
        ),
    }
    set_in_cache(cache_key, result)
    return result


@app.post("/api/backtest", tags=["Backtesting"])
async def backtest_strategy(
    req: BacktestRequest,
):
    import numpy as np

    from idx.backtest import run_backtest

    try:

        metrics, trades_df = run_backtest(
            strategy=req.strategy,
            holding_days=req.holding_days,
            top_n=req.top_n,
            min_turnover_rp=req.min_turnover_rp,
            start_date=req.start_date,
            end_date=req.end_date,
            stop_loss_pct=req.stop_loss_pct,
            take_profit_pct=req.take_profit_pct,
            position_sizing=req.position_sizing,
        )

        cleaned_metrics = {}

        for key, value in metrics.items():

            if isinstance(
                value,
                (float, np.floating),
            ):

                if np.isnan(value) or np.isinf(value):
                    cleaned_metrics[key] = None
                else:
                    cleaned_metrics[key] = (
                        value.item()
                        if hasattr(value, "item")
                        else value
                    )

            else:
                cleaned_metrics[key] = json_safe(value)

        # CAGR must never be a silent alias of total return at the API boundary.
        if cleaned_metrics.get("cagr_pct") is not None and cleaned_metrics.get(
            "total_return_pct"
        ) is not None:
            if cleaned_metrics["cagr_pct"] == cleaned_metrics["total_return_pct"]:
                cleaned_metrics["cagr_pct"] = None

        trades_list: list[dict] = []
        equity_curve: list[dict[str, object]] = []

        if len(trades_df) > 0:

            trades_df_sorted = trades_df.sort_values(
                ["ExitDate", "EntryDate", "StockCode"]
            )

            running_equity = 100.0

            first_entry = str(trades_df_sorted.iloc[0]["EntryDate"])

            equity_curve.append(
                {
                    "time": first_entry,
                    "value": 100.0,
                }
            )

            # Equal-weight mean return per ExitDate — matches engine portfolio metrics.
            for exit_dt, group in trades_df_sorted.groupby("ExitDate", sort=True):
                avg_period_return = float(group["Return"].mean())
                if not math.isfinite(avg_period_return):
                    continue
                running_equity *= 1.0 + avg_period_return
                if not math.isfinite(running_equity):
                    running_equity = equity_curve[-1]["value"]  # type: ignore[index]
                    break
                equity_curve.append(
                    {
                        "time": str(exit_dt),
                        "value": round(float(running_equity), 2),
                    }
                )

            trades_clean = (
                trades_df_sorted.replace({np.nan: None})
                .sort_values("ExitDate", ascending=False)
                .head(100)
            )

            trades_list = dataframe_to_json_records(trades_clean)

            # Ensure trade count reflects the full engine set, not the truncated table.
            cleaned_metrics["total_trades"] = int(len(trades_df))
            cleaned_metrics["trades_returned"] = int(len(trades_list))

        else:
            # No fabricated placeholder date — empty curve for zero-trade runs.
            equity_curve = []
            cleaned_metrics["total_trades"] = int(
                cleaned_metrics.get("total_trades") or 0
            )
            cleaned_metrics["trades_returned"] = 0

        return {
            "metrics": cleaned_metrics,
            "equity_curve": equity_curve,
            "trades": trades_list,
        }

    except Exception as e:

        raise HTTPException(
            status_code=400,
            detail=safe_http_detail(e, public="Backtest failed"),
        ) from e


class ConnectionManager:
    """Manages active WebSocket client connections."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(
        self,
        websocket: WebSocket,
    ):
        await websocket.accept()
        self.active_connections.append(
            websocket
        )

    def disconnect(
        self,
        websocket: WebSocket,
    ):
        if websocket in self.active_connections:
            self.active_connections.remove(
                websocket
            )

    async def broadcast(
        self,
        message: dict,
    ):
        payload = json.dumps(
            message,
            default=str,
            allow_nan=False,
        )

        dead = []

        for conn in self.active_connections:

            try:
                await conn.send_text(
                    payload
                )

            except Exception:
                dead.append(conn)

        for connection in dead:
            self.disconnect(connection)


ws_manager = ConnectionManager()


@app.post("/api/broadcast", tags=["System"])
async def broadcast_event(event: dict):
    await ws_manager.broadcast(event)

    return {
        "status": "broadcast_sent",
        "active_clients": len(
            ws_manager.active_connections
        ),
    }


@app.get(
    "/api/system/ingestion-status",
    tags=["Ingestion & Data Pipeline"],
)
async def api_ingestion_status():
    return get_full_ingestion_status()


@app.post(
    "/api/system/trigger-ingestion",
    tags=["Ingestion & Data Pipeline"],
)
async def api_trigger_ingestion(
    req: TriggerIngestionRequest,
):
    import uuid

    from idx.ingestion import (
        normalize_backfill_date_range,
        validate_ownership_path_or_url,
    )

    if req.job_type not in _ALLOWED_INGESTION_JOB_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported job_type '{req.job_type}'. "
                f"Allowed: {sorted(_ALLOWED_INGESTION_JOB_TYPES)}"
            ),
        )

    params: dict = {
        "date": req.date,
        "start_date": req.start_date,
        "end_date": req.end_date,
        "concurrency": req.concurrency,
        "path_or_url": req.path_or_url,
    }

    # Fail fast with clear errors (no invented defaults).
    if req.job_type == "backfill":
        try:
            start, end = normalize_backfill_date_range(req.start_date, req.end_date)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        params["start_date"] = start
        params["end_date"] = end
    elif req.job_type == "ownership":
        try:
            params["path_or_url"] = validate_ownership_path_or_url(req.path_or_url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    job_id = (
        f"job-{uuid.uuid4().hex[:8]}"
    )

    asyncio.create_task(
        run_async_ingestion_job(
            job_id=job_id,
            job_type=req.job_type,
            params=params,
            broadcast_callback=ws_manager.broadcast,
        )
    )

    label = {
        "daily": "Daily market-close",
        "backfill": "Historical backfill",
        "sync_all": "Sync All Data",
        "ownership": "Ownership (KSEI) ingest",
    }.get(req.job_type, req.job_type)

    return {
        "job_id": job_id,
        "status": "scheduled",
        "job_type": req.job_type,
        "message": f"{label} job triggered in background.",
        "params": {
            k: params[k]
            for k in ("start_date", "end_date", "path_or_url", "concurrency", "date")
            if params.get(k) is not None
        },
    }


@app.get(
    "/api/system/jobs",
    tags=["Ingestion & Data Pipeline"],
)
async def api_list_jobs(limit: int = 10):
    return list_recent_jobs(limit=limit)


@app.get(
    "/api/system/jobs/{job_id}",
    tags=["Ingestion & Data Pipeline"],
)
async def api_get_job(job_id: str):
    job = get_job_status(job_id)

    if not job:
        raise HTTPException(
            status_code=404,
            detail=f"Job '{job_id}' not found.",
        )

    return job


@app.websocket("/ws/stream")
async def websocket_stream(
    websocket: WebSocket,
):
    await ws_manager.connect(websocket)

    try:

        await websocket.send_text(
            json.dumps(
                {
                    "type": "handshake",
                    "status": "connected",
                    "service": "idx-microservice-stream",
                    "timestamp": (
                        asyncio
                        .get_event_loop()
                        .time()
                    ),
                },
                allow_nan=False,
            )
        )

        while True:

            try:

                msg = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=5.0,
                )

                data = json.loads(msg)

                if data.get("type") == "ping":

                    await websocket.send_text(
                        json.dumps(
                            {
                                "type": "pong",
                                "time": (
                                    asyncio
                                    .get_event_loop()
                                    .time()
                                ),
                            },
                            allow_nan=False,
                        )
                    )

            except TimeoutError:

                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "heartbeat",
                            "status": "alive",
                            "timestamp": (
                                asyncio
                                .get_event_loop()
                                .time()
                            ),
                            "connected_clients": len(
                                ws_manager.active_connections
                            ),
                        },
                        allow_nan=False,
                    )
                )

    except WebSocketDisconnect:

        ws_manager.disconnect(websocket)

    except Exception:

        ws_manager.disconnect(websocket)


def run_server(
    host: str = "0.0.0.0",
    port: int = 8000,
):
    import uvicorn

    uvicorn.run(
        app,
        host=host,
        port=port,
    )


if __name__ == "__main__":
    run_server()
