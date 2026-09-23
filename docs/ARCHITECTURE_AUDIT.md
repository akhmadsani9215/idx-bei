# [BRAND_NAME] Architecture Audit

**Status:** PHASE 1 COMPLETE — NO LARGE REWRITE YET  
**Date:** 2026-09-23  
**Repo:** `C:\Users\ThinkPad T495s\Downloads\idx-bei`  
**Excel reference:** `Trading Plan & Jurnal_V1.xlsx` (audited separately → `docs/TRADING_PLAN_JOURNAL_MAPPING.md`)

---

## Executive verdict

Existing repo is a **working but half-productized** IDX/BEI quantitative toolkit:

- Strong: EOD scrape → Parquet → signals → FastAPI → React SPA skeleton.
- Weak: product IA (tabs), brand (“Alpha”), auth/account data, honest data-quality UX, dynamic TP/CL/RR engine, account-private watchlist/journal, single SYNC ALL orchestration, realtime abstraction.
- Honest code already exists in places (e.g. blocks endpoint refuses synthesis; stealth accumulation returns `UNAVAILABLE`). Preserve that honesty — do not regress into fabrication.

**Goal:** evolve this codebase into `[BRAND_NAME] Market Intelligence` — **not** a greenfield demo rewrite.

---

## A. Repository map

```
idx-bei/
├── AGENTS.md, README.md, LICENSE (MIT), DATA_OWNERSHIP.md
├── pyproject.toml          # uv workspace root → python/
├── docker-compose.yml
├── docker-compose/         # neo4j, postgres, metabase
├── python/
│   ├── src/idx/            # core package (src-layout)
│   ├── tests/              # pytest suite
│   ├── backtest_lab.py, backtest_v3*.py  # experimental labs (not wired to UI)
│   └── analyze_network_alpha.py         # builds network_alpha_data.json
├── frontend/               # React 19 + Vite + TS SPA
├── dashboard/              # legacy vanilla HTML fallback
├── data/                   # JSON, parquet, timeseries, briefings, research dumps
└── docs/                   # this audit + dividend guide + plans
```

Approximate local `data/` footprint observed: **~89 MB** (mostly `stock_summary.parquet` ~14 MB + JSON snapshots + research artifacts).

---

## B. Frontend map

### Active route shell (`App.tsx`)

| Tab id (code) | UI label today | Component | Target product tab |
|---|---|---|---|
| `opportunities` | Alpha Finder | `AlphaHub.tsx` | **TAB 1 Screener** (needs redesign) |
| `terminal` | Stock Terminal | `ChartTab.tsx` | **TAB 2 Stock Terminal** |
| `power_map` | Tycoons & Power Map | `PowerMapTab.tsx` | partial → **TAB 3 Big Money** (ownership/UBO only; rename + expand) |
| `simulator` | Strategy Simulator | `BacktesterTab.tsx` | **TAB 4 Strategy Lab** |
| `ingestion` | Data Ingestion | `IngestionTab.tsx` | **TAB 5 Data Center** |
| *(drawer)* | Watchlist | `WatchlistDrawer.tsx` + `useWatchlist` | **TAB 6 Watchlist** (must become real tab + server-owned) |
| *(missing)* | — | — | **TAB 7 Trading Plan & Journal** |

Routing: hash-based (`#terminal?ticker=BBCA`). Titles still branded “IDX Smart Money / Alpha Finder”.

### Orphan / dead UI components (defined, never mounted from `App.tsx`)

| File | Notes |
|---|---|
| `ScreenerTab.tsx` | Full screener UI exists but **not wired** |
| `BandarmologyTab.tsx` | Orphan |
| `DividendTab.tsx` | Orphan (dividend still reachable via AlphaHub API calls) |
| `MethodologyTab.tsx` | Orphan |
| `InsidersTab.tsx` | Orphan (used only by ConglomeratesTab for `formatCurrency`) |
| `ConglomeratesTab.tsx` | Orphan (PowerMap embeds similar concepts) |
| `CompanyDrawer.tsx` | Orphan |

