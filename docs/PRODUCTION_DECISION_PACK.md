# PRODUCTION DECISION PACK — RitelInsight (Agen 6)

Last updated: 2026-09-23  
Status: **Decision package for Product Owner** — not an automatic vendor selection.  
Evidence: backend **295 passed**; frontend `npm run build` **passed**. No commit.

## Consistency audit stamp (final Agent 6 pass)
Cross-checked against repo on 2026-09-23. Claim status below uses:
TRUE / PARTIAL / OUTDATED(fixed) / CONTRADICTED.

---

## A. REALTIME PROVIDER SHORTLIST

Current abstraction (`MarketDataProvider`) extended with capability inventory.  
**Realtime remains NOT_CONFIGURED.** Users must never connect upstream directly.

### Capability interface (required)

| Capability | Current | Needed for CPE |
|---|---|---|
| realtime quote | NOT_CONFIGURED | Yes |
| tick / trade | NOT_CONFIGURED | Yes (tape / Fast-In-Out later) |
| timestamp / price / volume | NOT_CONFIGURED | Yes |
| trade side | NOT_CONFIGURED | Prefer AVAILABLE; else quality ≤ B |
| bid / ask / bid_vol / ask_vol | NOT_CONFIGURED | Prefer for L1 |
| orderbook / depth | NOT_CONFIGURED | Prefer Total View / L2 |
| historical intraday | NOT_CONFIGURED | Prefer |
| WebSocket / REST | NOT_CONFIGURED | At least one streaming path |
| reconnect / heartbeat / sequence | NOT_CONFIGURED | Required for production ops |
| latency / market status / symbol map | NOT_CONFIGURED | Prefer documented |
| corporate actions | NOT_CONFIGURED | Prefer |
| commercial + redistribution | NOT_CONFIGURED | **LICENSE REVIEW REQUIRED** |

Abstraction sufficiency: **sufficient for status/capability contracts**; adapter implementation deferred until contract. Minimal extension already applied (capability names + quality contract). No architecture rewrite.

### Candidates (not ranked)

