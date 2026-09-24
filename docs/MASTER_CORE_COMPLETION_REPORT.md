# MASTER CORE COMPLETION REPORT — RitelInsight

Date: 2026-09-23 · Baseline commit `939207c` (all work below is uncommitted; no push).

**Verdict: CORE ENGINEERING COMPLETE for what the repository can resolve.** Remaining gaps are
external decisions (provider / legal / IdP / hosting) or data that does not exist yet. No
research result was converted into a production BUY; no profitability is claimed.

Status legend: GREEN · PARTIAL · NOT_CONFIGURED · NOT_VALIDATED · UNAVAILABLE · BROKEN.

## Evidence

| Check | Result |
|---|---|
| Full backend suite | **442 passed** (429 suite + 13 core API smoke), coverage gate OK |
| Ruff lint + format | clean (repo-wide; first time) |
| Mypy `python/src/idx` | clean (65 files) |
| Frontend build (`npm run build`) | OK — 1.09 MB bundle warning (UI phase) |
| Controlled discovery study | 28 trials, 392 engine runs, **0 survivors** on 2026-09-23 and 2026-09-24 re-run (`docs/SIGNAL_DISCOVERY_STUDY.md`) |
| SBOM | 35 components, 2 MPL review items (`docs/SBOM.cdx.json`) |

## Definition-of-finish matrix

| Criterion | Status | Notes |
|---|---|---|
| Data/schema contract stable | GREEN | `DATA_SCHEMA_VERSION` 1.0.0; strict JSON smoke on core routes; additive fields only |
| Data completeness | **PARTIAL** | stock_summary 882 sessions 2023-01-02→2026-09-22, 0 gaps >14d; broker/index still incomplete; engine still segments if a gap returns |
| Screener causal & honest | GREEN | causal structure (shift/pivot confirmation); rows carry `production_eligibility=NOT_VALIDATED` |
| Dynamic TP/CL/RR ≥ 1:2 | GREEN | structure-derived levels; NOT_QUALIFIED otherwise (unchanged, audited) |
| Historical metrics causal | GREEN | fixed: truncated windows excluded, gap-crossing excluded, TP vs CL first-touch (CL wins ties), CL probability added |
| OOS | GREEN | temporal IS/VAL/OOS harness; Strategy Lab `/api/strategy/validate` |
| Walk-forward | GREEN | expanding folds; gate needs **every** fold OK; overlapping folds REJECTED |
| Cost/slippage semantics | GREEN (contract) / NOT_CONFIGURED (values) | gross vs net contract; no real fee/slippage source |
| Survivorship status explicit | NOT_VALIDATED | rule-based policy + audit; no delisting/suspension/ticker-change data |
| Robustness | GREEN | one-at-a-time neighbours, IS/VAL only, all variants kept, explicit criteria |
| Multiple-testing controls | GREEN | PSR, Deflated Sharpe, BH-FDR, evaluation bookkeeping |
| Multi-horizon discovery | PARTIAL | NEXT_DAY / SWING_3_10D / most SWING_2_4W evaluable after gap fill; POSITION_1_3M still INSUFFICIENT_DATA; INTRADAY / LONG_TERM / MULTIBAGGER UNAVAILABLE |
| Tradable edge | NOT_VALIDATED | 0 survivors; closest (Swing momentum) FRAGILE |
| Strategy Lab integrated | GREEN | catalog synced to engine, research verdicts per horizon, validation endpoint |
| Big Money honest | GREEN (audit) | Fast-In/Out, actor, stock-specific broker = UNAVAILABLE; nulls not zeros |
| Data Center reliable | GREEN | serialized jobs (409), task refs retained, dead-task detection, persisted bounded history, ops view |
| Watchlist/Journal contracts | GREEN | session-scoped (unchanged; covered by existing tests) |
| Security baseline | PARTIAL | operator token (fail-closed in prod), rate limit, security headers, sanitized errors, no default Neo4j password; IdP / TLS / CSP external |
| Full regression | GREEN | see evidence |
| SoT matches code | GREEN | PROJECT_STATE / ARCHITECTURE / HANDOFF / DECISION_LOG updated |

## Product areas

| Area | Status |
|---|---|
| Screener | GREEN (decision support; NOT_VALIDATED for production eligibility) |
| Stock Terminal | GREEN (EOD); tape/orderbook UNAVAILABLE |
| Big Money | PARTIAL (by data: disclosure / aggregate / market-wide only) |
| Strategy Lab | GREEN |
| Signal Discovery Lab | GREEN (harness) · NOT_VALIDATED (edge) |
| Data Center | GREEN |
| Watchlist · Trading Plan/Journal | GREEN (session) |
| Realtime | NOT_CONFIGURED |
| AI · Telegram · Payment | NOT_CONFIGURED |
| Auth / IdP | PARTIAL (local sessions; IdP NOT_CONFIGURED) |
| Deployment / TLS | NOT_CONFIGURED (external) |
| Commercial / data rights | BLOCKED_EXTERNAL (`docs/COMMERCIAL_READINESS.md`) |

## Correctness bugs found and fixed this session
1. Walk-forward research gate passed on one good fold.
2. Overlapping WF folds raised an uncaught exception.
3. Expectancy unit heuristic (wrong for trades > 150%).
4. `VALIDATED_FOR_RESEARCH` did not state it is data-sufficiency only.
5. Runner `int(None)` crash path.
6. **Engine trades and features spanned the 5.5-month data gap** (a "2-session" hold could last 6 months).
7. Features started cold at every window start (no warm-up).
8. Screener historical stats: truncated horizons counted, gap-crossing windows counted, TP hit ignored an earlier stop.
9. `composite_alpha_ranking` crashed without `opini`; recomputed full-history technicals per rebalance (~16 s each).
10. `pandas`/`numpy` not declared as runtime dependencies.
11. Unauthenticated `/api/broadcast` and `/api/system/trigger-ingestion`; concurrent ingestion jobs; GC-able background tasks.
12. Default Neo4j credential `password` in code and compose.

## Blocked / external (documented, not worked around)
Realtime vendor · KSEI source · production IdP · TLS/hosting · payment · Telegram · AI provider ·
IDX data redistribution rights · NOTICE text · broker fee/tax schedule + slippage data ·
delisting/suspension/ticker-change data.

## Recommended next (after Product Owner review)
1. **UI & Product Finalization** (gap backfill + CA controls + study re-run are done; 0 survivors).
2. Real cost/slippage source and survivorship-safe universe when those data exist — not another parameter search on Stage-1 families.
