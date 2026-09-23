"""
Historical data backfill scraper.

Fetches stock summaries, broker summaries, and index summaries over a date range,
building partitioned Parquet time-series datasets for quantitative analysis.

Usage:
    from idx.scrapers.historical import backfill_stock_summary
    backfill_stock_summary("20260101", "20260807")
"""

import datetime

from idx.core import timeseries as ts
from idx.core.client import IDXClient
from idx.core.utils import get_logger

log = get_logger("idx.scrapers.historical")


def _parse_date(d):
    """Accepts 'YYYYMMDD' or 'YYYY-MM-DD' and returns a date object."""
    if isinstance(d, datetime.date):
        return d
    d = d.replace("-", "")
    return datetime.datetime.strptime(d, "%Y%m%d").date()


def _trading_days(start, end):
    """Generates weekday dates between start and end (inclusive).

    IDX trades Mon-Fri. National holidays are NOT filtered here — the API
    simply returns an empty data list for non-trading days, which we skip.
    """
    current = _parse_date(start)
    end_dt = _parse_date(end)
    while current <= end_dt:
        if current.weekday() < 5:  # Mon=0 .. Fri=4
            yield current
        current += datetime.timedelta(days=1)


def backfill_stock_summary(start_date, end_date, client=None):
    """Fetches OHLCV + foreign flow for every trading day in [start_date, end_date].

    Data is written as one Parquet partition per date under
    data/timeseries/stock_summary/. Already-fetched dates are skipped (idempotent).

    Args:
        start_date: 'YYYYMMDD' or 'YYYY-MM-DD'
        end_date:   'YYYYMMDD' or 'YYYY-MM-DD'
        client:     Optional IDXClient instance

    Returns:
        dict with 'dates_fetched', 'dates_skipped', 'total_records'
    """
    return _backfill_dataset(
        "stock_summary",
        "/TradingSummary/GetStockSummary",
        start_date,
        end_date,
        client,
    )


def backfill_broker_summary(start_date, end_date, client=None):
    """Fetches broker transaction summaries for every trading day in [start_date, end_date]."""
    return _backfill_dataset(
        "broker_summary",
        "/TradingSummary/GetBrokerSummary",
        start_date,
        end_date,
        client,
    )


def backfill_index_summary(start_date, end_date, client=None):
    """Fetches index summaries (IHSG, LQ45, sectoral) for every trading day in range."""
    return _backfill_dataset(
        "index_summary",
        "/TradingSummary/GetIndexSummary",
        start_date,
        end_date,
        client,
    )


def _backfill_dataset(dataset, endpoint, start_date, end_date, client=None):
    """Generic backfill loop: fetch per trading day and write one partition per date.

    Each date is persisted immediately after fetching — a crash mid-backfill
    loses at most one day of work, and re-runs resume where they stopped.
    """
    if client is None:
        client = IDXClient()

    have = ts.existing_dates(dataset)
    dates = list(_trading_days(start_date, end_date))
    fetched = 0
    skipped = 0
    errors = 0
    total = 0

    log.info(
        "Backfill %s: %d trading days (%s → %s), %d already cached",
        dataset,
        len(dates),
        dates[0] if dates else "?",
        dates[-1] if dates else "?",
        len(have),
    )

    for i, dt in enumerate(dates):
        date_str = dt.strftime("%Y-%m-%d")
        date_api = dt.strftime("%Y%m%d")

        if date_str in have:
            skipped += 1
            continue

        try:
            data = client.get_json(endpoint, params={"date": date_api, "start": 0, "length": 9999})
        except Exception as exc:
            log.warning("Error fetching %s for %s: %s", dataset, date_api, exc)
            errors += 1
            continue

        if data is None:
            errors += 1
            log.warning(
                "[%d/%d] %s: fetch failed (HTTP error or request blocked)",
                i + 1,
                len(dates),
                date_str,
            )
            continue

        records = data.get("data") if isinstance(data, dict) else None
        if isinstance(records, list) and len(records) > 0:
            ts.write_partition(dataset, date_str, records)
            fetched += 1
            total += len(records)
            log.info("[%d/%d] %s: %d records", i + 1, len(dates), date_str, len(records))
        else:
            skipped += 1
            log.debug("[%d/%d] %s: no data (holiday?)", i + 1, len(dates), date_str)

    log.info(
        "Backfill %s done: fetched=%d, skipped=%d, errors=%d, total_records=%d",
        dataset,
        fetched,
        skipped,
        errors,
        total,
    )
    return {
        "dataset": dataset,
        "dates_fetched": fetched,
        "dates_skipped": skipped,
        "errors": errors,
        "total_records": total,
    }