| Candidate | IDX coverage | Realtime | Tick | Trade side | Bid/Ask | Depth | Hist intraday | Transport | Timestamp | Latency | Rate limits | Commercial | Redistribution | Pricing | ID entity | SLA |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **IDX Data Service / ITCH** (direct) | AVAILABLE (official) | AVAILABLE (ITCH products) | AVAILABLE (product-dependent) | PARTIAL / NOT DOCUMENTED per product | AVAILABLE (order products) | AVAILABLE (Total View / 5-level products) | PARTIAL (EOD + log products) | ITCH binary + SoupBinTCP (not public REST) | AVAILABLE (feed) | NOT DOCUMENTED publicly | NOT DOCUMENTED | AVAILABLE (license) | LICENSE REVIEW REQUIRED (unit-of-count / display) | QUOTE REQUIRED (catalogue + portal) | IDX / Indonesia | NOT DOCUMENTED publicly |
| **IQ Plus Prima** (authorized redistributor) | AVAILABLE (IDX-listed redistributor) | AVAILABLE (SCF feed marketing) | AVAILABLE (Trade records in SCF spec) | PARTIAL / NOT DOCUMENTED | AVAILABLE (Quote / Best Quote) | PARTIAL (order records; depth depth TBD in contract) | PARTIAL (historical login types in SCF) | TCP/IP text SCF (not WebSocket in public docs) | AVAILABLE | NOT DOCUMENTED | NOT DOCUMENTED | AVAILABLE | LICENSE REVIEW REQUIRED | QUOTE REQUIRED | PT IQ Plus Prima (ID) | NOT DOCUMENTED |
| **PT RTI Infokom** | AVAILABLE (IDX-listed redistributor) | AVAILABLE (marketed RT) | NOT DOCUMENTED publicly | NOT DOCUMENTED | NOT DOCUMENTED | NOT DOCUMENTED | NOT DOCUMENTED | NOT DOCUMENTED | NOT DOCUMENTED | NOT DOCUMENTED | NOT DOCUMENTED | AVAILABLE | LICENSE REVIEW REQUIRED | QUOTE REQUIRED | PT RTI Infokom (ID) | NOT DOCUMENTED |
| **IMQ / Antara** | AVAILABLE (IDX-listed redistributor) | NOT DOCUMENTED in this audit pass | NOT DOCUMENTED | NOT DOCUMENTED | NOT DOCUMENTED | NOT DOCUMENTED | NOT DOCUMENTED | NOT DOCUMENTED | NOT DOCUMENTED | NOT DOCUMENTED | NOT DOCUMENTED | AVAILABLE | LICENSE REVIEW REQUIRED | QUOTE REQUIRED | Indonesia | NOT DOCUMENTED |
| **LSEG / Refinitiv RTO WebSocket** | PARTIAL (IDX entitlement-dependent) | AVAILABLE (RTO) | PARTIAL (field-dependent) | PARTIAL / entitlement | AVAILABLE (typical MP) | PARTIAL | PARTIAL | WebSocket JSON | AVAILABLE | NOT DOCUMENTED for IDX specifically | NOT DOCUMENTED | AVAILABLE | LICENSE REVIEW REQUIRED | QUOTE REQUIRED | APAC / Indonesia contact exists | PARTIAL (enterprise) |
| **Bloomberg B-PIPE** | PARTIAL (enterprise entitlement) | AVAILABLE | PARTIAL | PARTIAL | AVAILABLE | PARTIAL | PARTIAL | API / cloud | AVAILABLE | PARTIAL (local ticker plants claimed) | NOT DOCUMENTED | AVAILABLE | LICENSE REVIEW REQUIRED | QUOTE REQUIRED | Global | PARTIAL |

**Integration effort (repo):** IDX ITCH = high (binary, NSP leased line). IQ Plus SCF = medium (TCP text normalizer). LSEG/Bloomberg = medium–high (entitlements + field mapping).

**Key risks:** redistribution/display rights; non-display usage reporting; claiming buy dominance from Bid/Offer without trade side; broker codes only if licensed.

---

## B. IDP SHORTLIST

Current: opaque local sessions (`X-Ritel-Session` / Bearer).  
**MULTI-USER IDENTITY PROVIDER NOT CONFIGURED.**

| Candidate | OIDC/OAuth | Email/pw | Social | MFA | Session mgmt | Refresh | JWT/JWK | Roles | Pricing | Commercial | ID availability | Lock-in | Self-host | Maturity |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **Auth0 / Okta** | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | Paid / free tier | AVAILABLE | Global (data residency review) | Medium–high | UNAVAILABLE (SaaS) | High |
| **Clerk** | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | PARTIAL/orgs | Per-MAU | AVAILABLE | Global | Medium (frontend coupling) | UNAVAILABLE | High |
| **Supabase Auth** | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | PARTIAL (RLS) | Generous free / low MAU $ | AVAILABLE | Global regions | Medium (if using whole stack) | PARTIAL | High |
| **Keycloak** (self-host / managed) | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | AVAILABLE | Free + ops cost | AVAILABLE | Deploy in ID possible | Low (OIDC) | AVAILABLE | High |
| **Local opaque session (current)** | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | PARTIAL (TTL+logout) | UNAVAILABLE | UNAVAILABLE | UNAVAILABLE | N/A | Dev/staging only | Local | None | N/A | Adequate for single-node demo |

Indonesia PDP / residency: treat as **LEGAL REVIEW REQUIRED** for any foreign SaaS IdP.

---

## C. KSEI / OWNERSHIP STATUS

**KSEI OWNERSHIP SOURCE NOT CONFIGURED**

