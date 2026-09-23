# DECISION_LOG — RitelInsight

Settled product/architecture decisions only. No routine implementation detail.

## 2026-09-23 — Product identity
- **Decision:** Product name for commercial path is **RitelInsight**.
- **Reason:** Commercial product distinct from upstream scraper toolkit branding.
- **Note:** Full UI rebrand from “IDX Smart Money” is **deferred** until a dedicated publish/rebrand task; IDX/BEI remain data-source labels only, not product brand.

## 2026-09-23 — Project memory
- **Decision:** Source of truth for continuity = `PROJECT_STATE.md`, `ARCHITECTURE.md`, `DECISION_LOG.md`, `HANDOFF.md` (+ source code). Chat is not primary SoT.
- **Reason:** Avoid dependence on long conversation history.

## 2026-09-23 — Anti-fabrication (broker / smart money)
- **Decision:** Do not invent institutional/retail/smart-money broker attribution from hardcoded broker code lists.
- **Decision:** `detect_stealth_accumulation` remains **UNAVAILABLE** until verified broker-participant attribution exists.
- **Decision:** Foreign aggregate flow may be reported; it must not be labeled as smart money / institutional accumulation.
- **Decision:** Broker concentration may keep CR1/CR3/CR5 and rank-by-`Value`; participant Category stays unclassified without verified mapping.

## 2026-09-23 — Architecture cost/storage (principles settled)
- PostgreSQL = planned app/business DB at hosting time; not forced locally now.
- Neo4j = optional for real network/ownership needs.
- Parquet + DuckDB = valid historical/market analytics path.
- Paid realtime data allowed when required for reliable CPE; justify cost to product owner before implement.
- 2 GB RAM is efficiency target, not hard architecture ceiling.

## 2026-09-23 — Terminology P0+P1 hygiene
- **Decision:** Apply minimal hygiene only: product brand shell → **RitelInsight**; neutralize user-facing Smart Money / Institutional / active stealth–retail-trap claims.
- **Decision:** Keep module name **Bandarmology** and score name **SMSS** for now (deferred rename = product decision).
- **Decision:** Keep internal/API identifiers (`smart_money*`, stealth enums, `/api/stealth-accumulation`) for compatibility; UI must not treat them as validated live attribution.

## 2026-09-23 — Pre-publish LICENSE/IP checklist (acceptance criteria; work deferred)
- Keep upstream MIT LICENSE + attribution.
- THIRD_PARTY_NOTICES/NOTICE near production.
- Final dependency + data/API source audit before publish.
- No Yahoo/`yfinance` on production commercial path.
- IDX/BEI not product brand; rebrand “IDX Smart Money” → RitelInsight before publish.
- Verify KSEI/LHKPN usage before commercial release.
- Do not claim scraped datasets as owned without clear rights.
- Contributor/provenance check before publish.

## 2026-09-23 — Backtest PIT / entry-date contract
- **Decision:** Keep the single existing engine in `idx.backtest.run_backtest` (no second engine).
- **Decision:** For a decision on `entry_date`, features must use only data on or before that date (`history_slice` / `as_of=entry_date`). Undated fundamental filings are excluded under `as_of` (no latest-snapshot fallback).
- **Decision:** Entry fill = same-session Close on `entry_date` (bar required). Exit = Close `holding_days` unique sessions later (date-index steps). Optional SL/TP checked on later session Closes; fill at stop/target return level; `ExitDate` = trigger session.
- **Decision:** Do not invent fees/slippage/position sizing, delisting universe reconstruction, or adjusted-price series in this foundation cluster — document limitations instead.
- **Decision:** Strategy optimization / parameter tuning / production hardening are out of scope until a later explicit task.

