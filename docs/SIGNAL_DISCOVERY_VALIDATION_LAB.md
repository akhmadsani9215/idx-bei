# Signal Discovery & Validation Lab

Last updated: 2026-09-23  
Status: **Clusters 1–8 complete** (engine `signal-discovery-4.0`). Controlled study: **0 survivors** — see `docs/SIGNAL_DISCOVERY_STUDY.md`.  
**Not** a profitability claim. **No** production BUY. V3.x offline labs remain research artifacts.

Canonical package: `idx.signal_discovery` (`contract`, `hypotheses`, `registry`, `runner`, `validation`, `metrics_adapter`, `costs`, `survivorship`, `robustness`)  
Execution engine (unchanged): `idx.backtest.run_backtest`  
Screener production (unchanged): `idx.screener`  
Strategy Lab honesty flags: `idx.strategy_lab`

---

## 1. Existing capability audit

| Capability | Status | Evidence |
|---|---|---|
| Generate signals / screens | **YES (partial)** | `idx.signals` (7 screens); `idx.screener` CP/Swing/Long-Term; dividend BUY/HOLD/SELL |
| Define entry | **YES** | Backtest: same-session Close on `entry_date`; screener: structure-derived `entry_zone` |
| Dynamic TP/CL | **YES (screener)** | `idx.screener.structure.select_dynamic_levels`; RR ≥ 1:2 gate |
| Fixed SL/TP in backtest | **PARTIAL** | Optional `stop_loss_pct` / `take_profit_pct` on Close (not structure TP/CL) |
| MFE / MAE | **YES (screener hist)** | `idx.screener.historical._forward_mfe_mae` — descriptive, sample-gated (≥30) |
| MFE / MAE in `run_backtest` | **NO** | Strategy Lab marks `mfe`/`mae` UNAVAILABLE |
| Holding period | **YES** | `holding_days` session steps in `run_backtest` |
| Expectancy | **PARTIAL** | Computed in offline `python/backtest_v3*.py`; not in production `run_backtest` metrics; Lab exposes key but usually missing |
| IS / validation / OOS split | **NO (prod)** | Strategy Lab always `INSUFFICIENT OOS VALIDATION`; V3.3 has TRAIN/TEST offline only |
| Walk-forward | **NO** | Explicitly flagged UNKNOWN/absent in `strategy_lab.validation_flags` |
| Transaction cost / slippage | **NO (engine)** | Documented in `backtest.py` header; trading_plan has fee defaults for plans only |
| Regime analysis | **PARTIAL** | PIT trend regime in `signals`; ingestion mentions cross-regime recommendations; no harness |
| Robustness / sensitivity | **NO (prod)** | Offline `backtest_v3_5` robustness lab JSON only |
| Leakage / PIT guards | **YES (reuse)** | `_pit_market_slice`, `_latest_per_code(as_of=)`, screener historical excludes live bar; tests in `test_backtest_pit`, `test_gap_closure`, `test_screener_engine`, `test_signals` |
| Survivorship handling | **NO** | Lab flag: listed universe only, no delisting reconstruction |
| Multiple-testing control | **NO** | No trial registry / FDR / deflated Sharpe in production path |

**Do not treat V3.x JSON outputs as proof of profitability** (`strategy_lab` + DECISION_LOG).

---

## 2. Missing capability

- Formal **candidate** object with lineage + lifecycle status
- Horizon-separated discovery (not one TP/CL/holding for all)
- Staged hypothesis search (interpretable → params → interactions → robustness → OOS → gate)
- Production OOS / walk-forward harness on `run_backtest`
- Cost + slippage models inside the backtest engine
- Survivorship-aware universe
- Multiple-testing / overfit registry
- Expectancy + MFE/MAE wired into production backtest metrics
- Screener CP/Swing wired as `run_backtest` strategy ids (currently UNAVAILABLE in Strategy Lab)
- Intraday discovery (no tape → permanently blocked until realtime)

---

## 3. Horizon taxonomy

Discovery horizons (`idx.signal_discovery.contract.HORIZONS`):