- Expected format: CSV columns `DATE, SHARE_CODE, ISSUER_NAME, INVESTOR_NAME, TOTAL_HOLDING_SHARES, PERCENTAGE` (+ optional investor type fields).
- Adapter: `idx.core.ownership.ingest_ksei_ownership` via `job_type=ownership` + explicit `path_or_url`.
- Public disclosure: IDX/KSEI publish >1% ownership **monthly via IDX announcements** (PDF) — **no verified stable machine API/URL configured in repo**.
- Do not fabricate default URL. Operator-supplied local CSV or http(s) only.
- Licensing for commercial redistribution of ownership lists: **LEGAL REVIEW REQUIRED**.

---

## D. AI / TELEGRAM / PAYMENT

| Integration | Status | Notes |
|---|---|---|
| AI | NOT_CONFIGURED (no key) / PARTIAL (key present, outbound disabled) | Never returns `is_ai_generated=true` without approved adapter |
| Telegram | NOT_CONFIGURED / PARTIAL | `sent` always false until outbound wired |
| Payment | NOT_CONFIGURED | Webhook rejects; `paid=false`; no entitlement grant |

---

## E. PRODUCTION SECURITY (repo-solvable)

Fixed this pass:
- Removed world-readable `/data` StaticFiles mount → allowlisted `/data/{filename}` only
- Session TTL + logout invalidation
- Strip client `user_id` / identity fields
- Ticker sanitization (injection boundary)
- CORS: wildcard cannot pair with credentials
- Production-safe error detail helper + global handler
- Payment webhook hard-reject
- Regression tests in `test_production_readiness.py`

Still open (need IdP / infra):
- Full OIDC, CSRF for cookie sessions (N/A while header tokens), durable session store, HTTPS termination at reverse proxy

---

## F. DEPLOYMENT STATUS — PARTIAL

| Item | Status |
|---|---|
| Env config (`RITELINSIGHT_ENV`, CORS, session TTL) | AVAILABLE |
| `/health` | AVAILABLE |
| `/ready` `/api/ready` | AVAILABLE (fails if prod CORS empty) |
| `/api/ops/status` | AVAILABLE |
| Secret management | PARTIAL (env vars only) |
| Rate limiting (API edge) | UNAVAILABLE |
| Graceful shutdown / process supervisor | NOT DOCUMENTED in app (rely on host) |
| Cloud deploy | NOT DONE |

---

## G. COMMERCIAL / IP STATUS

| Asset | Path class | Action |
|---|---|---|
| Upstream MIT (`nichsedge/idx-bei`) | PRODUCTION code lineage | Attribution required; keep LICENSE |
| IDX public scrape / EOD endpoints | PRODUCTION data path | Data redistribution review required |
| `yfinance` / Yahoo FX in `currency.py` | **GATED** — opt-in only (`RITELINSIGHT_ALLOW_YAHOO_FX`); removed from default runtime deps | Prefer cache/constant or contracted FX; LICENSE_REVIEW_REQUIRED if enabled |
| KSEI ownership CSVs | PRODUCTION when operator-supplied | Legal review + source license |
| LHKPN / KPK | OPTIONAL / graph path | Legal review before commercial claim |
| TradingView Lightweight Charts | PRODUCTION frontend | License terms review |
| THIRD_PARTY_NOTICES / SBOM | MISSING | Required near publish |
| Fake realtime / paid / AI | FORBIDDEN | Remains unavailable |

---

## H. EXACT REPO GAPS STILL OPEN

1. Realtime adapter + single-ingestion fan-out (not implemented)
2. Production IdP integration
3. Default KSEI ownership URL / licensed feed
4. AI outbound adapter
5. Telegram outbound send + delivery ack
6. Payment provider + signed webhooks + entitlement state machine
7. NOTICE / THIRD_PARTY_NOTICES / SBOM
8. FX commercial source (cache/constant vs opt-in Yahoo after legal review vs contracted FX) — Yahoo already gated, not hidden
9. API edge rate limiting
10. Durable session / app DB at hosting time
11. Durable queue only if scale evidence requires