## 2026-09-23 — Backtest result contract / CAGR
- **Decision:** `cagr_pct` is always unavailable (`null`); never mirror `total_return_pct` or label total return as CAGR in the UI.
- **Decision:** Portfolio summary return/risk/drawdown use equal-weight mean return per `ExitDate` (aligned with API equity curve). Win rate, avg trade, profit factor, and `total_trades` remain trade-level.
- **Decision:** `alpha_pct` / `benchmark_return_pct` are `null` unless a benchmark return series is supplied; do not imply IHSG outperformance without a benchmark.
- **Decision:** Zero-trade API responses use an empty equity curve (no placeholder date).

## 2026-09-23 — Strategy validation foundation
- **Decision:** Existing screens remain the only strategy entry points; `run_backtest` remains the only execution engine (no second engine / no new strategy).
- **Decision:** Historical runs with injected frames must not read `network_alpha_data.json`, live FX, or company-details JSON; default load is Parquet-only.
- **Decision:** Invalid `holding_days` / `top_n` / date range / unknown strategy return structured empty metrics (not a bare `{}`).
- **Decision:** Strategy optimization, parameter tuning, ranking, and comparison remain out of scope until an explicit later task.

## 2026-09-23 — Data Center orchestration foundation
- **Decision:** Add minimal Sync All Data orchestration on the **existing** FastAPI asyncio ingestion job runner — do not introduce Celery/Redis/microservices now.
- **Decision:** Pipeline catalog must mark UNAVAILABLE/PARTIAL honestly; Sync All must not fabricate historical ranges, KSEI ownership, feature-store rebuild, or target/risk rebuild.
- **Decision:** Independent pipeline failures yield overall PARTIAL when others succeed; false-success is forbidden.
- **Decision:** Realtime / AI / Telegram / Payment integrations remain NOT_CONFIGURED until truly wired.

## 2026-09-23 — Historical / ownership real-parameter wiring
- **Decision:** Historical backfill requires explicit `start_date`/`end_date` (YYYYMMDD or YYYY-MM-DD); never invent defaults; Sync All must not run unrestricted historical.
- **Decision:** Ownership stays Sync-All **UNAVAILABLE** without a default KSEI source; parameterized `job_type=ownership` + `path_or_url` is allowed when the operator supplies a real local file or http(s) URL.
- **Decision:** Prefer PARTIAL/UNAVAILABLE over false-success when sources are missing.

## 2026-09-23 — Screener production engine
- **Decision:** Screener results must follow DATA→FEATURE→SIGNAL→TARGET→RISK→HISTORICAL STATS; UI scoring alone is not production.
- **Decision:** Production TP/CL are structure-derived (swing, ND/52W highs-lows, ATR extensions). Fixed +3/+5/+7% or −1/−3/−5% are **not** production targets/stops. +3% remains Close Pressure **minimum opportunity filter** only.
- **Decision:** Qualified setups require RR ≥ 1:2; otherwise `NOT_QUALIFIED` with null levels — never fabricate TP2/TP3.
- **Decision:** Close Pressure without tape uses data_quality **E** (EOD snapshot); BidVolume/OfferVolume must not be labeled as trade-side dominance.
- **Decision:** Swing is a separate daily-structure engine; Long-Term labels **CANDIDATE** only; insufficient fundamentals → INSUFFICIENT DATA.
- **Decision:** Historical stats are descriptive with sample-size gating; do not claim strategy profitability until validated.

## 2026-09-23 — Completion pass auth & providers
- **Decision:** External IdP is NOT_CONFIGURED; private resources use opaque server-issued sessions (`X-Ritel-Session`). Clients must not send trusted `user_id`.
- **Decision:** AI / Telegram / Payment / Realtime remain NOT_CONFIGURED with capability contracts — never fake delivery, paid status, or tick data.
- **Decision:** Big Money Fast-In/Fast-Out stays UNAVAILABLE without stock-specific actor transactions; broker UI scope is MARKET-WIDE only.
- **Decision:** Strategy Lab must flag INSUFFICIENT OOS VALIDATION; positive historical metrics ≠ production edge.
- **Decision:** `DATA_SCHEMA_VERSION` (1.0.0) with legacy field aliases; unsupported versions marked explicitly.

