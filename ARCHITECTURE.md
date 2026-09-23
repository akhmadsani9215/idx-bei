# ARCHITECTURE — RitelInsight

Last updated: 2026-09-23

## Stack (current)
- **Backend:** Python 3.13+, `uv` workspace (`python/src/idx`), FastAPI + WebSocket (`api.py`), CLI (`idx`).
- **Frontend:** React 19 + TypeScript + Vite SPA (`frontend/`); charts via TradingView Lightweight Charts (Apache-2.0).
- **Analytics data path:** scrapers → partitioned timeseries → Parquet exports; query/analytics via **DuckDB** (+ PyArrow).
- **Optional graph:** Neo4j available via compose/CLI for ownership/network — **optional**, use only when graph analytics are required.
- **MCP:** stdio MCP server under `python/src/idx/mcp/`.

## Storage direction
- **Parquet + DuckDB:** preferred for historical/market analytics locally.
- **PostgreSQL:** planned **application/business** DB when hosting is chosen — **not** forced into local production architecture now.
- **Neo4j:** optional for UBO/network/relationship analytics; do not require for core screens.

## Infrastructure principles
- Product quality > artificial cost minimization; budget flexible with justified value.
- Costly changes: WHY → BENEFIT → COST → ALTERNATIVES → WAIT/IMPLEMENT; flag to product owner first.
- 2 GB RAM = initial efficiency target, **not** an absolute limit.
- Paid realtime market data may be appropriate for reliable CPE; do not substitute inadequate free data merely to save cost.
- Avoid unnecessary paid services/dependencies.

## Data integrity rules (stable)
- Never fabricate broker attribution, smart-money attribution, or market data.
- Foreign flow ≠ smart money.
- Stealth accumulation = **UNAVAILABLE** without validated broker-participant attribution.
- Broker concentration screens may report **CR_k** and turnover rank by actual `Value` only.

## Data Center orchestration (2026-09-23)
- Data Center (`IngestionTab`) orchestrates **existing** pipelines via `job_type=sync_all` on the current FastAPI asyncio job runner (no Celery/Redis).
- Status contract lives on `/api/system/ingestion-status` → `orchestration` (per-pipeline + integrations).
- UNAVAILABLE/PARTIAL pipelines must be labeled honestly; do not invent sources, records, or success.

## Screener production engine (2026-09-23)
- Package: `idx.screener` — structure features, dynamic levels, historical sample gate, mode evaluators.
- API: `GET /api/screener` (timeframe/ticker/date/setup/signal/limit/cursor) — compact rows only, no raw history dump.
- UI: opportunities tab → `ScreenerTab` (Close Pressure / Swing / Long-Term).
- Quality: Close Pressure EOD = grade **E**; missing levels = null / NOT_QUALIFIED; no fabricated tick/broker tape.

## Completion pass surfaces (2026-09-23)
- Auth: `idx.auth_session` opaque sessions for watchlist / trading plan / journal.
- Providers: `idx.providers` (MarketData / AI / Notification / Payment) + `/api/integrations`, `/api/realtime/status`.
- Terminal: `idx.stock_terminal` + `/api/stock/{ticker}/terminal|chart|foreign|flow|broker|ownership|signals`.
- Big Money: `idx.big_money` + `/api/big-money` (disclosure/foreign/MW broker; Fast-In/Out UNAVAILABLE).
- Strategy Lab: `idx.strategy_lab` + `/api/strategy`, `/api/strategy/run`.
- Schema: `idx.schema_version.DATA_SCHEMA_VERSION` via `/api/schema` and `/schema`.
- Data status alias: `/api/data-status` → same payload as `/api/system/ingestion-status`.
- Extra routes registered via `idx.api_extra.register_extra_routes`.
- Blocks/flow honesty: `/api/stock/{ticker}/blocks` returns null (not 0) for missing numerics; whale/smart-accumulation stay null without tape.

## Gap closure (2026-09-23)
- Rebuild caches: `idx.rebuild` → `.feature_rebuild_cache.json` / `.target_risk_rebuild_cache.json` (Sync All PARTIAL pipelines).
- Universe: `idx.universe` helpers; screener meta reports skipped_due_to_cap.
- CORS: `idx.cors_config.resolve_cors_origins` driven by `RITELINSIGHT_ENV` / `RITELINSIGHT_CORS_ORIGINS`.

## Production readiness / external deps (2026-09-23)
- **Realtime:** NOT_CONFIGURED. `MarketDataProvider` capability map lists quote/tick/side/bid-ask/depth/WS/reconnect/license fields. Quality grades A/B/C/EOD_SNAPSHOT in `providers.REALTIME_DATA_QUALITY`.
- **Fan-out rule:** one server-side upstream → normalizer → bounded buffer → feature/signal → API/WebSocket. Clients never connect to vendor.
- **Auth:** local opaque sessions (`auth_session`) with TTL + logout; production IdP NOT_CONFIGURED.
- **Public static:** allowlisted `/data/{filename}` only (`public_static.PUBLIC_DATA_FILES`) — never mount whole `DATA_DIR`.
- **Ops:** `/health`, `/ready`, `/api/ops/status` (`ops_status`).
- **Decision pack:** `docs/PRODUCTION_DECISION_PACK.md` (vendor shortlists; no auto-select).

## FX / Yahoo path (2026-09-23 Agen 7)
- Default production FX: local `usd_idr_rate.json` cache → stale cache → `DEFAULT_USD_IDR_RATE` constant.
- Live Yahoo (`yfinance`) and open.er-api are **opt-in only** via env flags; not default runtime dependencies.
- Status surface: `fx_status()` on `/api/integrations` → `fx`.
- Core screener/terminal/big-money paths do **not** use Yahoo.
- Quote statuses: `live` | `cached` | `stale_cache` | `default_constant` | `unavailable`.
- `default_constant` is never `is_market_quote` / never `is_live` / never `is_verified_fx`.

## Upstream / license (code)
- Upstream: `https://github.com/nichsedge/idx-bei` — SPDX **MIT**; retain LICENSE + attribution.
- Market-data rights and trademark/rebrand are separate from code license (see pre-publish checklist in HANDOFF / DECISION_LOG).
- **SBOM / NOTICE / THIRD_PARTY_NOTICES:** not generated yet (see decision pack §R).