**Implication:** do not rewrite Screener from zero — evaluate `ScreenerTab.tsx` + `AlphaHub.tsx` first, then merge into TAB 1 product IA.

### Supporting frontend

- `Header.tsx` — brand + 5 tabs + watchlist/alerts chips; **missing** market/data/EOD/realtime/provider/quality strip required by product.
- `services/api.ts` — thin fetch helpers; falls back to static `network_alpha_data.json`.
- `hooks/useDashboardData.ts`, `useLiveStream.ts`, `useWatchlist.ts`.
- Modals: `DailyBriefingModal`, `InvestorMemoModal`.
- Charts: TradingView `lightweight-charts` v5 in `ChartTab`.
- Graphs: `vis-network` in `NetworkGraph`.

---

## C. Backend map

| Module | Role |
|---|---|
| `idx/api.py` | FastAPI REST + WebSocket + static mounts |
| `idx/cli.py` | Unified `idx` CLI |
| `idx/signals.py` | 7 screens + briefing builder |
| `idx/backtest.py` | Vectorized strategy backtester |
| `idx/dividend.py` | Dividend / trap risk |
| `idx/ingestion.py` | Inventory, gaps, tiers, async jobs |
| `idx/graph.py` | Neo4j UBO / centrality / cross-holdings |
| `idx/lhkpn_radar.py` | LHKPN cross-ref (politics ownership split noted in DATA_OWNERSHIP.md) |
| `idx/close_pressure_config.py` | Internal BEI session windows (14:30–16:02, next open) |
| `idx/close_pressure_data.py` | EOD trading-info normalize; labels book pressure as EOD snapshot proxy |
| `idx/core/*` | HTTP client, DuckDB query, timeseries, ownership, currency |
| `idx/scrapers/*` | company, financial, corporate, members, news, trading, historical |
| `idx/pipelines/*` | daily ingestion, parquet export |
| `idx/mcp/server.py` | MCP tools for AI assistants |

Experimental (not product API): `python/backtest_v3*.py`, `backtest_lab.py`, `analyze_network_alpha.py`.

---

## D. API map (current)

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | OK |
| GET | `/api/dashboard-data` | Reads `network_alpha_data.json` |
| GET | `/api/companies` | Same file |
| GET | `/api/signals` | Daily briefing |
| GET | `/api/stock/{ticker}` | OHLCV + indicators (default last 120) |
| GET | `/api/stock/{ticker}/blocks` | **Honest:** empty blocks; no synthetic broker blocks |
| GET | `/api/broker-flow` | Market-wide broker concentration |
| GET | `/api/peers/{ticker}` | Fundamentals peers |
| GET | `/api/dividend`, `/api/dividend/{ticker}` | Dividend |
| GET | `/api/drift` | KSEI ownership drift |
| GET | `/api/graph/ubo|network|centrality|cross-holdings` | Neo4j-dependent |
| POST | `/api/query/sql` | DuckDB SQL — **high privilege** |
| GET | `/api/stealth-accumulation` | Returns unavailable path |
| POST | `/api/backtest` | Sync heavy compute on request |
| GET/POST | `/api/system/ingestion-status`, `trigger-ingestion`, jobs | Data center |
| WS | `/ws/stream` | Live events (ingestion / alerts) |
| STATIC | `/data/*` | **Entire DATA_DIR publicly mounted** |
| STATIC | `/dashboard`, `/assets` | SPA |

### Missing vs target product API

`/api/screener`, `/api/stock/.../chart|flow|foreign|broker|ownership|signals`, `/api/big-money`, `/api/strategy` (lab), `/api/data-status`, `/api/watchlist`, `/api/trading-plan`, `/api/journal`, `/api/ai` stubs, auth endpoints.

---

## E. Data-source map

