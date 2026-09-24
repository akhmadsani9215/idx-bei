"""
Data Ingestion Status, Timeseries Gap Detection, and Backfill Recommendation Engine.
"""

from __future__ import annotations

import datetime
import glob
import os
from typing import Any

from idx.core import timeseries as ts
from idx.core.utils import DATA_DIR, get_logger, load_json
from idx.scrapers.historical import _trading_days

log = get_logger("idx.ingestion")

# Official IDX Public Holidays / Non-trading Weekdays for 2026
KNOWN_IDX_HOLIDAYS_2026 = {
    "2026-01-01": "Tahun Baru 2026 Masehi",
    "2026-01-16": "Isra Mi'raj Nabi Muhammad SAW",
    "2026-02-16": "Cuti Bersama Tahun Baru Imlek 2577",
    "2026-02-17": "Tahun Baru Imlek 2577 Kongzili",
    "2026-03-18": "Cuti Bersama Hari Suci Nyepi",
    "2026-03-19": "Hari Suci Nyepi Tahun Baru Saka 1948",
    "2026-03-20": "Cuti Bersama Hari Raya Idul Fitri 1447 H",
    "2026-03-23": "Hari Raya Idul Fitri 1447 H",
    "2026-03-24": "Hari Raya Idul Fitri 1447 H",
    "2026-04-03": "Wafat Isa Al Masih (Good Friday)",
    "2026-05-01": "Hari Buruh Internasional",
    "2026-05-14": "Kenaikan Isa Al Masih",
    "2026-05-15": "Cuti Bersama Kenaikan Isa Al Masih",
    "2026-05-27": "Cuti Bersama Hari Raya Idul Adha 1447 H",
    "2026-05-28": "Hari Raya Idul Adha 1447 H",
    "2026-06-01": "Hari Lahir Pancasila",
    "2026-06-16": "Tahun Baru Islam 1448 H",
    "2026-08-17": "Hari Kemerdekaan RI Ke-81",
    "2026-08-25": "Maulid Nabi Muhammad SAW (12 Rabi'ul Awwal 1448 H)",
    "2026-12-24": "Cuti Bersama Hari Raya Natal",
    "2026-12-25": "Hari Raya Natal",
}


def get_idx_holidays(year: int | None = None, base_dir: str | None = None) -> dict[str, str]:
    """Retrieves IDX public holidays and non-trading days with local cache support.

    Merges static 2026 holiday calendar with any custom or cached entries in data/idx_holidays.json.
    """
    root = base_dir or DATA_DIR
    holidays = dict(KNOWN_IDX_HOLIDAYS_2026)
    cache_path = os.path.join(root, "idx_holidays.json")
    if os.path.exists(cache_path):
        try:
            cached = load_json(cache_path)
            if isinstance(cached, dict):
                holidays.update(cached)
        except Exception as e:
            log.warning("Failed to load custom holiday cache %s: %s", cache_path, e)

    if year is not None:
        prefix = f"{year:04d}-"
        return {d: name for d, name in holidays.items() if d.startswith(prefix)}
    return holidays



def _file_info(path: str) -> dict[str, Any]:
    """Helper to get file size and last modified time."""
    if not os.path.exists(path):
        return {"exists": False, "size_bytes": 0, "size_mb": 0.0, "modified_iso": None}
    stat = os.stat(path)
    return {
        "exists": True,
        "size_bytes": stat.st_size,
        "size_mb": round(stat.st_size / (1024 * 1024), 2),
        "modified_iso": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
    }