| Horizon | Holding guidance (sessions) | Screener map |
|---|---|---|
| `INTRADAY` | N/A (needs tape) | none — UNAVAILABLE |
| `NEXT_DAY_1_3D` | 1–3 | `close_pressure` |
| `SWING_3_10D` | 3–10 | `swing` |
| `SWING_2_4W` | 10–20 | `swing` (same engine, different holding/TP-CL contract) |
| `POSITION_1_3M` | 20–63 | none yet |
| `LONG_TERM_3_12M` | 63–252 | `long_term` (CANDIDATE labels only) |
| `MULTIBAGGER_1_5Y` | 252–1260 | `long_term` (CANDIDATE only) |

**Decision:** Do not duplicate screener TIMEFRAMES. Map explicitly via `SCREENER_TIMEFRAME_TO_HORIZON` / `HORIZON_TO_SCREENER_TIMEFRAME`. Each horizon must own its own TP/CL/holding rules — never reuse CP +3% opportunity filter as a universal TP.

---

## 4. Candidate contract

Module: `idx.signal_discovery.contract`

Required lineage fields: `strategy_id`, `strategy_version`, `horizon`, `universe_definition`, `feature_set`, `entry_rule`, `exit_rule`, `tp_methodology`, `cl_methodology`, `minimum_rr`, `holding_period_limit`, `signal_timestamp`, `data_as_of`, `data_quality`, `source`, `engine_version`, `discovery_method`, `hypothesis`, `parameter_set`, `cost_model`, `slippage_model`, `status`.

Statuses: `DISCOVERED` → `BACKTESTING` → `VALIDATION` → `OOS_TESTING` → `WALK_FORWARD` → `ROBUSTNESS` → `CANDIDATE` → `PRODUCTION_CANDIDATE`, plus terminals `REJECTED` / `INCONCLUSIVE` / `INSUFFICIENT_DATA`.

BUY rules:
- BUY only when `entry_rule` evaluates to BUY — never from high score alone
- `INSUFFICIENT_DATA` / `INCONCLUSIVE` / `REJECTED` must not coerce to BUY
- Traceability: signal → timestamp → features → entry → TP/CL → outcome

Multiple-testing metadata: `empty_multiple_testing_record()` — significance claimed only if computed.

---

## 5. Discovery pipeline (staged)

1. **STAGE_1_HYPOTHESIS** — small interpretable set from `FEATURE_FAMILIES`
2. **STAGE_2_PARAMETER_VARIATION** — bounded grids per horizon
3. **STAGE_3_FEATURE_INTERACTION** — limited pairwise only after Stage 1–2 survivors
4. **STAGE_4_ROBUSTNESS_REGIME** — regime / sensitivity
5. **STAGE_5_OOS_WALK_FORWARD** — locked parameters; no retuning
6. **STAGE_6_PRODUCTION_CANDIDATE_GATE** — OOS required; no bypass

Cluster 1 does **not** run search. Cluster 2 implements Stage-1 runner + trial registry against existing engines (no production BUY).

---

## 12. Cluster 2 — Discovery runner & trial registry

### Runner architecture
- Entry: `idx.signal_discovery.runner.run_stage1_discovery(DiscoveryConfig)`
- Catalog: `idx.signal_discovery.hypotheses.STAGE1_HYPOTHESES` (7 curated families)
- Registry: `idx.signal_discovery.registry.TrialRegistry`
- Evaluation: existing `run_backtest` only when `engine_strategy` is set and horizon is executable
- Unwired families / non-executable horizons → `INSUFFICIENT_DATA` (no silent fallback)
- `max_trials` (default 7): stop cleanly; register explicit `TRIAL_LIMIT_REACHED` (never silent truncate)
- Forbidden runner statuses: `PRODUCTION_CANDIDATE`, `PRODUCTION`, `BEST`, `WINNER`, `PROVEN`, `PROFITABLE`
- Inspection sort label: **candidate for further validation** only

### Stage-1 hypothesis families

