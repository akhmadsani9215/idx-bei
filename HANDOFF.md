# HANDOFF — RitelInsight

Last updated: 2026-09-24

## Mode
**Personal operator use** (commercial deferred).

## Last completed task
**Personal data fill** — broker/index/stock aligned; corporate refreshed; personal cost models ready.

### Result
- Timeseries: **stock/broker/index = 883/883/883** sessions (2023-01-02 → 2026-09-23); 0 gaps vs each other
- 2026-09-24: no IDX session data yet (expected until market close / publish)
- Corporate actions scrape: **1612** records
- `personal_operator_cost_model` / `personal_operator_slippage_model` CONFIGURED for private P&L (15/25 bps + 5 bps/side, as_of 2026-09-24)
- Research still locked: **0 survivors**, screener **NOT_VALIDATED** — do not re-search/promote
- Fixed `idx parquet` CLI (was nested under bandarmology; now works standalone)

### Exact next task (optional)
- Cursor: **Reload MCP** so `idx-bei` exposes `alpha_broker_summary` / `alpha_stock_history` / `alpha_foreign_flow` (key in gitignored `.env`)
- After market: `uv run idx daily` for 2026-09-24
- Use personal cost helpers when you want net P&L privately; do not treat study as tradable edge
- Note: Alpha Free plan ≈ **5 calls/day** — avoid burn; live BBCA broker-summary 2026-09-22 already verified PASS once

## Constraints
NO PUSH / NO COMMIT unless asked. Never commit `.env` / API keys.