def _parse_flexible_timestamp(value: str | None) -> datetime.datetime | None:
    """Parse ISO / common datetime strings into naive local datetimes. No invented clocks."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    # Normalize trailing Z / timezone offset for fromisoformat
    if text.endswith("Z"):
        text = text[:-1]
    try:
        return datetime.datetime.fromisoformat(text)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def get_dataset_inventory(base_dir: str | None = None) -> dict[str, Any]:
    """Inspects all local storage partitions, Parquet exports, and snapshots.

    Returns:
        Structured dictionary of dataset statistics.
    """
    root = base_dir or DATA_DIR
    ts_root = os.path.join(root, "timeseries")
    parquet_root = os.path.join(root, "parquet")

    inventory: dict[str, Any] = {
        "timeseries": {},
        "parquet_exports": {},
        "fundamental_snapshots": {},
        "ksei_drift": {},
        "system": {},
    }

    # 1. Timeseries Partitioned Datasets
    for ds in ts.DATASETS:
        dates_map = ts.existing_dates(ds, base_dir=ts_root)
        sorted_dates = sorted(dates_map.keys())

        # Calculate partition files size
        ds_dir = os.path.join(ts_root, ds)
        part_files = glob.glob(os.path.join(ds_dir, "date=*.parquet"))
        compacted_files = glob.glob(os.path.join(ds_dir, "year=*", "month=*.parquet"))
        total_size = sum(
            os.path.getsize(f) for f in part_files + compacted_files if os.path.exists(f)
        )

        inventory["timeseries"][ds] = {
            "total_dates": len(sorted_dates),
            "start_date": sorted_dates[0] if sorted_dates else None,
            "end_date": sorted_dates[-1] if sorted_dates else None,
            "daily_partitions_count": len(part_files),
            "compacted_partitions_count": len(compacted_files),
            "total_size_mb": round(total_size / (1024 * 1024), 2),
        }

    # 2. Consolidated Parquet Datasets
    for ds in [
        "stock_summary",
        "broker_summary",
        "index_summary",
        "financial_ratios",
        "corporate_actions",
    ]:
        p_path = os.path.join(parquet_root, f"{ds}.parquet")
        finfo = _file_info(p_path)
        row_count = 0
        if finfo["exists"]:
            try:
                import pyarrow.parquet as pq

                meta = pq.read_metadata(p_path)
                row_count = meta.num_rows
            except Exception:
                row_count = 0

        inventory["parquet_exports"][ds] = {
            "exists": finfo["exists"],
            "row_count": row_count,
            "size_mb": finfo["size_mb"],
            "modified_iso": finfo["modified_iso"],
        }

    # 3. Fundamental & Governance Snapshots
    all_comp_file = os.path.join(root, "allCompanies.json")
    comp_details_file = os.path.join(root, "companyDetailsByKodeEmiten.json")
    fin_ratio_file = os.path.join(root, "financial_ratio.json")
    corp_act_file = os.path.join(root, "corporateActions.json")
    broker_file = os.path.join(root, "brokerSearch.json")

    total_listed = 0
    if os.path.exists(all_comp_file):
        try:
            data = load_json(all_comp_file)
            total_listed = len(data) if isinstance(data, list) else len(data.get("data", []))
        except Exception:
            pass

    detailed_profiles = 0
    if os.path.exists(comp_details_file):
        try:
            d_data = load_json(comp_details_file)
            detailed_profiles = len(d_data) if isinstance(d_data, dict) else 0
        except Exception:
            pass

    inventory["fundamental_snapshots"] = {
        "total_listed_companies": total_listed,
        "detailed_profiles_scraped": detailed_profiles,
        "profile_coverage_pct": (
            round((detailed_profiles / total_listed * 100), 1) if total_listed else 0.0
        ),
        "financial_ratios": _file_info(fin_ratio_file),
        "corporate_actions": _file_info(corp_act_file),
        "broker_directory": _file_info(broker_file),
    }

    # 4. KSEI 1%+ Shareholder Drift & Ownership
    ksei_files = glob.glob(os.path.join(root, "*ownership*.csv"))
    ksei_meta = []
    for kf in sorted(ksei_files):
        ksei_meta.append({"file": os.path.basename(kf), **_file_info(kf)})
    inventory["ksei_drift"] = {
        "files_count": len(ksei_files),
        "files": ksei_meta,
    }

    # 5. Currency & Rates — honest lineage (never imply default is a live quote)
    from idx.core.currency import resolve_usd_idr_quote

    usd_quote = resolve_usd_idr_quote(force_refresh=False, allow_default=True)
    inventory["system"]["usd_idr"] = {
        "rate": usd_quote.get("rate"),
        "status": usd_quote.get("status"),
        "source": usd_quote.get("source"),
        "origin": usd_quote.get("origin"),
        "quality": usd_quote.get("quality"),
        "confidence": usd_quote.get("confidence"),
        "is_live": usd_quote.get("is_live"),
        "is_market_quote": usd_quote.get("is_market_quote"),
        "is_default_constant": usd_quote.get("is_default_constant"),
        "is_verified_fx": usd_quote.get("is_verified_fx"),
        "notes": usd_quote.get("notes"),
        "last_updated": usd_quote.get("as_of"),
    }

    return inventory


def detect_timeseries_gaps(
    dataset: str = "stock_summary",
    start_date: str = "2026-01-01",
    end_date: str | None = None,
    base_dir: str | None = None,
) -> dict[str, Any]:
    """Detects missing dates in the timeseries against expected weekday trading sessions.

    Separates official Indonesian holidays from true missing trading days.
    """
    if end_date is None:
        end_date = datetime.date.today().strftime("%Y-%m-%d")

    ts_root = os.path.join(base_dir or DATA_DIR, "timeseries")
    existing = ts.existing_dates(dataset, base_dir=ts_root)

    expected_weekdays = [d.strftime("%Y-%m-%d") for d in _trading_days(start_date, end_date)]
    all_missing = [d for d in expected_weekdays if d not in existing]

    holidays_map = get_idx_holidays(base_dir=base_dir)
    holidays = []
    true_missing = []

    for d in all_missing:
        if d in holidays_map:
            holidays.append({"date": d, "holiday_name": holidays_map[d]})
        else:
            true_missing.append(d)

    total_weekdays = len(expected_weekdays)
    ingested_days = len(expected_weekdays) - len(all_missing)
    expected_active_trading_days = total_weekdays - len(holidays)
    coverage_pct = (
        round((ingested_days / expected_active_trading_days * 100.0), 1)
        if expected_active_trading_days > 0
        else 100.0
    )

    return {
        "dataset": dataset,
        "start_date": start_date,
        "end_date": end_date,
        "total_calendar_weekdays": total_weekdays,
        "ingested_days": ingested_days,
        "official_holidays_count": len(holidays),
        "official_holidays": holidays,
        "true_missing_trading_days_count": len(true_missing),
        "true_missing_trading_days": true_missing,
        "coverage_percentage": min(coverage_pct, 100.0),
    }


def calculate_backfill_recommendations(
    base_dir: str | None = None,
    current_date: str | None = None,
) -> dict[str, Any]:
    """Generates rigorous quantitative recommendations on how much historical data to backfill.

    Evaluates:
    - Tier 1: Immediate Gap Repair & Daily Ingestion (late August to current date)
    - Tier 2: 1-Year Baseline (2025-01-01 to 2025-12-31) -> ~248 trading days
    - Tier 3: 3-Year Multi-Cycle (2023-01-01 to 2024-12-31) -> ~496 trading days
    - Tier 4: 5-Year Deep Macro History (2021-01-01 to 2022-12-31) -> ~500 trading days
    """
    if current_date is None:
        current_date = datetime.date.today().strftime("%Y-%m-%d")

    # Inspect current gaps in 2026
    gap_info = detect_timeseries_gaps(
        dataset="stock_summary",
        start_date="2026-01-01",
        end_date=current_date,
        base_dir=base_dir,
    )

    missing_recent = gap_info["true_missing_trading_days"]
    has_gaps = len(missing_recent) > 0

    tiers = [
        {
            "tier": 1,
            "id": "tier_1_immediate_gap_repair",
            "name": "2026 YTD Gap Repair & Latest Market Close",
            "priority": "HIGH (CRITICAL)" if has_gaps else "COMPLETED (100% UP TO DATE)",
            "description": (
                f"Fills {len(missing_recent)} un-ingested 2026 trading sessions."
                if has_gaps
                else "All 2026 weekday trading sessions are fully ingested with 0 gaps! Run daily ingestion at market close."
            ),
            "target_range": {
                "start": missing_recent[0] if has_gaps else current_date,
                "end": current_date,
            },
            "trading_days_to_fetch": len(missing_recent),
            "estimated_payload_mb": round(len(missing_recent) * 0.45, 1),
            "estimated_runtime_seconds_c8": max(5, int(len(missing_recent) * 1.5)),
            "unlocked_capabilities": [
                "Real-time Bandarmology broker dominance for recent sessions",
                "Accurate technical indicators (RSI-14, MACD, Bollinger Bands) up to latest close",
                "Current net foreign institutional flow alignment",
            ],
            "recommended_cli_commands": (
                [
                    f"uv run idx backfill --start {missing_recent[0].replace('-', '')} --end {current_date.replace('-', '')} --concurrency 4",
                    "uv run idx daily",
                ]
                if has_gaps
                else ["uv run idx daily"]
            ),
        },
        {
            "tier": 2,
            "id": "tier_2_one_year_baseline",
            "name": "1-Year Baseline Historical Backfill (2025 Full Year)",
            "priority": "RECOMMENDED (BEST VALUE)",
            "description": "Ingests full calendar year 2025 data. This is the optimal quant baseline for medium-term strategies without network strain.",
            "target_range": {
                "start": "2025-01-02",
                "end": "2025-12-30",
            },
            "trading_days_to_fetch": 246,
            "estimated_payload_mb": 110.0,
            "estimated_runtime_seconds_c8": 210,  # ~3.5 minutes at concurrency 8
            "unlocked_capabilities": [
                "200-day Simple & Exponential Moving Averages (SMA-200 / EMA-200)",
                "Full 52-week High/Low price channel breakouts",
                "12-month trailing foreign institutional accumulation cycles",
                "Authentic 1-year backtesting of Foreign Flow and Bandarmology strategies",
            ],
            "recommended_cli_commands": [
                "uv run idx backfill --start 20250101 --end 20251231 --concurrency 4",
                "uv run idx parquet",
                "uv run idx compact",
            ],
        },
        {
            "tier": 3,
            "id": "tier_3_three_year_multicycle",
            "name": "3-Year Multi-Cycle Strategy Simulator Dataset (2023–2024)",
            "priority": "HIGH VALUE FOR BACKTESTING",
            "description": "Extends history across the 2023–2024 monetary tightening and global commodity shifts, providing statistical significance.",
            "target_range": {
                "start": "2023-01-02",
                "end": "2024-12-30",
            },
            "trading_days_to_fetch": 494,
            "estimated_payload_mb": 220.0,
            "estimated_runtime_seconds_c8": 420,  # ~7 minutes
            "unlocked_capabilities": [
                "Statistically rigorous Sharpe and Sortino ratios (>500 trades)",
                "Cross-regime validation: Bull (2023 H2), Sideways (2024 H1), and Volatility regimes",
                "Dividend Arbitrage multi-year seasonality: Pre-Cum exit vs Post-Ex rebuy performance",
                "Tycoon conglomerate power shifts and long-horizon accumulation arcs",
            ],
            "recommended_cli_commands": [
                "uv run idx backfill --start 20230101 --end 20241231 --concurrency 4",
                "uv run idx parquet",
                "uv run idx compact",
            ],
        },
        {
            "tier": 4,
            "id": "tier_4_five_year_macro",
            "name": "5-Year Deep Macro History (2021–2022)",
            "priority": "OPTIONAL / RESEARCH ONLY",
            "description": "Complete post-COVID economic recovery cycle and long-term dividend compounder verification.",
            "target_range": {
                "start": "2021-01-04",
                "end": "2022-12-30",
            },
            "trading_days_to_fetch": 498,
            "estimated_payload_mb": 215.0,
            "estimated_runtime_seconds_c8": 430,
            "unlocked_capabilities": [
                "5-year dividend CAGR and dividend trap historical resilience",
                "Long-term UBO and conglomerate restructuring tracking",
                "Full post-pandemic recovery macro backtesting",
            ],
            "recommended_cli_commands": [
                "uv run idx backfill --start 20210101 --end 20221231 --concurrency 4",
                "uv run idx parquet",
                "uv run idx compact",
            ],
        },
    ]

    return {
        "as_of_date": current_date,
        "summary": {
            "current_status": (
                f"2026 YTD partially ingested ({len(missing_recent)} missing sessions)"
                if has_gaps
                else f"2026 YTD is 100% complete ({gap_info['ingested_days']} trading sessions ingested, 0 gaps)"
            ),
            "immediate_gaps_count": len(missing_recent),
            "immediate_gaps": missing_recent,
            "recommended_action": (
                "Backfill Tier 1 (immediate 2026 gaps) first, followed by Tier 2 (2025 1-Year Baseline) for 200-day moving averages and full backtesting power."
                if has_gaps
                else "2026 YTD has zero gaps! Proceed to Tier 2 (2025 1-Year Baseline) to unlock 200-day moving averages (SMA-200 / EMA-200) and full 52-week channels."
            ),
        },
        "tiers": tiers,
    }


# Track active and recent background ingestion jobs
_INGESTION_JOBS: dict[str, dict[str, Any]] = {}
_JOB_TASKS: dict[str, Any] = {}
MAX_JOB_HISTORY = 50
JOB_HISTORY_FILE = os.path.join(DATA_DIR, ".ingestion_job_history.json")
_PERSISTED_JOB_FIELDS = (
    "job_id",
    "type",
    "params",
    "status",
    "progress_pct",
    "message",
    "created_at",
    "completed_at",
    "duration_s",
)
_LAST_SYNC_ALL: dict[str, Any] | None = None
_LAST_HISTORICAL_RUN: dict[str, Any] | None = None
_LAST_OWNERSHIP_RUN: dict[str, Any] | None = None

_MARKET_DATASETS = ("stock_summary", "broker_summary", "index_summary")

# Data Center pipeline catalog — honesty over completeness.
PIPELINE_CATALOG: list[dict[str, Any]] = [
    {
        "id": "market_eod",
        "label": "Market / EOD",
        "availability": "AVAILABLE",
        "source": "IDX TradingSummary GetStockSummary + GetIndexSummary via ingest_daily",
        "notes": "Daily market-close stock and index summaries.",
    },
    {
        "id": "financial",
        "label": "Financial / Fundamental",
        "availability": "AVAILABLE",
        "source": "IDX financial ratio scraper → financial_ratio.json → financial_ratios.parquet",
        "notes": "Snapshot fundamental ratios (not full company-detail backfill).",
    },
    {
        "id": "foreign",
        "label": "Foreign",
        "availability": "PARTIAL",
        "source": "stock_summary ForeignBuy/ForeignSell (embedded in Market / EOD)",
        "notes": "No dedicated foreign-flow sync; arrives with stock EOD.",
    },
    {
        "id": "historical",
        "label": "Historical",
        "availability": "PARTIAL",
        "source": "async backfill stock/broker/index (requires explicit start/end)",
        "notes": "Manual backfill requires date range. Not auto-run by Sync All.",
    },
    {
        "id": "ownership",
        "label": "Ownership",
        "availability": "UNAVAILABLE",
        "source": None,
        "notes": (
            "KSEI ownership ingest requires an explicit local CSV path or http(s) URL "
            "(job_type=ownership + path_or_url). Not in Sync All — no default source."
        ),
    },
    {
        "id": "broker",
        "label": "Broker",
        "availability": "AVAILABLE",
        "source": "IDX TradingSummary GetBrokerSummary via ingest_daily",
        "notes": "Broker concentration source; not institutional/retail attribution.",
    },
    {
        "id": "feature_rebuild",
        "label": "Feature Rebuild",
        "availability": "PARTIAL",
        "source": "idx.rebuild.rebuild_features ← stock_summary (read-only cache)",
        "notes": (
            "On-read structure feature snapshot to .feature_rebuild_cache.json. "
            "Does not mutate source partitions."
        ),
    },
    {
        "id": "signal_rebuild",
        "label": "Signal Rebuild",
        "availability": "AVAILABLE",
        "source": "idx.signals.build_briefing over Parquet exports",
        "notes": "Rebuilds daily decision-support briefing artifacts.",
    },
    {
        "id": "target_risk",
        "label": "Target / Risk",
        "availability": "PARTIAL",
        "source": "idx.rebuild.rebuild_target_risk ← screener structure levels",
        "notes": (
            "Deterministic TP/CL snapshot cache. Does not mutate source. "
            "Not a durable feature store."
        ),
    },
    {
        "id": "screener_rebuild",
        "label": "Screener Rebuild",
        "availability": "AVAILABLE",
        "source": "analyze_network_alpha.run_analysis_pipeline → network_alpha_data.json",
        "notes": "Regenerates screener/AlphaHub cache snapshot.",
    },
]

INTEGRATION_STATUS = {
    "realtime": "NOT_CONFIGURED",
    "ai": "NOT_CONFIGURED",
    "telegram": "NOT_CONFIGURED",
    "payment": "NOT_CONFIGURED",
}


def build_freshness_contract(
    inventory: dict[str, Any],
    base_dir: str | None = None,
    jobs: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Operational freshness: last completed job, market partitions, screener snapshot age.

    Timestamps come only from job registry evidence, filesystem mtimes, partition dates,
    or file content fields — never from the API request clock.
    """
    root = base_dir or DATA_DIR
    job_registry = jobs if jobs is not None else _INGESTION_JOBS

    # 1) Last successful ingestion job (status==completed only)
    completed_jobs = [
        j for j in job_registry.values() if isinstance(j, dict) and j.get("status") == "completed"
    ]
    last_job: dict[str, Any] | None = None
    if completed_jobs:
        last_job = max(
            completed_jobs,
            key=lambda j: j.get("completed_at") or j.get("created_at") or "",
        )

    last_successful_ingestion: dict[str, Any] = {
        "available": last_job is not None,
        "job_id": last_job.get("job_id") if last_job else None,
        "job_type": last_job.get("type") if last_job else None,
        "completed_at": last_job.get("completed_at") if last_job else None,
        "source": "in_memory_job_registry" if last_job else None,
        "note": (
            None if last_job else "No completed ingestion job recorded in this server process."
        ),
    }

    # 2) Market partition / as-of dates from inventory
    partitions: dict[str, Any] = {}
    for ds in _MARKET_DATASETS:
        meta = inventory.get("timeseries", {}).get(ds, {})
        partitions[ds] = {
            "end_date": meta.get("end_date"),
            "start_date": meta.get("start_date"),
            "total_dates": meta.get("total_dates", 0),
        }
    stock_end = partitions.get("stock_summary", {}).get("end_date")
    parquet_exports = inventory.get("parquet_exports", {})
    parquet_modified: dict[str, str | None] = {}
    for ds in _MARKET_DATASETS:
        parquet_modified[ds] = parquet_exports.get(ds, {}).get("modified_iso")

    market_data = {
        "as_of_date": stock_end,
        "partitions": partitions,
        "parquet_modified_iso": parquet_modified,
    }

    # 3) Screener snapshot (network_alpha_data.json) actual file freshness
    alpha_path = os.path.join(root, "network_alpha_data.json")
    alpha_info = _file_info(alpha_path)
    content_last_updated: str | None = None
    if alpha_info["exists"]:
        try:
            alpha_payload = load_json(alpha_path)
            if isinstance(alpha_payload, dict):
                raw = alpha_payload.get("last_updated")
                content_last_updated = raw if isinstance(raw, str) else None
        except Exception:
            content_last_updated = None

    screener_snapshot = {
        "file": "network_alpha_data.json",
        "exists": alpha_info["exists"],
        "modified_iso": alpha_info["modified_iso"],
        "content_last_updated": content_last_updated,
    }

    # 4) Relationship / mismatch
    screener_ts = _parse_flexible_timestamp(alpha_info["modified_iso"])
    if screener_ts is None:
        screener_ts = _parse_flexible_timestamp(content_last_updated)

    evidence_candidates: list[tuple[datetime.datetime, str]] = []
    job_ts = _parse_flexible_timestamp(
        last_successful_ingestion["completed_at"]
        if last_successful_ingestion["available"]
        else None
    )
    if job_ts is not None:
        evidence_candidates.append((job_ts, "last_successful_job.completed_at"))

    for ds, ts_iso in parquet_modified.items():
        parsed = _parse_flexible_timestamp(ts_iso)
        if parsed is not None:
            evidence_candidates.append((parsed, f"parquet_exports.{ds}.modified_iso"))

    ingestion_evidence_ts: datetime.datetime | None = None
    ingestion_evidence_source: str | None = None
    if evidence_candidates:
        ingestion_evidence_ts, ingestion_evidence_source = max(
            evidence_candidates, key=lambda item: item[0]
        )

    status = "unknown"
    screener_lagging = False
    warning: str | None = None
    comparison_basis: str | None = None

    if not alpha_info["exists"]:
        status = "screener_missing"
        screener_lagging = True
        warning = (
            "Screener cache file network_alpha_data.json is missing. "
            "Market ingestion/partitions may be newer than AlphaHub/screener data."
        )
        comparison_basis = "screener_file_missing"
    elif screener_ts is None and ingestion_evidence_ts is None:
        status = "unknown"
        comparison_basis = "insufficient_timestamps"
    elif ingestion_evidence_ts is not None and screener_ts is not None:
        comparison_basis = f"{ingestion_evidence_source}_vs_screener.modified_iso"
        # Small skew tolerance (2s) for same-write races
        if ingestion_evidence_ts > screener_ts + datetime.timedelta(seconds=2):
            status = "screener_stale"
            screener_lagging = True
            warning = (
                "Market ingestion evidence is newer than the screener snapshot "
                "(network_alpha_data.json). Screener/AlphaHub may lag Sync Market Close."
            )
        else:
            status = "current"
            screener_lagging = False
            warning = None
    elif stock_end and content_last_updated:
        # Date-level fallback when only partition date + content last_updated exist
        market_date = _parse_flexible_timestamp(stock_end)
        content_ts = _parse_flexible_timestamp(content_last_updated)
        if market_date is not None and content_ts is not None:
            comparison_basis = "market_partitions.as_of_date_vs_screener.content_last_updated"
            if market_date.date() > content_ts.date():
                status = "screener_stale"
                screener_lagging = True
                warning = (
                    f"Latest market partition ({stock_end}) is after screener content "
                    f"last_updated ({content_last_updated}). Screener snapshot appears stale."
                )
            else:
                status = "current"
                screener_lagging = False
                warning = None
        else:
            status = "unknown"
            comparison_basis = "unparseable_date_fallback"
    else:
        status = "unknown"
        comparison_basis = "partial_evidence"

    return {
        "last_successful_ingestion": last_successful_ingestion,
        "market_data": market_data,
        "screener_snapshot": screener_snapshot,
        "status": status,
        "screener_lagging": screener_lagging,
        "warning": warning,
        "comparison_basis": comparison_basis,
        "ingestion_evidence_at": (
            ingestion_evidence_ts.isoformat() if ingestion_evidence_ts else None
        ),
        "ingestion_evidence_source": ingestion_evidence_source,
    }