| Source | What we get | Quality label | Used by |
|---|---|---|---|
| IDX public web APIs via `curl_cffi` client | Company, trading summary, financial ratios, corporate actions, brokers directory, news/announcements | EOD / snapshot; **not true tick** | scrapers, close_pressure_data |
| `GetTradingInfoSS` | OHLCV, foreign buy/sell shares, bid/offer snapshot | EOD; book imbalance = **EOD_SNAPSHOT_ONLY** | CPE data layer |
| KSEI ownership CSVs | Holder % drift | Disclosure-based, periodic | ownership / drift |
| Neo4j (optional) | UBO graph | Depends on ingest | graph endpoints |
| USD/IDR cache / yfinance fallback | FX | Best-effort | currency |
| `network_alpha_data.json` | Aggregated company scores, insiders, conglomerates | Derived batch artifact | Dashboard / AlphaHub |
| Parquet exports | Analytical EOD bars | EOD | signals, backtest, stock terminal |

### DATA UNAVAILABLE (must stay unavailable until real provider)

- True tick / trade side / transaction tape
- Historical orderbook / market depth time series
- Stock-specific broker buy/sell pairs (for bandar / fast-in-out)
- Realtime foreign intraday
- AI / Telegram / Payment (future stubs only)

---

## F. Database / storage map

| Store | Purpose | Prod readiness |
|---|---|---|
| `data/timeseries/` partitions | Daily scrapes | Core |
| `data/parquet/*.parquet` | Analytical exports | Core (~14 MB stock_summary) |
| `data/*.json` snapshots | Dashboard / research | Mixed; some research dumps |
| DuckDB (query layer) | Ad-hoc SQL | Dev-friendly; `/api/query/sql` risky |
| Neo4j | Graph | Optional; docker-compose |
| PostgreSQL compose | Defined | Not clearly primary for app state |
| Browser `localStorage` | Watchlist | **Not account-safe** |
| *(missing)* SQLite/Postgres user DB | auth, watchlist, plan, journal | **Required for TAB 6–7** |

**Proposed for 2 GB single-node:** SQLite (or single Postgres) for account data; Parquet for market analytics; **no Redis/Celery** unless proven necessary.

---

## G. Signal-engine map

Current screens in `signals.py`:

1. Foreign Flow Radar  
2. Audit Risk Shield  
3. Dilution Watch  
4. Sharia Value  
5. Pasar Nego Crossing  
6. Bandarmology / Broker Concentration (**market-wide**)  
7. Composite Alpha Ranking  
+ Stealth Accumulation → **intentionally UNAVAILABLE** without broker attribution  
+ Technical indicators (RSI, EMA, Bollinger, ATR)

Close Pressure Engine:

- Config windows match product INTERNAL windows (`close_pressure_config.py`).
- Data layer correctly marks book pressure as EOD proxy.
- **Not yet** exposed as full TAB 1 Intraday mode with dynamic TP/CL/RR/historical stats.

---

## H. Backtest-engine map

| Piece | Status |
|---|---|
| `idx/backtest.py` | Live strategies: foreign_flow, bandarmology, sharia_value, composite_alpha, dividend_arbitrage; fixed SL/TP %; Sharpe/drawdown/alpha |
| `BacktesterTab` | UI posts to `/api/backtest` **on user click** (heavy) |
| `backtest_v3*` / lab JSON | Offline research artifacts | not productized |
| Walk-forward / OOS / sensitivity / robustness UI | Missing in product (partial offline labs) |
| Dynamic TP/CL RR≥2 engine | Missing |
| Big Money Fast-In/Out backtest | Missing; **blocked by data** for broker/person transaction-level |

---

## I. Route / page map (current vs target)

```
CURRENT                          TARGET
─────────────────────────────────────────────────────
Alpha Finder                  →  Screener (Intraday / Swing / Long-Term)
Stock Terminal                →  Stock Terminal (expanded)
Tycoons & Power Map           →  Big Money (ownership + honest gaps)
Strategy Simulator            →  Strategy Lab
Data Ingestion                →  Data Center (SYNC ALL + auto)
Watchlist drawer              →  Watchlist tab (account)
—                             →  Trading Plan & Journal tab
```