---

## I. EXACT EXTERNAL DECISIONS REQUIRED FROM PRODUCT OWNER

1. Contract realtime source (direct IDX vs authorized redistributor vs terminal vendor)
2. Confirm commercial display + redistribution rights for chosen feed
3. Select production IdP (managed OIDC vs self-host) + PDP residency posture
4. Decide ownership ingestion policy (manual monthly CSV vs automated legal source)
5. Decide whether AI is in MVP scope (provider + budget + data boundary)
6. Decide Telegram notifications scope
7. Decide payment/entitlement provider (or defer monetization)
8. Approve FX source (keep cache/constant, opt-in Yahoo after legal review, or contract FX)
9. Approve hosting / reverse-proxy / TLS model
10. Authorize final legal publish checklist (NOTICE/SBOM/trademark)

---

## J. RECOMMENDED DECISION SEQUENCE

(Implementation dependency order — **not** vendor ranking.)

1. Select/contract realtime source (+ license terms)
2. Configure realtime adapter (single upstream → normalizer → cache → API WS)
3. Select/contract production IdP
4. Configure auth (replace opaque local sessions for production users)
5. Resolve ownership source (manual OK until API exists)
6. Resolve AI if product needs it
7. Resolve notifications
8. Resolve payment / entitlements
9. Production deployment (CORS, TLS, secrets, ready probes)
10. Final security + license/SBOM audit

---

## Realtime architecture (validated against current repo)

```
Provider (licensed)
  → Single ingestion connection (server-side only)
  → Normalizer (symbol, ts UTC, quality grade)
  → Cache / bounded event buffer
  → Feature engine → Signal engine
  → API / app WebSocket fan-out
  → Frontend users
```

Lifecycle: connect → heartbeat → stale detection → reconnect with backoff → outage → degrade to EOD_SNAPSHOT.  
Duplicate/sequence handling at normalizer. Backpressure via bounded buffer drop-oldest + metrics.  
No Redis/Celery unless concrete scale evidence.

Quality grades: **A** actual trade+side · **B** inferred side · **C** OHLCV proxy · **EOD_SNAPSHOT**.  
Never label BidVolume>OfferVolume as buy dominance; never invent broker identity.

---

# AGEN 7 ADDENDUM — DATA / LICENSE PATH AUDIT (2026-09-23)

Legend for rows below: **FACT** = verified in repo · **CODE OBSERVATION** = traced call path · **LICENSE UNKNOWN** = no clearance claimed · **PRODUCT DECISION REQUIRED**.

---

## K. Data Source Matrix