| Family | strategy_id | engine | Cluster 2 outcome |
|---|---|---|---|
| TREND | `s1_trend_composite` | `composite_alpha` | Evaluable |
| MOMENTUM | `s1_momentum_standalone` | none | INSUFFICIENT_DATA |
| BREAKOUT | `s1_breakout_structure` | none | INSUFFICIENT_DATA |
| PULLBACK | `s1_pullback_trend` | none | INSUFFICIENT_DATA |
| MEAN_REVERSION | `s1_mean_reversion` | none | INSUFFICIENT_DATA |
| VOLUME_EXPANSION | `s1_volume_expansion` | none | INSUFFICIENT_DATA |
| RELATIVE_STRENGTH | `s1_relative_strength_foreign` | `foreign_flow` | Evaluable |

### Horizon execution (no silent remap)

| Horizon | Executable | holding_days |
|---|---|---|
| INTRADAY | No | — |
| NEXT_DAY_1_3D | Yes | 2 |
| SWING_3_10D | Yes | 7 |
| SWING_2_4W | Yes | 15 |
| POSITION_1_3M | Yes | 42 |
| LONG_TERM_3_12M | No | — |
| MULTIBAGGER_1_5Y | No | — |

### Trial registry schema (required)
`trial_id`, `strategy_id`, `strategy_version`, `horizon`, `hypothesis`, `feature_set`, `parameters`, `universe_definition`, `discovery_period`, `validation_period`, `oos_period`, `cost_model`, `slippage_model`, `engine_version`, `data_version`, `data_quality`, `created_at`, `status`, `metrics`, `failure_reason`  
Plus honesty: `survivorship_status=NOT_VALIDATED`, `cost_model=NOT_CONFIGURED`, `slippage_model=NOT_CONFIGURED`, `return_is_net_tradable=False`, `profitable_claim=False`.

Metrics missing from engine → `null` / `NOT_AVAILABLE` (never fake tradable 0 when sample=0).

### Why this is NOT profitability proof
- Stage-1 is curated enumeration, not validated edge discovery
- Cluster 2 had no OOS / walk-forward gate; Cluster 3 adds harness but still no production BUY
- Gross unadjusted Close ≠ net tradable return
- Survivorship not reconstructed
- Multiple hypotheses recorded without significance claims
- Inspection ranking is for humans, not production winners
- `VALIDATED_FOR_RESEARCH` ≠ PRODUCTION / PRODUCTION_BUY

---

## 13. Cluster 3 — OOS + walk-forward validation harness

### Temporal split contract
- Modules: `idx.signal_discovery.validation`, `metrics_adapter`
- Entry: `run_validation(ValidationConfig)`
- Windows: `discovery` (IS) → `validation` → `oos` — explicit dates, **no current-date defaults**
- Overlap or non-chronological order → `REJECTED` (`ValidationConfigError`)
- **No random shuffle** (`shuffle_used=False`)
- Data coverage: if requested range outside `data_available_*` → `INSUFFICIENT_DATA` with `actual_used_range=null` (**no silent shrink**)

### Parameter selection
- Allowed from `IS` / `TRAIN` / `VALIDATION` only
- `parameter_selection_phase=OOS` → rejected
- OOS/walk-forward test folds use **locked** parameters; retune after OOS requires new trial/version

### Walk-forward
- Expanding window via `WalkForwardConfig` (`build_walk_forward_folds`)
- Per fold: `fold_id`, train/test ranges, `parameter_version`, metrics, sample, status
- Aggregate keeps dispersion: fold counts, median/mean return, MFE/MAE medians when present, success/failure counts + full `folds[]`

### Metrics adapter
- `adapt_backtest_metrics` — reuses registry normalizer; MFE/MAE/TP/CL hit → `NOT_AVAILABLE` unless engine supplies
- Optional expectancy from trade ledger mean return
- Missing / zero-trade → null (not fake tradable 0); `return_is_net_tradable=False`

### Sample gate
- Default `min_sample` = screener `MIN_HISTORICAL_SAMPLE` (30) — **engineering gate**, documented, configurable
- Below threshold → `INSUFFICIENT_DATA` (high return with tiny n does not pass)