## 2026-09-23 — Production gap closure
- **Decision:** Feature/Target-Risk rebuild may write **read-only derived caches** via `idx.rebuild` during Sync All; must never mutate source partitions (`mutates_source=false`).
- **Decision:** Screener `max_universe` is an explicit safety parameter; truncation must surface `skipped_due_to_cap` (never silent).
- **Decision:** Production CORS forbids wildcard; set `RITELINSIGHT_ENV=production` + `RITELINSIGHT_CORS_ORIGINS`.
- **Decision:** Ownership/foreign/broker in Big Money must label **basis** (disclosure vs aggregate vs market-wide); never call disclosure “transaction-based”.

## 2026-09-23 — External dependency / production readiness (Agen 6)
- **Decision:** Do **not** auto-select realtime vendor or IdP. Product Owner chooses from shortlist in `docs/PRODUCTION_DECISION_PACK.md`.
- **Decision:** Realtime architecture = single server-side upstream → normalize → bounded buffer → engines → app fan-out; clients never connect to vendor.
- **Decision:** Realtime quality grades A/B/C/EOD_SNAPSHOT; Bid/Offer volume must never be labeled actual buy dominance; broker identity never inferred.
- **Decision:** Keep **KSEI OWNERSHIP SOURCE NOT CONFIGURED** until a verified legal source URL/path is supplied by operator/owner.
- **Decision:** AI key presence ≠ AVAILABLE outbound; Telegram must never claim `sent=true` without upstream ack; payment webhooks must not grant entitlements while NOT_CONFIGURED.
- **Decision:** Do not mount entire `DATA_DIR` as StaticFiles; public files are allowlisted only.
- **Decision:** Implementation dependency order for externals follows pack §J (realtime → IdP → ownership → AI → notify → payment → deploy → final legal).

## 2026-09-23 — Data / license path (Agen 7)
- **Decision:** Yahoo/yfinance must not be a hidden production FX dependency. Live Yahoo and open.er-api are opt-in (`RITELINSIGHT_ALLOW_YAHOO_FX` / `RITELINSIGHT_ALLOW_OPEN_ER_API`); default path is cache → default constant with explicit lineage.
- **Decision:** `yfinance` is optional (`fx-yahoo`) / dev-test only — not a required production runtime package.
- **Decision:** IDX public API EOD paths remain production data sources but stay **LICENSE REVIEW REQUIRED** (not commercially cleared by engineering).
- **Decision:** Do not generate fabricated NOTICE/SBOM legal text; track checklist until counsel/release process produces artifacts.
- **Decision:** LHKPN remains optional/offline until data dir + legal review; absence of `lhkpn/` is expected.
- **Decision:** FX `default_constant` must never be presented as a live, verified, or current market quote; consumers must read `status` / `is_market_quote` / `is_default_constant`.

## 2026-09-23 — Final integration honesty (Agen 7)
- **Decision:** Ops WebSocket presence must not be labeled market **LIVE**; UI uses OPS WS / WS OFF. Market realtime stays NOT_CONFIGURED until a contracted provider is chosen.
- **Decision:** Missing aggregate numerics (foreign legs, VWAP, whale) must serialize as **null**, never fabricated **0**, and UI must render **—** rather than zero-as-available.
- **Decision:** Stable contract aliases (`/schema`, `/api/data-status`, `/api/stock/{t}/ownership|signals`, `/api/ai|/notifications|/payment`) return honest status payloads; they do not imply providers are configured.
- **Decision:** Production SQL analytics endpoint stays disabled; ownership local files must resolve under `DATA_DIR`; remote ownership URLs require explicit `RITELINSIGHT_ALLOW_OWNERSHIP_HTTP=1`.

## 2026-09-23 — Local Git checkpoint (Agen 7)
- **Decision:** Agents 1–7 engineering baseline is recorded as a **local commit only** (no push) when Product Owner requests checkpoint.
- **Reason:** Preserve reviewable history without publishing until external decisions / hosting are ready.