def get_full_ingestion_status(base_dir: str | None = None) -> dict[str, Any]:
    """Unified status payload combining inventory, gap detection, and backfill recommendations."""
    inventory = get_dataset_inventory(base_dir=base_dir)
    gaps = detect_timeseries_gaps(dataset="stock_summary", base_dir=base_dir)
    recommendations = calculate_backfill_recommendations(base_dir=base_dir)
    freshness = build_freshness_contract(inventory, base_dir=base_dir)

    # Health score calculation (0 - 100)
    health_score = 100
    if gaps["true_missing_trading_days_count"] > 0:
        health_score -= min(30, gaps["true_missing_trading_days_count"] * 3)

    stock_ts = inventory["timeseries"].get("stock_summary", {})
    if stock_ts.get("total_dates", 0) < 200:
        health_score -= 15  # lacks 1-year history

    profile_pct = inventory["fundamental_snapshots"].get("profile_coverage_pct", 0)
    if profile_pct < 80.0:
        health_score -= 10

    return {
        "status": "healthy"
        if health_score >= 75
        else ("warning" if health_score >= 50 else "critical"),
        "health_score": max(0, health_score),
        "inventory": inventory,
        "gaps": gaps,
        "recommendations": recommendations,
        "freshness": freshness,
        "orchestration": get_orchestration_status(),
        "generated_at": datetime.datetime.now().isoformat(),
    }