### Eligibility
- Gates: `IS_SUCCESS` / `VALIDATION_SUCCESS` / `OOS_SUCCESS` / optional `WALK_FORWARD_SUCCESS`
- Max Cluster 3 status: **`VALIDATED_FOR_RESEARCH`**
- Forbidden: `PRODUCTION`, `PRODUCTION_BUY`, `PRODUCTION_CANDIDATE`, BEST/WINNER/PROVEN/PROFITABLE
- Honesty: `cost_model=NOT_CONFIGURED`, `slippage_model=NOT_CONFIGURED`, `survivorship_status=NOT_VALIDATED`

### References (no new deps)
- Walk-forward / purged CV concepts; Deflated Sharpe / multiple testing — design references only

## 14. Cluster 4 — Cost/slippage, survivorship policy, robustness contracts

### Cluster 3 verification (before Cluster 4 changes)
- `run_backtest` filters `Date <= end_date` before the rebalance loop, so exits never cross a window boundary → no IS→VALIDATION→OOS label bleed. Feature warm-up is truncated at `start_date` (no leakage, but early-window signals see less history).
- Fixed in Cluster 4:
  - Walk-forward gate passed with **one** successful fold (`PARTIAL`) → now requires **every** fold `OK`.
  - Overlapping WF folds (`step < test_span`) raised an uncaught exception → now `REJECTED` (run-level `REJECTED`).
  - Expectancy used a percent/fraction magnitude heuristic (wrong for |trade| > 150%) → explicit ledger units (`Return` fraction, `ReturnPct` percent).
  - `VALIDATED_FOR_RESEARCH` meant data sufficiency only but did not say so → `eligibility_basis` now states: **no performance threshold applied**.
  - Runner: executable horizon with `holding_days=None` would crash on `int(None)` → `INSUFFICIENT_DATA`.

### Cost / slippage (`costs.py`)
- `CostModel` (buy/sell bps; sell includes any sell tax) and `SlippageModel` (per-side bps). Statuses: `NOT_CONFIGURED` | `RESEARCH_ILLUSTRATIVE` | `CONFIGURED`.
- **No IDX fee schedule and no slippage values ship in code.** `CONFIGURED` requires `source` + `as_of`; illustrative models are caller-chosen and labelled RESEARCH/ILLUSTRATIVE.
- Net = exact multiplicative: `(1+gross)·(1−sell)/(1+buy) − 1`, per trade from the engine ledger.
- `return_semantics`: `net_return_status` = `NOT_AVAILABLE` (any model not configured) | `RESEARCH_ILLUSTRATIVE` | `AVAILABLE`; `return_is_net_tradable=true` only when both are `CONFIGURED`. `execution_feasibility` = NOT_MODELED (lots, ARA/ARB, liquidity, fill probability).
- `ValidationConfig.cost_model/slippage_model` default `NOT_CONFIGURED`; each phase result carries `net_returns` (gross vs net expectancy / win rate).

### Survivorship (`survivorship.py`)
- Components: point-in-time universe, delisted, suspended, historical index constituents, ticker changes, corporate-action price adjustment.
- Evidence: `VERIFIED` (requires `verified_by` + `source`) | `OBSERVED_UNVERIFIED` | `NOT_AVAILABLE`.
- Rule: `SURVIVORSHIP_SAFE` = all VERIFIED; `SURVIVORSHIP_PARTIAL` = PIT universe VERIFIED + ≥1 other; else `NOT_VALIDATED`. Observation never upgrades status.
- Audit on local Parquet (2026-09-23): 2025-01-02 → 2026-09-22, 980 tickers; 17 last seen before end (e.g. FREN, MASA — cause unconfirmed), 33 first seen after start; 61 share-count/price-basis events in range (23 rights, 14 capital reductions, 10 splits, 7 bonus, 4 mergers, 3 stock dividends); **0 full delisting records** (`partialDelisting` ≠ delisting); no suspension registry, ticker-change map or historical constituents. **Result: `NOT_VALIDATED`.** Unadjusted Close means trades spanning those events can carry artificial returns.

