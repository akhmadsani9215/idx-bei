"""
SQL query layer over the partitioned Parquet time-series store via DuckDB.

Queries run directly against data/timeseries/<dataset>/date=*.parquet without
materializing anything in memory beyond the result set.

Usage:
    from idx.core.query import query_dataset
    df = query_dataset("stock_summary", start="2026-01-01", where="StockCode = 'BBCA'")
"""

import glob
import os

import duckdb

from idx.core import timeseries as ts
from idx.core.utils import get_logger

log = get_logger("idx.core.query")


def sql(query):
    """Runs arbitrary SQL against DuckDB. Returns a pandas DataFrame."""
    return duckdb.sql(query).df()


def _dataset_glob(dataset, base_dir=None):
    """Glob pattern covering all partitions of a dataset; raises if none exist."""
    d_dir = ts.dataset_dir(dataset, base_dir)
    pattern = os.path.join(d_dir, "**", "*.parquet")
    if not glob.glob(pattern, recursive=True):
        # Fallback to consolidated parquet if available
        consolidated = os.path.join(os.path.dirname(d_dir), "parquet", f"{dataset}.parquet")
        if os.path.exists(consolidated):
            return consolidated
        raise FileNotFoundError(f"No partitions found for dataset '{dataset}' under {d_dir}")
    return pattern


def query_dataset(
    dataset, start=None, end=None, where=None, columns="*", limit=None, base_dir=None
):
    """Queries one time-series dataset with optional filters.

    Args:
        dataset:  Dataset name (e.g. 'stock_summary')
        start:    Inclusive partition date filter, YYYY-MM-DD (on filename Date)
        end:      Inclusive partition date filter, YYYY-MM-DD
        where:    Optional SQL predicate applied to record columns
        columns:  Column list string, defaults to '*'
        limit:    Optional row cap applied last
        base_dir: Optional store root override (for tests)

    Returns:
        pandas DataFrame of matching rows, ordered chronologically by ``Date``
        when that column is available. When ``limit`` is set, the *latest*
        ``limit`` rows by Date are returned (still ascending).
    """
    pattern = _dataset_glob(dataset, base_dir)

    conds = []
    if start:
        conds.append(
            f"(Date >= '{start}' OR regexp_extract(filename, 'date=(.*)\\.parquet', 1) >= '{start}')"
        )
    if end:
        conds.append(
            f"(Date <= '{end}' OR regexp_extract(filename, 'date=(.*)\\.parquet', 1) <= '{end}')"
        )
    if where:
        conds.append(f"({where})")
    where_clause = f"WHERE {' AND '.join(conds)}" if conds else ""

    # Never ORDER BY 1 — first column is often a row index ("No"), not Date.
    if limit is not None:
        # Ensure Date is available for latest-N selection even if caller omitted it.
        col_list = [c.strip() for c in columns.split(",")] if columns.strip() != "*" else []
        if columns.strip() == "*" or "Date" in col_list:
            select_cols = columns
            drop_date = False
        else:
            select_cols = f"Date, {columns}"
            drop_date = True
        query = f"""
            SELECT * FROM (
                SELECT {select_cols}
                FROM read_parquet(['{pattern}'], filename = true)
                {where_clause}
                ORDER BY Date DESC
                LIMIT {int(limit)}
            ) AS _q
            ORDER BY Date ASC
        """
        log.debug("DuckDB query: %s", " ".join(query.split()))
        df = sql(query)
        if drop_date and "Date" in df.columns:
            df = df.drop(columns=["Date"])
    else:
        query = f"""
            SELECT {columns}
            FROM read_parquet(['{pattern}'], filename = true)
            {where_clause}
            ORDER BY Date ASC
        """
        log.debug("DuckDB query: %s", " ".join(query.split()))
        df = sql(query)

    if "Date" in df.columns and len(df) > 1:
        df = df.sort_values("Date", kind="mergesort").reset_index(drop=True)
    return df


def available_datasets():
    """Returns datasets that have at least one partition on disk."""
    return [ds for ds in ts.DATASETS if ts.existing_dates(ds)]