def get_job_status(job_id: str) -> dict[str, Any] | None:
    """Return status of a specific ingestion task (in-memory, else persisted history)."""
    job = _INGESTION_JOBS.get(job_id)
    if job is not None:
        return job
    return next((j for j in load_job_history() if j.get("job_id") == job_id), None)


def list_recent_jobs(limit: int = 10) -> list[dict[str, Any]]:
    """List recent ingestion background tasks (this process + persisted history)."""
    merged = {j["job_id"]: j for j in load_job_history() if j.get("job_id")}
    merged.update(_INGESTION_JOBS)
    return sorted(merged.values(), key=lambda j: j.get("created_at", ""), reverse=True)[:limit]


def register_job_task(job_id: str, task: Any) -> None:
    """Associate an API-scheduled asyncio task with its job record (liveness checks)."""
    _JOB_TASKS[job_id] = task


def _task_alive(job_id: str) -> bool:
    task = _JOB_TASKS.get(job_id)
    if task is None:
        return True  # inline/unknown runner — treat as running
    try:
        return not task.done() and not task.get_loop().is_closed()
    except RuntimeError:
        return False


def running_job() -> dict[str, Any] | None:
    """The in-process ingestion job still running, if any (jobs share data files).

    A 'running' record whose task died with its event loop is marked 'interrupted'.
    """
    for job in _INGESTION_JOBS.values():
        if job.get("status") != "running":
            _JOB_TASKS.pop(job["job_id"], None)
            continue
        if _task_alive(job["job_id"]):
            return job
        job["status"] = "interrupted"
        job["message"] = "Task ended without completing (event loop closed)."
        _JOB_TASKS.pop(job["job_id"], None)
        _persist_job(job)
    return None


def load_job_history() -> list[dict[str, Any]]:
    """Persisted finished jobs; a 'running' record from a dead process becomes 'interrupted'."""
    data = load_json(JOB_HISTORY_FILE) if os.path.exists(JOB_HISTORY_FILE) else None
    if not isinstance(data, list):
        return []
    out = []
    for rec in data:
        if not isinstance(rec, dict):
            continue
        if rec.get("status") == "running" and rec.get("job_id") not in _INGESTION_JOBS:
            rec = {**rec, "status": "interrupted", "message": "Process ended before completion."}
        out.append(rec)
    return out


def _persist_job(record: dict[str, Any]) -> None:
    """Keep the last ``MAX_JOB_HISTORY`` job records on disk (atomic replace)."""
    import json

    history = [j for j in load_job_history() if j.get("job_id") != record.get("job_id")]
    slim = {k: record.get(k) for k in _PERSISTED_JOB_FIELDS}
    history = (history + [slim])[-MAX_JOB_HISTORY:]
    tmp = f"{JOB_HISTORY_FILE}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(history, fh, default=str)
        os.replace(tmp, JOB_HISTORY_FILE)
    except OSError as exc:
        log.warning("Could not persist job history: %s", exc)


def _prune_jobs() -> None:
    finished = sorted(
        (j for j in _INGESTION_JOBS.values() if j.get("status") != "running"),
        key=lambda j: j.get("created_at", ""),
    )
    for job in finished[: max(0, len(finished) - MAX_JOB_HISTORY)]:
        _INGESTION_JOBS.pop(job["job_id"], None)


def _now_iso() -> str:
    return datetime.datetime.now().isoformat()


def _pipeline_shell(meta: dict[str, Any]) -> dict[str, Any]:
    """Empty honest pipeline status row from catalog metadata."""
    return {
        "id": meta["id"],
        "label": meta["label"],
        "availability": meta["availability"],
        "status": "UNAVAILABLE" if meta["availability"] == "UNAVAILABLE" else "PENDING",
        "started_at": None,
        "completed_at": None,
        "duration_sec": None,
        "records": None,
        "source": meta.get("source"),
        "quality": None,
        "warnings": [],
        "errors": [],
        "notes": meta.get("notes"),
    }