### Robustness (`robustness.py`)
- `RobustnessConfig(base, evaluation_phase ∈ {IS, VALIDATION}, max_variants, parameter_neighbors, universe_neighbors, holding_days_neighbors, time_subwindows, cost_scenarios)`. OOS is rejected.
- One-at-a-time neighbours around the locked base; no grid, no selection; **every variant retained**. Budget exceeded → `TRIAL_LIMIT_REACHED`, nothing executed.
- Guards: neighbours exclude base and duplicates; real engine only varies consumed keys (`top_n`; universe `min_turnover_rp`); holding neighbours must stay inside `HORIZON_HOLDING_BOUNDS`; time sub-windows ordered, non-overlapping, inside the phase window.
- Per-dimension criteria (`ROBUSTNESS_CRITERIA`): ≥2 evaluable neighbours else `INSUFFICIENT_DATA`; base ≤ 0 → `INCONCLUSIVE`; any neighbour sign flip or median degradation > 50% → `FRAGILE`; any neighbour unevaluable → `INCONCLUSIVE`; else `ROBUST`.
- Overall: any FRAGILE → `FRAGILE`; `ROBUST` needs ≥2 engine dimensions all ROBUST; else `INCONCLUSIVE`/`INSUFFICIENT_DATA`.
- Metric: gross expectancy (net only when both models `CONFIGURED`). Cost sensitivity reports net per scenario but **never** contributes to `ROBUST`.

## 15. Clusters 5–8 — engine outcomes, controlled study, overfit control

- **Engine (`run_backtest`)**: ledger adds `MFEPct`/`MAEPct` (post-entry High/Low, else Close), `HoldingSessions`, `ExitReason` (TIME / TIME_LAST_AVAILABLE / STOP_LOSS / TAKE_PROFIT); metrics add `expectancy_pct`, `median_mfe_pct`, `median_mae_pct`, `tp_hit_rate_pct`/`cl_hit_rate_pct` (null unless the rule is configured), `median_holding_sessions`, `data_gap_segments`, `data_gap_rebalances_skipped`.
- **Data gaps**: sessions > 14 calendar days apart split history into segments. Local `stock_summary` after the 2026-09-24 backfill: 882 sessions, 2023-01-02→2026-09-22, **no such gap**. Features/history never cross a gap; rebalances whose exit would cross are skipped.
- **Price basis**: default `EXCHANGE_REFERENCE_ADJUSTED` (causal). Trades whose hold spans a price-distorting CA are excluded (`ca_event_trades_excluded`).
- **Warm-up**: bars before `start_date` feed features (PIT); trades stay inside the window.
- **Technical rules** (`backtest.TECHNICAL_RULES`): momentum, breakout, pullback, mean_reversion, volume_expansion — one fixed rule each; trailing features computed once per dataset (content-hash cache), identical to per-slice recomputation.
- **Study** (`study.py`, `uv run idx discovery-study`): pre-registered protocol + verdict rules; baseline = liquid-universe forward return; illustrative stress cost; IS robustness; DSR over all evaluations; BH-FDR on OOS.
- **Multiple testing** (`multiple_testing.py`): PSR, expected max Sharpe, DSR (threshold 0.95, ≥20 periods), BH step-up.

### Multiple-testing preparation (`registry.py`)
- `record_robustness_run`; summary adds `total_trials`, `trials_by_family`, `trials_by_horizon`, `parameter_variants`, `robustness_runs`, `robustness_variants_total`, `evaluations_upper_bound` (correlated, not independent).
- `adjustment_status=NOT_APPLIED`, `deflated_sharpe=null` (`NOT_IMPLEMENTED`), `false_discovery_control=NOT_IMPLEMENTED`, `statistical_significance_claimed=false`.

---

## 6. Anti-leakage rules (P0)

**Reuse** existing PIT guards — do not duplicate:
- `idx.backtest._pit_market_slice`
- `idx.signals._latest_per_code(..., as_of=)` (undated filings excluded)
- Screener historical: outcomes after signal bar; `exclude_last=True`
- Structure levels from past bars only for live qualification

Contract adds:
- `assert_signal_as_of_ordering` — `data_as_of <= signal_timestamp`
- `assert_no_future_feature` — feature as_of ≤ signal timestamp

Audit checklist (must remain true):
- No future OHLCV / reports / revised filings / corp actions / ownership / foreign flow
- No current-bar outcome contamination for live signals
- No lookahead via normalization / cross-sectional ranking / universe selection
- No target leakage / train–test contamination
- Survivorship **NOT_VALIDATED** (policy + audit in §14; no delisting/suspension/ticker-change data)