---

## J. Dependency map

**Python (workspace):** FastAPI, pandas, DuckDB, curl_cffi, Neo4j driver, pytest, ruff, mypy, uv.  
**Frontend:** React 19, Vite 6, lightweight-charts 5, lucide-react, vis-network.  
**Infra optional:** Docker Neo4j / Postgres / Metabase.

License of codebase: **MIT** (`LICENSE`).

---

## K. Existing functionality (keep / harden)

- EOD scrape + parquet + daily status/gaps
- Stock OHLCV chart + indicators API
- Foreign flow / dilution / audit / sharia / nego screens
- Market-wide broker concentration (label correctly)
- Dividend analyzer
- Ownership drift + UBO graph (when Neo4j populated)
- Blocks endpoint honesty (no synthetic broker blocks)
- Stealth accumulation honest UNAVAILABLE
- Close pressure time-window config + EOD proxy labeling
- WebSocket ingestion events
- MCP server

---

## L. Broken / fragile functionality

| Item | Issue |
|---|---|
| Watchlist | localStorage only; seeded fake BBCA/BBRI prices; not multi-user |
| AlphaHub “stealth” UX | Can imply smart money even when backend says UNAVAILABLE |
| Briefing fallback in AlphaHub | Synthesizes briefing-shaped object from companies.slice — **risk of looking like real alpha rankings** |
| Graph endpoints | Fail if Neo4j down — need graceful UNAVAILABLE |
| `/api/query/sql` | Unauthenticated arbitrary query surface |
| Static `/data` | Exposes warehouse/JSON publicly |
| Orphan tabs | ScreenerTab etc. unused → confusion / drift |
| Schema | Frontend `Company` vs JSON fields historically mismatched (many `.bak-*` files show past pain) |
| Backtest on HTTP | Blocks worker; bad for 2 GB multi-user |

---

## M. Missing functionality (vs product Definition of Done)

- Product header data-status strip (honest)
- TAB 1 modes: Intraday Close Pressure / Swing / Long-Term
- Dynamic TP1–3, CL1–3, RR≥2 qualification, Entry Zone
- Historical MFE/MAE/hit rates with sample-size gating
- Dormant→Active lifecycle states
- Transaction tape / orderbook UI with UNAVAILABLE states
- Stock-specific broker only when source proves it
- Big Money Fast-In/Out (data-gated)
- Strategy Lab: walk-forward, OOS, robustness, bias warnings
- Data Center: single SYNC ALL + automatic schedules
- Account auth + private Watchlist / Plan / Journal
- AIProvider / NotificationProvider / Entitlement stubs
- MarketDataProvider abstraction + REALTIME NOT CONFIGURED
- Schema versioning (`DATA_SCHEMA_VERSION`)
- Metric lineage metadata on every important field

---

## N. Legacy functionality

- `dashboard/` vanilla SPA fallback
- Branding: Alpha Finder, Network Alpha, Smart Money, Bandarmology productization of market-wide data
- `analyze_network_alpha.py` + `network_alpha_data.json` as mega-blob
- Multiple `*.bak-*` frontend/python backups in tree (noise; do not ship)
- `data/idx_chunks/*.js` research dumps from IDX site
- Politics/LHKPN split documented in `DATA_OWNERSHIP.md` (bijak-beli)

---

## O. Fake / synthetic-data risk checklist

| Risk | Current status | Action |
|---|---|---|
| Synthetic broker blocks | **Mitigated** in `/api/stock/{ticker}/blocks` | Keep tests; ban regressions |
| Stealth / smart money delta | **Mitigated** (UNAVAILABLE) | Ensure UI never invents anomalies |
| EOD bid/offer as buy dominance | Partially labeled in CPE | Enforce “EOD PRESSURE PROXY” in UI |
| Watchlist seed prices | Fake defaults | Remove; load from API |
| Briefing fallback slice(0,5) | Synthetic-looking | Show explicit degraded mode |
| MockProvider in prod | N/A yet | Forbid via env flag |
| Excel sample trades | Marked dummy in Panduan | Import only if user opts in |