| Source | Class | Used by | Status |
|---|---|---|---|
| IDX `/TradingSummary/GetStockSummary` | PRODUCTION ingestion | daily/backfill → parquet → screener/terminal/signals/big-money/strategy | LICENSE REVIEW REQUIRED (commercial redistribution) |
| IDX `/TradingSummary/GetBrokerSummary` | PRODUCTION ingestion | daily/backfill → broker concentration / Big Money MW | LICENSE REVIEW REQUIRED |
| IDX `/TradingSummary/GetIndexSummary` | PRODUCTION ingestion | daily/backfill | LICENSE REVIEW REQUIRED |
| IDX `/ListedCompany/GetCompanyProfiles(+Detail)` | PRODUCTION ingestion | company profiles / dividend details JSON | LICENSE REVIEW REQUIRED |
| IDX `/DigitalStatistic/GetApiDataPaginated` | PRODUCTION ingestion | financial ratios | LICENSE REVIEW REQUIRED |
| IDX `/ListingActivity/GetIssuedHistory` | PRODUCTION ingestion | corporate actions | LICENSE REVIEW REQUIRED |
| IDX `/ExchangeMember/GetBrokerSearch` | PRODUCTION / optional | broker name map | LICENSE REVIEW REQUIRED |
| IDX `/NewsAnnouncement/*` | OPTIONAL | news CLI/scrapers | LICENSE REVIEW REQUIRED |
| IDX `/ListedCompany/GetTradingInfoSS` | DEAD/UNUSED for SPA screener | `close_pressure_data.py` helper only — **not** wired into `idx.screener.engine` | LICENSE REVIEW REQUIRED if enabled later |
| GetStockChart / GetTradingInfoDaily | NOT PRESENT in code | — | — |
| Local Parquet `stock_summary` / `broker_summary` | PRODUCTION analytics | API feature/signal path (no live IDX on read) | Derived from IDX scrape — rights follow source |
| `network_alpha_data.json` | PRODUCTION cache / public allowlist | dashboard / terminal company meta | Derived |
| Yahoo / yfinance USDIDR | OPT-IN ONLY (not default production) | FX for dividend USD + dividend_arbitrage backtest + daily refresh | LICENSE REVIEW REQUIRED; gated |
| open.er-api.com | OPT-IN ONLY | FX fallback | LICENSE REVIEW REQUIRED; gated |
| Local `usd_idr_rate.json` / default constant | PRODUCTION FX path (default) | dividend / backtest / daily | FACT: default when live FX not allowed |
| KSEI ownership CSV | OPTIONAL parameterized | Big Money disclosure when file present; ingest via `path_or_url` | **KSEI OWNERSHIP SOURCE NOT CONFIGURED** |
| LHKPN JSON dir | NOT PRESENT / OPTIONAL CLI+MCP | `idx lhkpn` / MCP tool — no `lhkpn/` in repo | LEGAL REVIEW if wired commercially |
| Neo4j | OPTIONAL | graph CLI | Ops decision |

---

## L. YFinance / Yahoo Production Path

### Occurrence map (CODE OBSERVATION)

| SOURCE | FILE | FUNCTION | CALLER | API? | Frontend? | Ingestion? | Test/Dev? | Fallback? | Purpose | Class |
|---|---|---|---|---|---|---|---|---|---|---|
| yfinance | `idx/core/currency.py` | `_fetch_live_quote` / `fetch_live_usd_idr_rate` | `resolve_usd_idr_quote` | Indirect | No | daily refresh | unit tests | Opt-in only | USD/IDR FX | GATED (was hidden PRODUCTION) |
| Yahoo email strings | `data/*Companies*.json` | — | scraped company profile emails | N/A | N/A | N/A | N/A | N/A | Contact fields containing “yahoo.com” | NOT a Yahoo Finance dependency |

### Traced production chains (before / after Agen 7)

**Before:**  
`GET /api/dividend/{ticker}` → `analyze_stock_dividend` → `get_usd_idr_rate()` → could silently call yfinance  
`POST /api/backtest` (dividend_arbitrage) → `get_usd_idr_rate()` → yfinance  
`ingest_daily` → `get_usd_idr_rate(force_refresh=True)` → yfinance  

**After (FACT):**  
Same callers → `resolve_usd_idr_quote` / `get_usd_idr_rate` → **cache → (opt-in live) → stale cache → default_constant**  
Yahoo only if `RITELINSIGHT_ALLOW_YAHOO_FX=1`. Default path has `hidden_yahoo_production_dependency=false`.

### What still depends on FX (not on Yahoo specifically)

| Data need | Can replace from IDX/local? | Needs external? | Required for core CPE? |
|---|---|---|---|
| USD cash dividend conversion | No IDX FX in warehouse | YES — FX source | PARTIAL (IDR prices work without FX) |
| Dividend arbitrage USD events | Local stock bars + details | FX only for USD cash | Strategy Lab optional path |
| Screener / Terminal / Big Money / Watchlist | Local parquet | No | Core — **no Yahoo** |
| Chart OHLCV | Local parquet | No | Core — **no Yahoo** |