---

## 7. Multiple-testing / overfit controls

Record per discovery run: hypotheses tested, candidate/parameter counts, selection rule, discovery/validation/OOS periods, seed, trial count, best IS vs selected vs OOS results.

Do **not** claim statistical significance until a real test is computed and stored. Positive IS alone is insufficient for `PRODUCTION_CANDIDATE`.

---

## 8. Validation gates

| Gate | Requirement |
|---|---|
| Lineage complete | All `REQUIRED_LINEAGE_FIELDS` present |
| Horizon valid | In `HORIZONS`; TP/CL/holding match horizon |
| PIT | Ordering + no future features |
| Sample | Prefer ≥30 trades (align screener `MIN_HISTORICAL_SAMPLE`); else `INSUFFICIENT_DATA` |
| OOS | Required before `PRODUCTION_CANDIDATE` |
| Honesty | `profitable_claim_allowed=False` until Product Owner + OOS evidence |

---

## 9. Production eligibility rules

Separate:
1. **SIGNAL DISCOVERY** — hypothesis generation  
2. **SIGNAL VALIDATION** — IS / OOS / walk-forward / robustness  
3. **PRODUCTION ELIGIBILITY** — only `PRODUCTION_CANDIDATE` after OOS  

Forbidden:
- Wire new BUY into production screener from discovery without gate
- Promote `REJECTED` → `PRODUCTION_CANDIDATE` without revalidation restart
- Bypass OOS via UI score or V3.x artifact

---

## 10. Known data limitations

- No fees/slippage/position sizing in `run_backtest`; discovery cost models are NOT_CONFIGURED by default (no real IDX fee / slippage source)
- Raw Close (not CA-adjusted) — 61 price-basis events in the current data range
- No delisting / survivorship reconstruction (`NOT_VALIDATED`)
- MFE/MAE from realised paths; TP/CL hit only with configured fixed-% SL/TP (engine has no structural TP/CL yet)
- Close Pressure EOD = data quality **E**; no trade-side dominance from Bid/Offer
- Long-term = CANDIDATE label only; expectancy not validated
- Intraday / Big Money actor follow = UNAVAILABLE without tape / actor transactions
- `cagr_pct` / alpha without benchmark remain null (backtest contract)
- Offline `backtest_v3*` ≠ production proof

---

## 11. Planned implementation clusters

| Cluster | Focus |
|---|---|
| **1** | Audit, contract, horizon map, anti-leakage invariants, docs, focused tests |
| **2 (done)** | Discovery runner skeleton + Stage-1 catalog + trial registry (no production BUY) |
| **3 (done)** | OOS / walk-forward harness + metrics adapter; `VALIDATED_FOR_RESEARCH` only |
| **4 (done)** | Cost/slippage contracts + survivorship policy/audit + robustness sensitivity + multiple-testing bookkeeping |
| **5 (done)** | Engine per-trade MFE/MAE, TP/CL first-exit reason, holding sessions, expectancy; data-gap segmentation; warm-up before window |
| **6–7 (done)** | 7 families wired (5 new technical rules) + pre-registered multi-horizon study → `docs/SIGNAL_DISCOVERY_STUDY.md` (0 survivors) |
| **8 (done)** | `multiple_testing.py`: PSR, Deflated Sharpe, BH-FDR |
| **5** | Stage 1–2 small hypothesis packs per horizon; robustness gates |
| **6** | Production candidate promotion UI/API (flags only) — still no silent BUY injection |

---

## Third-party research / dependency candidates (not added)

| Item | Use | Action |
|---|---|---|
| Bailey & López de Prado — Deflated Sharpe / multiple testing | Overfit control design | Reference only until Cluster 3+ |
| `vectorbt` / `backtesting.py` | Optional vectorized research | **Do not add** until justified vs extending `run_backtest` |
| Academic momentum/value/quality papers | Hypothesis sources | Must re-validate on IDX; no transfer of claimed edges |

No new dependencies in Cluster 1.