---

## P. Performance risks (2 GB RAM target)

1. Loading full universe JSON into SPA (`network_alpha_data.json`) every visit.  
2. Backtest computed synchronously in API request.  
3. DuckDB / pandas loading large frames per request without cache.  
4. Unbounded chart history if `limit` ignored by clients.  
5. Multiple WebSocket clients triggering heavy reloads.  
6. Neo4j + API + scrapers concurrent on 2 GB.  
7. Research JSON/`idx_chunks` sitting in mounted `/data`.

**Mitigations (design):** precompute screener cache daily; paginate; server-side filter/sort; background jobs; one upstream realtime connection; SQLite for user data; drop unused mounts.

### Estimated RAM risk

| Profile | Feasible? | Notes |
|---|---|---|
| 2 GB — EOD only, few users | **Yes, if disciplined** | Precompute + SQLite + no Neo4j-in-process required |
| 2 GB — realtime tick + multi-user + Neo4j | **Risky** | Prefer 4 GB once realtime + graph always-on |
| 4–8 GB | Comfortable for realtime + more concurrent users | Document when upgrading |

---

## Q. Security risks

| Severity | Issue |
|---|---|
| Critical | No authentication/authorization for private data (watchlist/journal not even server-side yet) |
| Critical | `/api/query/sql` unauthenticated |
| High | CORS `allow_origins=["*"]` + credentials |
| High | `/data` static mount exposes datasets |
| High | SQL string interpolation `where=f"StockCode = '{ticker}'"` (ticker uppercased but still injection-shaped) |
| Medium | Ingestion trigger unauthenticated → resource abuse |
| Medium | Future AI keys must stay server-side only |
| Low | No rate limiting observed |

---

## R. Licensing / data-rights checklist

| Asset | Notes |
|---|---|
| Repo MIT | Attribution required in redistributions |
| IDX website scrape | **Not a licensed commercial feed**; ToS/robots/redistribution unclear — treat as fragile; prefer licensed feed for commercial product |
| IDX Data Service / ITCH | Official paid; redistribution & display licenses required |
| Redistributors (RTI, IQ Plus, etc.) | Commercial; negotiate display rights |
| Third-party APIs (Invezgo etc.) | Verify commercial + redistribution before wiring |
| lightweight-charts | Check TradingView license terms for commercial use |
| lucide-react / vis-network / React | Generally permissive; keep attributions |
| Stockbit | UX reference only — do not clone UI 1:1; fee defaults in Excel cite Stockbit help as fee reference |
| Excel workbook | User’s private trading data structure; sample rows are dummy |

**ASSUMPTION:** Commercial launch requires explicit market-data license decision by owner. Until then product must run on EOD + clearly labeled sources.

---

## S. Proposed target architecture

```
Providers (IDX EOD | Realtime adapter NOT_CONFIGURED | Ownership | Broker if stock-specific)
        ↓
Ingestion Orchestrator (SYNC ALL + schedulers)
        ↓
Normalized Store (Parquet EOD + optional tick rolling window)
        ↓
Feature Engine → Signal Engine → Target Engine → Risk Engine
        ↓
Screener Cache (EOD + optional realtime cache)
        ↓
API Layer (versioned contracts, lineage metadata)
        ↓
SPA ([BRAND_NAME] 7 tabs)
        ↓
Account DB (SQLite/Postgres): users, watchlist, plans, journals

Side abstractions (stubs): AIProvider | NotificationProvider | Entitlement
Realtime fan-out: ONE upstream → cache → many users
```

### Schema versioning

Introduce:

- `DATA_SCHEMA_VERSION` on derived artifacts  
- API response envelope: `{ schema_version, as_of, quality, source, data }`  
- Frontend must tolerate missing fields (no `undefined.length` crashes)

### Rebranding order (no blind file renames)

1. UI strings / Header / titles / footer  
2. Nav labels  
3. Docs  
4. API tags / public names  
5. Safe component renames (`AlphaHub` → later)