### Can yfinance be removed from production path?

**FACT: YES for default production.** Moved to optional extra `fx-yahoo` + dev test dep. Runtime no longer requires the package. Live Yahoo remains available only after opt-in + legal review.

### FX fallback honesty (final follow-up)

| status | is_live | is_market_quote | is_default_constant | is_verified_fx | quality |
|---|---|---|---|---|---|
| `live` | true | true | false | **false** (opt-in feeds are not contracted/verified) | C |
| `cached` | false | true | false | false | B |
| `stale_cache` | false | true | false | false | C |
| `default_constant` | false | **false** | **true** | false | CONSTANT |
| `unavailable` | false | false | false | false | U |

- `default_constant` notes explicitly state it is **not** a live/verified/current market quote.
- Dividend analysis + dividend_arbitrage backtest attach `usd_idr` / `fx` lineage on results.
- Inventory `/system/usd_idr` carries the same honesty fields (not rate-only).
- Frontend has no dedicated FX market-quote UI; TypeScript type extended so rate alone is not assumed to be live.

---

## M. IDX Data Path (production)

| Endpoint | Feature | Data type | Freshness | License |
|---|---|---|---|---|
| GetStockSummary | Screener, Terminal, Signals, Strategy Lab, Big Money foreign | EOD OHLCV + foreign aggregates | Daily ingest / backfill | LICENSE REVIEW REQUIRED |
| GetBrokerSummary | Bandarmology CR / Big Money MW | EOD broker turnover | Daily | LICENSE REVIEW REQUIRED |
| GetIndexSummary | Index partitions | EOD index | Daily | LICENSE REVIEW REQUIRED |
| GetCompanyProfiles(+Detail) | Company meta, dividends list | Snapshot JSON | Periodic scrape | LICENSE REVIEW REQUIRED |
| GetApiDataPaginated | Financial ratios | Snapshot | Periodic | LICENSE REVIEW REQUIRED |
| GetIssuedHistory | Corporate actions | Event history | Periodic | LICENSE REVIEW REQUIRED |
| GetBrokerSearch | Broker directory | Reference | Periodic | LICENSE REVIEW REQUIRED |
| GetTradingInfoSS | Close-pressure SS helper | Session snapshot fields | **Not wired to production screener** | LICENSE REVIEW REQUIRED if used |

Do **not** mark commercially allowed without evidence. **LICENSE REVIEW REQUIRED** (not GREEN).

---

## N. Ownership / KSEI

- **Status:** KSEI OWNERSHIP SOURCE NOT CONFIGURED  
- **FACT:** No default production URL in ingest validation.  
- **CODE OBSERVATION:** Local sample `data/1%ownership-2026-02-27.csv` may exist for analytics when present; Sync All does not ingest ownership.  
- **PRODUCT DECISION REQUIRED:** manual monthly CSV vs automated licensed source.  
- Redistribution of ownership lists: LICENSE UNKNOWN / LEGAL REVIEW REQUIRED.

---

## O. LHKPN / KPK

- **FACT:** `lhkpn/` directory **NOT PRESENT** in this workspace.  
- **CODE OBSERVATION:** `idx.lhkpn_radar` + CLI `idx lhkpn` + MCP tool exist; degrade empty when dir missing.  
- **Not** on FastAPI SPA critical path (Screener/Terminal/Big Money/etc.).  
- Class: OPTIONAL / NOT CONFIGURED for production product surface.  
- Commercial redistribution of KPK LHKPN: LEGAL REVIEW REQUIRED (public ≠ redistributable).

---

## P. Dependency License Status

### Direct Python runtime (`python/pyproject.toml`) — known SPDX (package license ≠ data rights)

| Package | Known license (code) | Notes |
|---|---|---|
| fastapi, uvicorn, duckdb, curl_cffi, python-dotenv, tqdm | MIT / BSD-class | FACT: common permissive |
| pyarrow, neo4j | Apache-2.0 | FACT |
| yfinance | optional `fx-yahoo` / dev | Apache-2.0 code; **Yahoo data ToS separate** |