def normalize_backfill_date_range(start_date: str | None, end_date: str | None) -> tuple[str, str]:
    """Normalize and validate an explicit historical backfill range.

    Accepts ``YYYYMMDD`` or ``YYYY-MM-DD``. Returns ``(YYYYMMDD, YYYYMMDD)``.
    Raises ``ValueError`` when dates are missing, unparseable, or start > end.
    Does **not** invent default dates.
    """
    if not start_date or not end_date:
        raise ValueError(
            "Historical backfill requires explicit start_date and end_date "
            "(YYYYMMDD or YYYY-MM-DD). Defaults are not invented."
        )

    def _one(label: str, raw: str) -> datetime.date:
        text = str(raw).strip()
        if not text:
            raise ValueError(f"{label} is empty")
        compact = text.replace("-", "")
        if len(compact) != 8 or not compact.isdigit():
            raise ValueError(f"{label} must be YYYYMMDD or YYYY-MM-DD (got {raw!r})")
        try:
            return datetime.date(int(compact[:4]), int(compact[4:6]), int(compact[6:8]))
        except ValueError as exc:
            raise ValueError(f"{label} is not a valid calendar date: {raw!r}") from exc

    start = _one("start_date", start_date)
    end = _one("end_date", end_date)
    if start > end:
        raise ValueError(
            f"Invalid date range: start_date ({start.isoformat()}) > end_date ({end.isoformat()})"
        )
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