async def async_backfill_dataset(
    dataset,
    endpoint,
    start_date,
    end_date,
    concurrency=1,
    delay=5.0,
    client=None,
):
    """
    Safe/resumable asynchronous backfill.

    Important:
    - Existing parquet partitions are never overwritten unnecessarily.
    - Missing dates are fetched one at a time by default.
    - A delay is applied between requests.
    - IDX 429/5xx handling remains inside AsyncIDXClient.
    """

    import asyncio

    from idx.core.client import AsyncIDXClient

    have = ts.existing_dates(dataset)
    dates = list(_trading_days(start_date, end_date))

    missing = [
        dt for dt in dates
        if dt.strftime("%Y-%m-%d") not in have
    ]

    log.info(
        "%s: %d total trading days (%d cached, %d missing)",
        dataset,
        len(dates),
        len(dates) - len(missing),
        len(missing),
    )

    if not missing:
        return {
            "dataset": dataset,
            "requested_days": len(dates),
            "cached_days": len(dates),
            "missing_days": 0,
            # Sync-compatible keys (primary contract)
            "dates_fetched": 0,
            "dates_skipped": 0,
            "errors": 0,
            "total_records": 0,
            # Async aliases
            "fetched_days": 0,
            "skipped_days": 0,
            "records": 0,
        }

    # Keep the client conservative. The caller can still request a
    # different concurrency, but IDX backfill defaults to serial operation.
    safe_concurrency = max(1, int(concurrency or 1))
    safe_delay = max(0.0, float(delay or 0.0))

    async def run(client_obj):
        sem = asyncio.Semaphore(safe_concurrency)
        lock = asyncio.Lock()

        fetched = 0
        skipped = 0
        errors = 0
        total_records = 0

        async def _worker(dt, idx, total_tasks):
            nonlocal fetched, skipped, errors, total_records

            date_str = dt.strftime("%Y-%m-%d")
            date_api = dt.strftime("%Y%m%d")

            async with sem:
                # Re-check immediately before requesting. This makes the
                # operation resumable if a previous worker/process already
                # created the partition.
                if date_str in ts.existing_dates(dataset):
                    async with lock:
                        skipped += 1
                    log.info(
                        "[%d/%d] %s: already cached",
                        idx,
                        total_tasks,
                        date_str,
                    )
                    return

                if safe_delay > 0:
                    await asyncio.sleep(safe_delay)

                try:
                    data = await client_obj.get_json(
                        endpoint,
                        params={
                            "date": date_api,
                            "start": 0,
                            "length": 9999,
                        },
                    )
                except Exception as exc:
                    async with lock:
                        errors += 1

                    log.warning(
                        "[%d/%d] %s: request error: %s",
                        idx,
                        total_tasks,
                        date_str,
                        exc,
                    )
                    return

                records = (
                    data.get("data")
                    if isinstance(data, dict)
                    else None
                )

                if isinstance(records, list) and len(records) > 0:
                    # Write only after a successful non-empty response.
                    ts.write_partition(
                        dataset,
                        date_str,
                        records,
                    )

                    async with lock:
                        fetched += 1
                        total_records += len(records)

                    log.info(
                        "[%d/%d] %s: %d records",
                        idx,
                        total_tasks,
                        date_str,
                        len(records),
                    )
                else:
                    async with lock:
                        skipped += 1

                    log.info(
                        "[%d/%d] %s: no data (holiday/weekend/empty)",
                        idx,
                        total_tasks,
                        date_str,
                    )

        # With concurrency=1 this becomes a clean serial request stream.
        # gather is retained so the same function remains compatible with
        # callers that intentionally request limited concurrency.
        tasks = [
            asyncio.create_task(
                _worker(dt, idx, len(missing))
            )
            for idx, dt in enumerate(missing, start=1)
        ]

        if tasks:
            await asyncio.gather(*tasks)

        return {
            "dataset": dataset,
            "requested_days": len(dates),
            "cached_days": len(dates) - len(missing),
            "missing_days": len(missing),
            # Sync-compatible keys (primary contract)
            "dates_fetched": fetched,
            "dates_skipped": skipped,
            "errors": errors,
            "total_records": total_records,
            # Async aliases
            "fetched_days": fetched,
            "skipped_days": skipped,
            "records": total_records,
        }

    if client is not None:
        return await run(client)

    async with AsyncIDXClient(
        max_retries=2,
        delay_seconds=1.5,
        concurrency=safe_concurrency,
    ) as async_client:
        return await run(async_client)

async def async_backfill_stock_summary(start_date, end_date, concurrency=1, delay=5.0, client=None):
    """Async backfill for stock OHLCV summaries."""
    return await async_backfill_dataset(
        "stock_summary",
        "/TradingSummary/GetStockSummary",
        start_date,
        end_date,
        concurrency=concurrency,
        delay=delay,
        client=client,
    )


async def async_backfill_broker_summary(start_date, end_date, concurrency=1, delay=5.0, client=None):
    """Async backfill for broker transaction summaries."""
    return await async_backfill_dataset(
        "broker_summary",
        "/TradingSummary/GetBrokerSummary",
        start_date,
        end_date,
        concurrency=concurrency,
        delay=delay,
        client=client,
    )


async def async_backfill_index_summary(start_date, end_date, concurrency=1, delay=5.0, client=None):
    """Async backfill for index summaries."""
    return await async_backfill_dataset(
        "index_summary",
        "/TradingSummary/GetIndexSummary",
        start_date,
        end_date,
        concurrency=concurrency,
        delay=delay,
        client=client,
    )