No direct **GPL / AGPL / SSPL** identified in declared runtime dependencies.  
**SBOM NOT YET GENERATED** — transitive certainty not claimed.

### Direct frontend (`frontend/package.json`)

| Package | Common license | Notes |
|---|---|---|
| react, react-dom | MIT | |
| lucide-react | ISC | |
| lightweight-charts | Apache-2.0 | TradingView terms for commercial display — REVIEW |
| vis-network, vis-data | Apache-2.0 / MIT | |
| vite, typescript | MIT (dev) | |

**SBOM NOT YET GENERATED** for lockfile transitive tree.

---

## Q. Dataset Shipping Audit (selected)

| Dataset | Type | Source | Prod used? | Redistribution review? | Action |
|---|---|---|---|---|---|
| `timeseries/`, `parquet/` | Source partitions / exports | IDX scrape | YES | YES | Keep; rights follow IDX |
| `network_alpha_data.json` | Derived cache | Local pipeline | YES (UI) | YES | Allowlisted public file |
| `companyDetailsByKodeEmiten.json` | Snapshot | IDX company detail | YES (dividend) | YES | |
| `1%ownership-*.csv` | Source snapshot | KSEI via IDX disclosure | OPTIONAL | YES | No default URL |
| `usd_idr_rate.json` | Cache | Prior FX resolve | YES | Low | Lineage in file |
| `briefings/` | Derived | signals | OPTIONAL | YES | |
| `backtest_*.json` | Lab results | Local | DEV/ANALYTICS | N/A | Not product entitlement |
| `idx_*endpoints*.txt` | Research dumps | IDX site inspection | DEV | N/A | Not ship to customers as product data |
| `.feature_rebuild_cache.json` etc. | Derived cache | rebuild | INTERNAL | N/A | Private; not via `/data` |

Do **not** delete. Classify and gate packaging at release time.

---

## R. NOTICE / SBOM Checklist (technical — not legal text)

**Present:** `LICENSE` (MIT).  
**Missing:** `NOTICE`, `THIRD_PARTY_NOTICES`, SBOM artifact.

Before commercial distribution, generate:

1. Retain upstream MIT copyright + LICENSE copy.  
2. `THIRD_PARTY_NOTICES` listing direct + key transitive OSS licenses (from SBOM).  
3. Machine-readable SBOM (e.g. CycloneDX/SPDX from `uv` + `npm`).  
4. Separate **data-rights** schedule: IDX, KSEI, FX, LHKPN, charting.  
5. Trademark check: product is RitelInsight; IDX/BEI are source labels only.  
6. Confirm no customer ship of research dumps / private stores.

**Do not** invent NOTICE legal prose in-repo without counsel.

---

## S. Production dependency graph

```
Frontend (SPA)
  ↓
FastAPI (/api/*)
  ↓
Feature / Signal / Screener / Terminal / Big Money / Strategy
  ↓
DuckDB + Parquet + JSON caches          [VERIFIED local]
  ↓
Ingestion scrapers (daily/backfill)      [REVIEW REQUIRED — IDX public API]
  ↓
www.idx.co.id/primary/*                  [LICENSE REVIEW REQUIRED]

FX side-path:
  dividend / dividend_arbitrage / daily
    → currency.resolve_usd_idr_quote
      → local cache / default_constant   [VERIFIED default]
      → Yahoo / open.er-api              [NOT CONFIGURED unless opt-in; LICENSE REVIEW]

Ownership side-path:
  Big Money disclosure / ownership job
    → operator CSV/URL                   [NOT CONFIGURED]

LHKPN:
  CLI/MCP only                           [NOT PRESENT / DEV-OPTIONAL]

Realtime:
  MarketDataProvider                     [NOT CONFIGURED]
```