def validate_ownership_path_or_url(path_or_url: str | None) -> str:
    """Validate ownership ingest source. Does not invent paths or URLs.

    Status: KSEI OWNERSHIP SOURCE NOT CONFIGURED — operators must supply an
    explicit local CSV path or http(s) URL. There is no default production URL.

    Local files must resolve under DATA_DIR (no arbitrary LFI). Remote http(s)
    requires RITELINSIGHT_ALLOW_OWNERSHIP_HTTP=1 (SSRF guard).
    """
    if path_or_url is None or not str(path_or_url).strip():
        raise ValueError(
            "KSEI OWNERSHIP SOURCE NOT CONFIGURED — provide path_or_url "
            "(local CSV or http(s) URL). No default source."
        )
    source = str(path_or_url).strip()
    if source.startswith(("http://", "https://")):
        allow_http = os.environ.get("RITELINSIGHT_ALLOW_OWNERSHIP_HTTP", "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        if not allow_http:
            raise ValueError(
                "Remote ownership URL blocked — set RITELINSIGHT_ALLOW_OWNERSHIP_HTTP=1 "
                "to permit http(s) sources (SSRF guard)."
            )
        return source
    if not os.path.isfile(source):
        raise ValueError(f"Local ownership file not found: {source}")
    abs_source = os.path.realpath(source)
    data_root = os.path.realpath(DATA_DIR)
    if not (abs_source == data_root or abs_source.startswith(data_root + os.sep)):
        raise ValueError(
            f"Local ownership file must be under DATA_DIR ({data_root}); got {abs_source}"
        )
    return abs_source


def get_orchestration_status() -> dict[str, Any]:
    """Catalog + last Sync All / parameterized runs for Data Center UI."""
    catalog_rows = []
    last_pipelines: dict[str, Any] = {}
    if isinstance(_LAST_SYNC_ALL, dict):
        for p in _LAST_SYNC_ALL.get("pipelines") or []:
            if isinstance(p, dict) and p.get("id"):
                last_pipelines[str(p["id"])] = p

    for meta in PIPELINE_CATALOG:
        row = _pipeline_shell(meta)
        prior = last_pipelines.get(meta["id"])
        if prior and meta["id"] not in ("historical", "ownership"):
            for key in (
                "status",
                "started_at",
                "completed_at",
                "duration_sec",
                "records",
                "source",
                "quality",
                "warnings",
                "errors",
            ):
                if key in prior and prior[key] is not None:
                    row[key] = prior[key]
            if prior.get("warnings") is not None:
                row["warnings"] = list(prior["warnings"])
            if prior.get("errors") is not None:
                row["errors"] = list(prior["errors"])
            if meta["availability"] == "UNAVAILABLE":
                row["status"] = "UNAVAILABLE"
        elif meta["availability"] == "UNAVAILABLE" and meta["id"] != "ownership":
            row["status"] = "UNAVAILABLE"
        elif meta["id"] == "historical":
            row["status"] = "IDLE"
            row["warnings"] = ["Manual backfill requires date range — not auto-run by Sync All."]
            if isinstance(_LAST_HISTORICAL_RUN, dict):
                for key in (
                    "status",
                    "started_at",
                    "completed_at",
                    "duration_sec",
                    "records",
                    "source",
                    "quality",
                    "warnings",
                    "errors",
                ):
                    if key in _LAST_HISTORICAL_RUN and _LAST_HISTORICAL_RUN[key] is not None:
                        row[key] = _LAST_HISTORICAL_RUN[key]
                row["availability"] = "PARTIAL"
                if _LAST_HISTORICAL_RUN.get("warnings") is not None:
                    row["warnings"] = list(_LAST_HISTORICAL_RUN["warnings"])
                if _LAST_HISTORICAL_RUN.get("errors") is not None:
                    row["errors"] = list(_LAST_HISTORICAL_RUN["errors"])
        elif meta["id"] == "ownership":
            # Stay UNAVAILABLE for Sync All; show last parameterized run if any.
            row["status"] = "UNAVAILABLE"
            row["source"] = None
            row["warnings"] = [
                "Requires explicit path_or_url — not in Sync All; no default KSEI source."
            ]
            if isinstance(_LAST_OWNERSHIP_RUN, dict):
                for key in (
                    "status",
                    "started_at",
                    "completed_at",
                    "duration_sec",
                    "records",
                    "source",
                    "quality",
                    "warnings",
                    "errors",
                ):
                    if key in _LAST_OWNERSHIP_RUN and _LAST_OWNERSHIP_RUN[key] is not None:
                        row[key] = _LAST_OWNERSHIP_RUN[key]
                # Keep availability UNAVAILABLE (not a Sync All pipeline).
                row["availability"] = "UNAVAILABLE"
                if _LAST_OWNERSHIP_RUN.get("warnings") is not None:
                    row["warnings"] = list(_LAST_OWNERSHIP_RUN["warnings"])
                if _LAST_OWNERSHIP_RUN.get("errors") is not None:
                    row["errors"] = list(_LAST_OWNERSHIP_RUN["errors"])
        else:
            row["status"] = "IDLE"
        catalog_rows.append(row)

    return {
        "integrations": dict(INTEGRATION_STATUS),
        "pipelines": catalog_rows,
        "last_sync_all": _LAST_SYNC_ALL,
        "last_historical_run": _LAST_HISTORICAL_RUN,
        "last_ownership_run": _LAST_OWNERSHIP_RUN,
    }


def _finalize_pipeline(
    row: dict[str, Any],
    *,
    status: str,
    records: Any = None,
    quality: Any = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    ended = _now_iso()
    row["completed_at"] = ended
    started = row.get("started_at")
    if started:
        try:
            delta = datetime.datetime.fromisoformat(ended) - datetime.datetime.fromisoformat(
                started
            )
            row["duration_sec"] = round(delta.total_seconds(), 3)
        except ValueError:
            row["duration_sec"] = None
    row["status"] = status
    if records is not None:
        row["records"] = records
    if quality is not None:
        row["quality"] = quality
    if source is not None:
        row["source"] = source
    if warnings:
        row["warnings"] = list(warnings)
    if errors:
        row["errors"] = list(errors)
    return row


def _status_from_ingest_dataset(result: Any) -> tuple[str, int | None, list[str], list[str]]:
    """Map ingest_daily dataset result → SUCCESS/PARTIAL/FAILED."""
    warnings: list[str] = []
    errors: list[str] = []
    if not isinstance(result, dict):
        return "FAILED", None, warnings, ["Unexpected non-dict ingest result"]
    st = str(result.get("status", "")).lower()
    records = result.get("records")
    rec_i = int(records) if isinstance(records, (int, float)) else None
    if st in ("ok", "skipped"):
        if st == "skipped":
            warnings.append("Partition already existed; skipped fetch.")
        return "SUCCESS", rec_i, warnings, errors
    if st == "no_data":
        warnings.append("No rows returned (non-trading day or empty response).")
        return "PARTIAL", rec_i, warnings, errors
    if st == "error":
        errors.append(str(result.get("message") or result.get("error") or "ingest error"))
        return "FAILED", rec_i, warnings, errors
    errors.append(f"Unknown ingest status: {st or 'missing'}")
    return "FAILED", rec_i, warnings, errors


def _overall_from_pipelines(pipelines: list[dict[str, Any]]) -> str:
    """SUCCESS / PARTIAL / FAILED from runnable outcomes (UNAVAILABLE ignored)."""
    runnable = [p for p in pipelines if p.get("status") in ("SUCCESS", "PARTIAL", "FAILED")]
    if not runnable:
        return "PARTIAL"
    statuses = {p.get("status") for p in runnable}
    if statuses == {"SUCCESS"}:
        return "SUCCESS"
    if statuses == {"FAILED"}:
        return "FAILED"
    return "PARTIAL"


def run_sync_all_data(
    date: str | None = None,
    *,
    fail_pipelines: set[str] | frozenset[str] | None = None,
) -> dict[str, Any]:
    """Minimal Sync All Data orchestrator for pipelines that truly exist.

    Independent pipelines keep their own status when another fails.
    Does not invent records, sources, or success for UNAVAILABLE pipelines.
    ``fail_pipelines`` is a test hook to force a controlled failure.
    """
    global _LAST_SYNC_ALL
    fail_set = set(fail_pipelines or ())
    started_all = _now_iso()
    by_id = {m["id"]: m for m in PIPELINE_CATALOG}
    results: list[dict[str, Any]] = []

    def _start(pid: str) -> dict[str, Any]:
        row = _pipeline_shell(by_id[pid])
        row["started_at"] = _now_iso()
        row["status"] = "RUNNING"
        return row

    for pid in ("ownership", "historical"):
        row = _pipeline_shell(by_id[pid])
        row["status"] = "UNAVAILABLE"
        if pid == "historical":
            row["warnings"] = [
                "Historical backfill requires explicit start/end — not executed by Sync All."
            ]
        results.append(row)

    market_row = _start("market_eod")
    broker_row = _start("broker")
    foreign_row = _start("foreign")
    daily_res: dict[str, Any] = {}
    try:
        if "market_eod" in fail_set or "broker" in fail_set:
            raise RuntimeError("Controlled test failure for market/broker ingest")
        from idx.pipelines.daily import ingest_daily

        daily_res = ingest_daily(date=date, export_parquet=True) or {}
        if not isinstance(daily_res, dict):
            daily_res = {"raw": daily_res}
    except Exception as exc:
        err = str(exc)
        log.error("Sync All market/broker ingest failed: %s", exc)
        _finalize_pipeline(market_row, status="FAILED", errors=[err])
        _finalize_pipeline(broker_row, status="FAILED", errors=[err])
        _finalize_pipeline(
            foreign_row,
            status="FAILED",
            errors=["Foreign fields unavailable because market EOD ingest failed."],
            source=by_id["foreign"]["source"],
        )
        daily_res = {}
    else:
        stock = daily_res.get("stock_summary")
        index = daily_res.get("index_summary")
        broker = daily_res.get("broker_summary")

        st_stock, rec_stock, w_stock, e_stock = _status_from_ingest_dataset(stock)
        st_index, rec_index, w_index, e_index = _status_from_ingest_dataset(index)
        market_warnings = w_stock + [f"index: {w}" for w in w_index]
        market_errors = e_stock + [f"index: {e}" for e in e_index]
        if "market_eod" in fail_set:
            st_m, market_errors = "FAILED", market_errors + ["Controlled test failure (market_eod)"]
        elif st_stock == "FAILED" and st_index == "FAILED":
            st_m = "FAILED"
        elif st_stock in ("FAILED", "PARTIAL") or st_index in ("FAILED", "PARTIAL"):
            st_m = "PARTIAL"
        else:
            st_m = "SUCCESS"
        rec_m = None
        if rec_stock is not None or rec_index is not None:
            rec_m = (rec_stock or 0) + (rec_index or 0)
        _finalize_pipeline(
            market_row,
            status=st_m,
            records=rec_m,
            warnings=market_warnings,
            errors=market_errors,
            source=by_id["market_eod"]["source"],
        )

        st_b, rec_b, w_b, e_b = _status_from_ingest_dataset(broker)
        if "broker" in fail_set:
            st_b, e_b = "FAILED", e_b + ["Controlled test failure (broker)"]
        _finalize_pipeline(
            broker_row,
            status=st_b,
            records=rec_b,
            warnings=w_b,
            errors=e_b,
            source=by_id["broker"]["source"],
        )

        if "foreign" in fail_set:
            _finalize_pipeline(
                foreign_row,
                status="FAILED",
                errors=["Controlled test failure (foreign)"],
                source=by_id["foreign"]["source"],
            )
        elif st_stock == "SUCCESS":
            _finalize_pipeline(
                foreign_row,
                status="SUCCESS",
                records=rec_stock,
                warnings=[
                    "ForeignBuy/ForeignSell ingested with stock EOD — no separate foreign pipeline."
                ],
                source=by_id["foreign"]["source"],
                quality="embedded",
            )
        elif st_stock == "PARTIAL":
            _finalize_pipeline(
                foreign_row,
                status="PARTIAL",
                records=rec_stock,
                warnings=w_stock + ["Foreign fields depend on stock_summary partition."],
                source=by_id["foreign"]["source"],
                quality="embedded",
            )
        else:
            _finalize_pipeline(
                foreign_row,
                status="FAILED",
                errors=e_stock or ["stock_summary failed; foreign fields not updated."],
                source=by_id["foreign"]["source"],
            )

    results.extend([market_row, broker_row, foreign_row])

    fin_row = _start("financial")
    try:
        if "financial" in fail_set:
            raise RuntimeError("Controlled test failure (financial)")
        from idx.pipelines.parquet import export_financial_ratios
        from idx.scrapers.financial import fetch_financial_ratios

        scraped = fetch_financial_ratios()
        records = None
        if isinstance(scraped, dict) and isinstance(scraped.get("data"), list):
            records = len(scraped["data"])
        elif isinstance(scraped, list):
            records = len(scraped)
        export_info = export_financial_ratios()
        quality = None
        warnings: list[str] = []
        if export_info is None:
            warnings.append("financial_ratios.parquet export returned no output.")
            st = "PARTIAL"
        else:
            st = "SUCCESS"
            if isinstance(export_info, dict):
                quality = export_info.get("status") or export_info.get("rows")
                if records is None and isinstance(export_info.get("rows"), int):
                    records = export_info["rows"]
        _finalize_pipeline(
            fin_row,
            status=st,
            records=records,
            quality=quality,
            warnings=warnings,
            source=by_id["financial"]["source"],
        )
    except Exception as exc:
        log.error("Sync All financial failed: %s", exc)
        _finalize_pipeline(fin_row, status="FAILED", errors=[str(exc)])
    results.append(fin_row)

    sig_row = _start("signal_rebuild")
    try:
        if "signal_rebuild" in fail_set:
            raise RuntimeError("Controlled test failure (signal_rebuild)")
        from idx.signals import build_briefing

        briefing = build_briefing()
        records = None
        if isinstance(briefing, dict):
            total = 0
            found = False
            for key, val in briefing.items():
                if str(key).endswith("_rows") and isinstance(val, (int, float)):
                    total += int(val)
                    found = True
            if found:
                records = total
        _finalize_pipeline(
            sig_row,
            status="SUCCESS",
            records=records,
            source=by_id["signal_rebuild"]["source"],
        )
    except Exception as exc:
        log.error("Sync All signal rebuild failed: %s", exc)
        _finalize_pipeline(sig_row, status="FAILED", errors=[str(exc)])
    results.append(sig_row)

    feat_row = _start("feature_rebuild")
    try:
        if "feature_rebuild" in fail_set:
            raise RuntimeError("Controlled test failure (feature_rebuild)")
        from idx.rebuild import rebuild_features

        feat = rebuild_features(max_tickers=40)
        st = feat.get("status") or "FAILED"
        if st == "SUCCESS":
            pipe_st = "SUCCESS"
        elif st == "PARTIAL":
            pipe_st = "PARTIAL"
        else:
            pipe_st = "FAILED"
        _finalize_pipeline(
            feat_row,
            status=pipe_st,
            records=feat.get("records"),
            source=by_id["feature_rebuild"]["source"],
            quality=st,
            warnings=list(feat.get("warnings") or []),
            errors=list(feat.get("errors") or []),
        )
        feat_row["duration_sec"] = feat.get("duration_sec")
        feat_row["engine_version"] = feat.get("engine_version")
    except Exception as exc:
        log.error("Sync All feature rebuild failed: %s", exc)
        _finalize_pipeline(feat_row, status="FAILED", errors=[str(exc)])
    results.append(feat_row)

    tr_row = _start("target_risk")
    try:
        if "target_risk" in fail_set:
            raise RuntimeError("Controlled test failure (target_risk)")
        from idx.rebuild import rebuild_target_risk

        tr = rebuild_target_risk(max_tickers=40)
        st = tr.get("status") or "FAILED"
        if st == "SUCCESS":
            pipe_st = "SUCCESS"
        elif st == "PARTIAL":
            pipe_st = "PARTIAL"
        else:
            pipe_st = "FAILED"
        _finalize_pipeline(
            tr_row,
            status=pipe_st,
            records=tr.get("records"),
            source=by_id["target_risk"]["source"],
            quality=st,
            warnings=list(tr.get("warnings") or []),
            errors=list(tr.get("errors") or []),
        )
        tr_row["duration_sec"] = tr.get("duration_sec")
        tr_row["engine_version"] = tr.get("engine_version")
    except Exception as exc:
        log.error("Sync All target/risk rebuild failed: %s", exc)
        _finalize_pipeline(tr_row, status="FAILED", errors=[str(exc)])
    results.append(tr_row)

    scr_row = _start("screener_rebuild")
    try:
        if "screener_rebuild" in fail_set:
            raise RuntimeError("Controlled test failure (screener_rebuild)")
        screener = refresh_screener_snapshot()
        _finalize_pipeline(
            scr_row,
            status="SUCCESS",
            source=by_id["screener_rebuild"]["source"],
            quality=screener.get("status") if isinstance(screener, dict) else None,
        )
    except Exception as exc:
        log.error("Sync All screener rebuild failed: %s", exc)
        _finalize_pipeline(scr_row, status="FAILED", errors=[str(exc)])
    results.append(scr_row)

    order = [m["id"] for m in PIPELINE_CATALOG]
    results.sort(key=lambda r: order.index(r["id"]) if r["id"] in order else 99)

    completed_all = _now_iso()
    overall = _overall_from_pipelines(results)
    try:
        duration = round(
            (
                datetime.datetime.fromisoformat(completed_all)
                - datetime.datetime.fromisoformat(started_all)
            ).total_seconds(),
            3,
        )
    except ValueError:
        duration = None

    payload = {
        "overall_status": overall,
        "started_at": started_all,
        "completed_at": completed_all,
        "duration_sec": duration,
        "pipelines": results,
        "integrations": dict(INTEGRATION_STATUS),
    }
    _LAST_SYNC_ALL = payload
    return payload


def refresh_screener_snapshot() -> dict[str, Any]:
    """Regenerate data/network_alpha_data.json via existing analyze_network_alpha pipeline.

    Loads the generator module from python/analyze_network_alpha.py (outside the idx
    package) without spawning a second process or duplicating generation logic.
    """
    import importlib.util
    import sys

    module_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "analyze_network_alpha.py")
    )
    if not os.path.isfile(module_path):
        raise FileNotFoundError(f"Screener generator not found: {module_path}")

    module_name = "analyze_network_alpha"
    existing = sys.modules.get(module_name)
    if existing is not None and hasattr(existing, "run_analysis_pipeline"):
        existing.run_analysis_pipeline()
        return {"status": "completed", "generator": module_path}

    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load screener generator from {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    if not hasattr(module, "run_analysis_pipeline"):
        raise AttributeError("analyze_network_alpha.run_analysis_pipeline is missing")

    module.run_analysis_pipeline()
    return {"status": "completed", "generator": module_path}


async def run_async_ingestion_job(
    job_id: str,
    job_type: str,
    params: dict[str, Any],
    broadcast_callback: Any | None = None,
) -> dict[str, Any]:
    """Runs a daily ingestion or backfill task asynchronously with status updates."""
    import asyncio

    job_record: dict[str, Any] = {
        "job_id": job_id,
        "type": job_type,
        "params": params,
        "status": "running",
        "progress_pct": 0,
        "message": "Starting ingestion task...",
        "created_at": datetime.datetime.now().isoformat(),
        "completed_at": None,
        "duration_s": None,
        "results": None,
    }
    _INGESTION_JOBS[job_id] = job_record
    _prune_jobs()
    _persist_job(job_record)
    started = datetime.datetime.now()

    async def _notify(progress: int, msg: str):
        job_record["progress_pct"] = progress
        job_record["message"] = msg
        if broadcast_callback:
            try:
                await broadcast_callback(
                    {
                        "type": "ingestion_progress",
                        "job_id": job_id,
                        "progress": progress,
                        "message": msg,
                    }
                )
            except Exception:
                pass

    try:
        await _notify(10, f"Initializing {job_type} task...")
        completion_message = f"{job_type.capitalize()} completed successfully."

        if job_type == "sync_all":
            await _notify(15, "Running Sync All Data orchestrator...")
            fail_raw = params.get("fail_pipelines") or []
            fail_set = set(fail_raw) if isinstance(fail_raw, (list, set, tuple)) else set()
            sync_res = await asyncio.to_thread(
                run_sync_all_data,
                date=params.get("date"),
                fail_pipelines=fail_set,
            )
            job_record["results"] = sync_res
            overall = sync_res.get("overall_status", "PARTIAL")
            if overall == "FAILED":
                job_record["status"] = "failed"
                job_record["progress_pct"] = 100
                job_record["completed_at"] = datetime.datetime.now().isoformat()
                job_record["message"] = "Sync All Data finished with overall status FAILED."
                if broadcast_callback:
                    try:
                        await broadcast_callback(
                            {
                                "type": "ingestion_error",
                                "job_id": job_id,
                                "error": job_record["message"],
                                "results": sync_res,
                            }
                        )
                    except Exception:
                        pass
                return job_record
            completion_message = f"Sync All Data finished with overall status {overall}."
            job_record["status"] = "completed"
            job_record["progress_pct"] = 100
            job_record["completed_at"] = datetime.datetime.now().isoformat()
            job_record["message"] = completion_message
            if broadcast_callback:
                try:
                    await broadcast_callback(
                        {
                            "type": "ingestion_completed",
                            "job_id": job_id,
                            "message": completion_message,
                            "overall_status": overall,
                        }
                    )
                except Exception:
                    pass
            return job_record

        if job_type == "daily":
            from idx.pipelines.daily import ingest_daily

            await _notify(30, "Ingesting today's market-close sessions...")
            # Run blocking ingest_daily in threadpool
            date_arg = params.get("date")
            eod_res = await asyncio.to_thread(ingest_daily, date=date_arg)
            results: dict[str, Any] = (
                dict(eod_res) if isinstance(eod_res, dict) else {"ingestion": eod_res}
            )

            await _notify(85, "Refreshing screener snapshot...")
            try:
                screener_res = await asyncio.to_thread(refresh_screener_snapshot)
                results["screener_refresh"] = screener_res
                completion_message = "Daily completed successfully; screener snapshot refreshed."
            except Exception as screener_exc:
                # EOD ingestion already succeeded — do not fail the overall job.
                log.error(
                    "Screener refresh failed after successful daily ingestion (job %s): %s",
                    job_id,
                    screener_exc,
                )
                results["screener_refresh"] = {
                    "status": "failed",
                    "error": str(screener_exc),
                }
                completion_message = "Daily completed successfully; screener refresh failed."

            job_record["results"] = results

        elif job_type == "backfill":
            global _LAST_HISTORICAL_RUN
            from idx.pipelines.parquet import export_all
            from idx.scrapers.historical import (
                async_backfill_broker_summary,
                async_backfill_index_summary,
                async_backfill_stock_summary,
            )

            # Explicit range only — never invent defaults.
            start, end = normalize_backfill_date_range(
                params.get("start_date"), params.get("end_date")
            )
            concurrency = max(1, int(params.get("concurrency", 4)))
            hist_started = _now_iso()
            hist_warnings: list[str] = []
            hist_errors: list[str] = []

            async def _one_backfill(label: str, coro):
                try:
                    return await coro
                except Exception as exc:
                    log.error("Historical backfill %s failed: %s", label, exc)
                    return {
                        "dataset": label,
                        "status": "error",
                        "error": str(exc),
                        "total_records": 0,
                        "dates_fetched": 0,
                        "errors": 1,
                    }

            await _notify(20, f"Backfilling stock summaries ({start} to {end})...")
            res_stock = await _one_backfill(
                "stock_summary",
                async_backfill_stock_summary(start, end, concurrency=concurrency),
            )

            await _notify(50, f"Backfilling broker summaries ({start} to {end})...")
            res_broker = await _one_backfill(
                "broker_summary",
                async_backfill_broker_summary(start, end, concurrency=concurrency),
            )

            await _notify(75, f"Backfilling index summaries ({start} to {end})...")
            res_index = await _one_backfill(
                "index_summary",
                async_backfill_index_summary(start, end, concurrency=concurrency),
            )

            await _notify(85, "Rebuilding consolidated Parquet datasets...")
            try:
                parquet_res = await asyncio.to_thread(export_all)
            except Exception as exc:
                log.error("Parquet export after backfill failed: %s", exc)
                parquet_res = {"status": "error", "error": str(exc)}
                hist_errors.append(f"parquet_export: {exc}")

            def _rec(res: Any) -> int:
                if not isinstance(res, dict):
                    return 0
                for key in ("total_records", "records"):
                    val = res.get(key)
                    if isinstance(val, (int, float)):
                        return int(val)
                return 0

            def _failed(res: Any) -> bool:
                if not isinstance(res, dict):
                    return True
                if res.get("status") == "error" or res.get("error"):
                    return True
                err_n = res.get("errors")
                return (
                    isinstance(err_n, (int, float))
                    and int(err_n) > 0
                    and _rec(res) == 0
                    and int(res.get("dates_fetched") or res.get("fetched_days") or 0) == 0
                    and int(res.get("missing_days") or 1) > 0
                    and int(err_n) >= int(res.get("missing_days") or err_n)
                )

            parts = {
                "stock_summary": res_stock,
                "broker_summary": res_broker,
                "index_summary": res_index,
            }
            fail_flags = []
            for name, res in parts.items():
                if isinstance(res, dict) and (res.get("status") == "error" or res.get("error")):
                    fail_flags.append(name)
                    hist_errors.append(f"{name}: {res.get('error') or res.get('status')}")
            total_records = sum(_rec(r) for r in parts.values())

            if len(fail_flags) == 3:
                hist_status = "FAILED"
            elif fail_flags:
                hist_status = "PARTIAL"
                hist_warnings.append(f"Independent dataset failure(s): {', '.join(fail_flags)}")
            else:
                hist_status = "SUCCESS"

            if isinstance(parquet_res, dict) and (
                parquet_res.get("status") == "error" or parquet_res.get("error")
            ):
                if hist_status == "SUCCESS":
                    hist_status = "PARTIAL"
                hist_warnings.append("Parquet rebuild failed after backfill.")

            hist_completed = _now_iso()
            try:
                hist_duration = round(
                    (
                        datetime.datetime.fromisoformat(hist_completed)
                        - datetime.datetime.fromisoformat(hist_started)
                    ).total_seconds(),
                    3,
                )
            except ValueError:
                hist_duration = None

            _LAST_HISTORICAL_RUN = {
                "id": "historical",
                "label": "Historical",
                "availability": "PARTIAL",
                "status": hist_status,
                "started_at": hist_started,
                "completed_at": hist_completed,
                "duration_sec": hist_duration,
                "records": total_records,
                "source": f"IDX TradingSummary backfill {start}→{end}",
                "quality": None,
                "warnings": hist_warnings
                + [
                    "Manual parameterized backfill (not Sync All).",
                ],
                "errors": hist_errors,
                "params": {"start_date": start, "end_date": end, "concurrency": concurrency},
            }

            job_record["results"] = {
                "pipeline": "historical",
                "start_date": start,
                "end_date": end,
                "stock_summary": res_stock,
                "broker_summary": res_broker,
                "index_summary": res_index,
                "parquet_export": parquet_res,
                "orchestration": _LAST_HISTORICAL_RUN,
            }
            completion_message = (
                f"Historical backfill ({start}→{end}) finished with status {hist_status}."
            )
            if hist_status == "FAILED":
                job_record["status"] = "failed"
                job_record["progress_pct"] = 100
                job_record["completed_at"] = hist_completed
                job_record["message"] = completion_message
                if broadcast_callback:
                    try:
                        await broadcast_callback(
                            {
                                "type": "ingestion_error",
                                "job_id": job_id,
                                "error": completion_message,
                                "results": job_record["results"],
                            }
                        )
                    except Exception:
                        pass
                return job_record

        elif job_type == "ownership":
            global _LAST_OWNERSHIP_RUN
            own_started = _now_iso()
            source = validate_ownership_path_or_url(params.get("path_or_url"))
            await _notify(30, "Ingesting KSEI ownership from provided source...")

            def _run_ownership():
                from idx.core.ownership import ingest_ksei_ownership

                return ingest_ksei_ownership(source)

            try:
                own_res = await asyncio.to_thread(_run_ownership)
            except Exception as exc:
                log.error("Ownership ingest failed: %s", exc)
                own_completed = _now_iso()
                _LAST_OWNERSHIP_RUN = {
                    "id": "ownership",
                    "label": "Ownership",
                    "availability": "UNAVAILABLE",
                    "status": "FAILED",
                    "started_at": own_started,
                    "completed_at": own_completed,
                    "duration_sec": None,
                    "records": None,
                    "source": source,
                    "quality": None,
                    "warnings": [
                        "Parameterized ownership ingest failed — Sync All still excludes this pipeline."
                    ],
                    "errors": [str(exc)],
                }
                job_record["results"] = {"orchestration": _LAST_OWNERSHIP_RUN}
                job_record["status"] = "failed"
                job_record["progress_pct"] = 100
                job_record["completed_at"] = own_completed
                job_record["message"] = f"Ownership ingest failed: {exc}"
                if broadcast_callback:
                    try:
                        await broadcast_callback(
                            {
                                "type": "ingestion_error",
                                "job_id": job_id,
                                "error": str(exc),
                            }
                        )
                    except Exception:
                        pass
                return job_record

            records = None
            if isinstance(own_res, dict) and isinstance(own_res.get("total_rows"), (int, float)):
                records = int(own_res["total_rows"])
            # Drop non-JSON DataFrames from results payload
            safe_res = {}
            if isinstance(own_res, dict):
                for k, v in own_res.items():
                    if k in ("deltas", "tycoon_drift"):
                        continue
                    safe_res[k] = v
            own_completed = _now_iso()
            try:
                own_duration = round(
                    (
                        datetime.datetime.fromisoformat(own_completed)
                        - datetime.datetime.fromisoformat(own_started)
                    ).total_seconds(),
                    3,
                )
            except ValueError:
                own_duration = None
            _LAST_OWNERSHIP_RUN = {
                "id": "ownership",
                "label": "Ownership",
                "availability": "UNAVAILABLE",
                "status": "SUCCESS",
                "started_at": own_started,
                "completed_at": own_completed,
                "duration_sec": own_duration,
                "records": records,
                "source": source,
                "quality": safe_res.get("status"),
                "warnings": [
                    "Parameterized run only — ownership remains excluded from Sync All "
                    "(no default KSEI source)."
                ],
                "errors": [],
            }
            job_record["results"] = {
                "pipeline": "ownership",
                "ingest": safe_res,
                "orchestration": _LAST_OWNERSHIP_RUN,
            }
            completion_message = (
                f"Ownership ingest finished ({records if records is not None else 'n/a'} rows)."
            )

        else:
            raise ValueError(f"Unknown job type: {job_type}")

        job_record["status"] = "completed"
        job_record["progress_pct"] = 100
        job_record["completed_at"] = datetime.datetime.now().isoformat()
        job_record["message"] = completion_message

        if broadcast_callback:
            try:
                await broadcast_callback(
                    {
                        "type": "ingestion_completed",
                        "job_id": job_id,
                        "message": completion_message,
                        "results": job_record["results"],
                    }
                )
            except Exception:
                pass

    except Exception as exc:
        log.error("Ingestion job %s failed: %s", job_id, exc)
        job_record["status"] = "failed"
        job_record["message"] = str(exc)
        job_record["completed_at"] = datetime.datetime.now().isoformat()
        if broadcast_callback:
            try:
                await broadcast_callback(
                    {
                        "type": "ingestion_error",
                        "job_id": job_id,
                        "error": str(exc),
                    }
                )
            except Exception:
                pass

    job_record["duration_s"] = round((datetime.datetime.now() - started).total_seconds(), 1)
    _persist_job(job_record)
    return job_record
