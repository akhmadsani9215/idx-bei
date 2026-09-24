# PROJECT_STATE — RitelInsight

Last updated: 2026-09-24

## Product
**RitelInsight** — personal decision-support (commercial path deferred).

## Current state
**CORE + UI DONE.** Personal-data mode complete for local use: stock/broker/index timeseries aligned; corporate refreshed; personal cost models available. Research locked (0 survivors, screener NOT_VALIDATED).

## Verified
- Discovery study: **0 survivors** — unchanged
- Survivorship **NOT_VALIDATED**; registry default cost **NOT_CONFIGURED**
- Personal operator cost/slippage: **CONFIGURED** (private provenance, as_of 2026-09-24)
- Timeseries: **stock/broker/index = 883/883/883** (2023-01-02 → 2026-09-23); only 2026-09-24 missing (no IDX data yet)
- Corporate actions: **1612** scraped
- Fixed `idx parquet` CLI (was accidentally nested under bandarmology)

## Product matrix

| Area | Status |
|---|---|
| Screener | GREEN (NOT_VALIDATED labeled) |
| Stock Terminal | GREEN (EOD) |
| Big Money | GREEN enough for personal (broker history filled) |
| Strategy Lab / Discovery | GREEN harness · edge NOT_VALIDATED |
| Data Center | GREEN |
| Commercial / IdP / Realtime | DEFERRED |

## Next task
Optional: `uv run idx daily` after 2026-09-24 session publishes. No Stage-1 re-search. No commercial publish work until asked.