---

## T. Exact unresolved legal / data-rights questions

1. May RitelInsight commercially display/redistribute IDX EOD fields obtained via public website APIs?  
2. Display vs non-display license for any future realtime feed?  
3. Rights to ship or display KSEI >1% ownership extracts?  
4. Rights to use/redistribute LHKPN/KPK filings if later enabled?  
5. Approve FX: constant/cache only vs contracted FX vs opt-in Yahoo after ToS review?  
6. TradingView Lightweight Charts commercial terms acceptable?  
7. Who produces NOTICE/SBOM and signs off before publish?

---

## U. Can realtime-provider decision safely proceed?

**YES — for Product Owner shortlist / contracting discussion.**  
Blocking for *go-live with realtime* remains: signed license + adapter.  
Blocking for *EOD product commercial publish* remains: IDX/KSEI data-rights + NOTICE/SBOM — **independent** of which realtime vendor is chosen.  
Yahoo is no longer a hidden blocker on the default path.

---

## V. FINAL CONSISTENCY AUDIT (Agent 6 close)

| Claim | Verdict vs code |
|---|---|
| Realtime NOT_CONFIGURED | **TRUE** (`/api/realtime/status`, integrations) |
| IdP NOT_CONFIGURED; local opaque sessions | **TRUE** (`auth_session`) |
| KSEI OWNERSHIP SOURCE NOT CONFIGURED | **TRUE** (`validate_ownership_path_or_url`) |
| AI / Telegram / Payment not production-ready | **TRUE** (no outbound success; payment webhook rejects) |
| yfinance not hidden production dep | **TRUE** (opt-in env; optional `fx-yahoo`) |
| FX default_constant not market quote | **TRUE** (`is_market_quote=false`, quality CONSTANT) |
| IDX EOD = production analytics path | **TRUE** + **LICENSE REVIEW REQUIRED** |
| Big Money Fast-In/Out UNAVAILABLE | **TRUE** |
| Stock-specific broker UNAVAILABLE | **TRUE** |
| Strategy Lab OOS / some strategies UNAVAILABLE | **TRUE** (PARTIAL overall) |
| Security PARTIAL (repo fixes done; IdP open) | **TRUE** |
| Deployment PARTIAL | **TRUE** |
| NOTICE/SBOM missing | **TRUE** |
| Evidence “280 tests” | **OUTDATED → fixed** to 295 |

### Product matrix (final)

| Area | Status | Rule note |
|---|---|---|
| Screener | GREEN | Functional + tested + honest EOD quality |
| Stock Terminal | GREEN | EOD; orderbook/tape NOT_CONFIGURED labeled |
| Big Money | PARTIAL | Disclosure/foreign/MW broker; Fast-In/Out UNAVAILABLE |
| Strategy Lab | PARTIAL | Runnable EOD strategies; OOS / some modes UNAVAILABLE |
| Data Center | GREEN | Orchestrates real pipelines; honest UNAVAILABLE rows |
| Watchlist | GREEN | Session-scoped (IdP still NOT_CONFIGURED) |
| Trading Plan / Journal | GREEN | Session-scoped |
| AI | UNAVAILABLE | External adapter/credentials |
| Telegram | UNAVAILABLE | External token/send |
| Payment | UNAVAILABLE | External provider |
| Realtime | UNAVAILABLE | External feed |
| Auth / IdP | PARTIAL | Local session works; multi-user IdP NOT_CONFIGURED |
| Schema | GREEN | |
| Security | PARTIAL | Repo-solvable items closed; production IdP/HTTPS open |
| Performance | PARTIAL | |
| Observability | PARTIAL | `/ready`, `/api/ops/status` present |
| Deployment readiness | PARTIAL | No cloud deploy |
| Commercial / IP | PARTIAL | LICENSE REVIEW + NOTICE/SBOM open |

No BROKEN surfaces found in this audit.