Placeholder brand: **`[BRAND_NAME]`**.

---

## Alpha branding inventory (UI-first)

| Location | Current | Target direction |
|---|---|---|
| `Header.tsx` | IDX Smart Money / Alpha Terminal / Alpha Finder | `[BRAND_NAME]` / Market Intelligence |
| `App.tsx` titles & footer | Alpha Finder / Network Alpha | brand-neutral |
| `AlphaHub.tsx` | Alpha Finder & Opportunity Hub | Screener hub |
| `BacktesterTab.tsx` | Strategy Alpha Engine | Strategy Lab |
| `signals` / tests | AlphaScore, composite_alpha | Engine Score / Signal Ranking (API rename carefully) |
| `network_alpha_data.json` | filename | keep until migration; alias |

Quant term “alpha” (excess return vs benchmark) may remain in Strategy Lab metrics as **benchmark excess return**, not product brand.

---

## Realtime provider research (summary)

| Provider class | Coverage | Tick | Depth | Broker | Commercial | Verdict |
|---|---|---|---|---|---|---|
| IDX official Data Service / ITCH | Official | Yes | Yes (products) | Yes (ITCH) | Paid + license | Best correctness; not free |
| IDX authorized redistributors | Official path | Yes | Varies | Varies | Paid | Preferred for production website |
| ICE Consolidated Feed | IDX L1/L2 | Yes | Yes | ? | Enterprise | Expensive/enterprise |
| Developer APIs (e.g. Invezgo-class) | Claims IDX RT + broker | Claims | Claims | Claims | Must verify ToS | Evaluate later with contract; **do not integrate blindly** |
| Free scrape of IDX site | Partial EOD | No | No | No | Redistribution dubious | Current path; label EOD |

**Decision for now:** implement `MarketDataProvider` + status **`REALTIME: NOT CONFIGURED`**. Keep EOD screener operational. No fake realtime.

---

## Implementation order (locked to product phases)

1. Repo audit ← **this document**  
2. Architecture cleanup (providers, honesty labels, remove/guard dangerous surfaces)  
3. Schema / data contracts  
4. Rebrand UI  
5. Backend/API cleanup  
6. TAB 1 Screener  
7. TAB 2 Stock Terminal  
8. TAB 3 Big Money  
9. TAB 4 Strategy Lab  
10. TAB 5 Data Center  
11. TAB 6 Watchlist (auth)  
12. TAB 7 Trading Plan & Journal (Excel mapping)  
13–15. AI / Telegram / Payment abstractions  
16. Realtime provider (when chosen)  
17–19. Performance / Security / Deployment  

---

## Assumptions / Limitations / Gaps

| Type | Statement |
|---|---|
| ASSUMPTION | Owner will pick final brand string to replace `[BRAND_NAME]` |
| ASSUMPTION | Initial deploy is single-node ~2 GB RAM, EOD-first |
| ASSUMPTION | Stockbit is UX inspiration only |
| LIMITATION | No licensed realtime feed configured |
| LIMITATION | No stock-specific broker transaction pairs in current warehouse |
| LIMITATION | Neo4j optional; Power Map/UBO degrade without it |
| DATA UNAVAILABLE | Tick tape, historical depth, person-level fast-in/out from broker inference |
| PROVIDER LIMITATION | IDX public endpoints are snapshot/EOD-oriented and unstable for production SLA |

---

## Next issue (after audit acceptance)

**PHASE 2 kickoff (still no big rewrite):**

1. Freeze honesty contracts (quality enums, unavailable responses).  
2. Draft `DATA_SCHEMA_VERSION` + API envelope.  
3. Scaffold provider interfaces (MarketData / AI / Notification / Entitlement) as stubs.  
4. UI rebrand pass on Header/App titles only.  
5. Begin TAB 7 schema from Excel mapping doc (DB design only).

**Do not** rewrite AlphaHub/ChartTab wholesale until Screener contract is approved.
