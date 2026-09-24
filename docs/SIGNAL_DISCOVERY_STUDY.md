# Controlled Signal Discovery Study — 2026-09-24 re-run

Status: **COMPLETE — 0 candidates survive.** Research evidence only; no verdict is wired
into the screener or any BUY path. Raw report: `data/research/discovery_study_2026-09-24.json`
(regenerate with `uv run idx discovery-study`). Engine `signal-discovery-4.0`,
study `controlled-study-1.0`, strategy catalog `stage1-0.2.0`.

This is the same pre-registered protocol as 2026-09-23, re-run after (a) backfilling
the 2025-03→2025-09 stock hole, (b) exchange-reference price adjustment, and
(c) exclusion of trades whose hold spans a price-distorting corporate action.
Prior report: `data/research/discovery_study_2026-09-23.json`.

## Protocol (unchanged windows — `study.default_plan_for_local_data`)

| Item | Value |
|---|---|
| Data | `stock_summary` 2023-01-02 → 2026-09-22, **882 sessions**, 982 tickers, EOD OHLCV (quality C) |
| Price basis | `EXCHANGE_REFERENCE_ADJUSTED` (causal forward-adjust from IDX `Previous`) |
| CA events | trades spanning a price-distorting CA (table + sparse reference-price events) are **excluded** |
| Data gaps | **none** > 14 calendar days on stock_summary (was 168 days, 2025-03-17→2025-09-01) |
| IS / VALIDATION / OOS | 2025-01-02→2025-10-31 / 2025-11-01→2026-03-31 / 2026-04-01→2026-09-22 |
| Walk-forward | expanding, first train end 2025-10-31, 5 folds × 60-day tests, locked parameters |
| Families (1 rule each, no tuning) | TREND (composite_alpha), MOMENTUM, BREAKOUT, PULLBACK, MEAN_REVERSION, VOLUME_EXPANSION, RELATIVE_STRENGTH (foreign_flow) |
| Parameters | top_n=10, min 20-session avg Value ≥ Rp1bn |
| Horizons | NEXT_DAY h=2, SWING_3_10D h=7, SWING_2_4W h=15, POSITION_1_3M h=42; INTRADAY / LONG_TERM / MULTIBAGGER **UNAVAILABLE** |
| Execution | signal + fill at entry-session Close (close-to-close; needs closing-auction execution) |
| Cost stress | RESEARCH/ILLUSTRATIVE 15 bps buy / 25 bps sell + 10 bps slippage per side (≈0.60% round trip) — not an IDX fee schedule |
| Robustness | IS only; top_n {5,15}; min turnover {0.5bn, 2bn}; holding ±max(1, h//4) |
| Baseline | mean forward return of all liquid tickers at the same rebalance dates |
| Multiple testing | DSR vs 224 evaluations (28 trials + 196 robustness variants), threshold 0.95; BH-FDR α=0.10 on OOS period returns |
| Sample gate | 30 trades per phase / fold (engineering gate) |

Verdict rules are in `study.VERDICT_RULES`; SURVIVES requires every check (all phases and
folds sample-sufficient, positive and above-baseline expectancy in IS/VAL/OOS, positive OOS
net after stress cost, ROBUST, DSR PASS, BH discovery).

## Result

Verdicts: **SURVIVES 0 · FAILED 16 · FRAGILE 2 · INSUFFICIENT_DATA 10 · UNAVAILABLE 21** (392 engine runs).
Vs 2026-09-23: FAILED 14→16, FRAGILE 1→2, INSUFFICIENT_DATA 13→10. Gap fill made three
SWING_2_4W families evaluable; they **FAILED** OOS. BH-FDR: 0 discoveries. DSR: FAIL or
INSUFFICIENT_DATA for every trial.

Gross expectancy per trade (%), IS / VALIDATION / OOS; OOS liquid baseline in brackets.

| Horizon | Family | Verdict | n IS/VAL/OOS | Expectancy IS/VAL/OOS | OOS net (stress) | Robustness |
|---|---|---|---|---|---|---|
| Next day | TREND | FAILED | 968/470/570 | 0.03 / 0.49 / −0.13 [−0.11] | −0.73 | FRAGILE |
| Next day | MOMENTUM | FAILED | 969/470/568 | 1.19 / 1.71 / −0.34 | −0.93 | ROBUST |
| Next day | BREAKOUT | FAILED | 732/370/381 | 0.26 / 0.99 / −0.79 | −1.38 | ROBUST |
| Next day | PULLBACK | INSUFFICIENT_DATA | 4/6/0 | — | — | — |
| Next day | MEAN_REVERSION | FAILED | 603/334/310 | 0.05 / −0.50 / −1.26 | −1.85 | FRAGILE |
| Next day | VOLUME_EXPANSION | FAILED | 936/450/543 | −0.27 / −0.80 / −2.09 | −2.68 | INCONCLUSIVE |
| Next day | RELATIVE_STRENGTH | FAILED | 969/470/569 | 1.40 / 1.26 / −0.01 | −0.61 | ROBUST |
| Swing 3–10D | TREND | FAILED | 268/130/160 | 0.86 / 1.97 / −0.05 [−0.15] | −0.65 | ROBUST |
| Swing 3–10D | MOMENTUM | **FRAGILE** | 268/130/160 | 5.13 / 7.94 / 0.92 | +0.31 | ROBUST |
| Swing 3–10D | BREAKOUT | FAILED | 204/105/105 | 1.88 / 3.34 / −1.92 | −2.51 | ROBUST |
| Swing 3–10D | PULLBACK | INSUFFICIENT_DATA | 0/4/0 | — | — | — |
| Swing 3–10D | MEAN_REVERSION | FAILED | 147/99/89 | −1.06 / −1.08 / −0.29 | −0.89 | INCONCLUSIVE |
| Swing 3–10D | VOLUME_EXPANSION | FAILED | 269/126/146 | 1.09 / 0.77 / −1.80 | −2.39 | FRAGILE |
| Swing 3–10D | RELATIVE_STRENGTH | **FRAGILE** | 269/130/159 | 3.14 / 0.53 / 0.61 | +0.01 | ROBUST |
| Swing 2–4W | TREND | FAILED | 129/60/70 | 1.02 / 1.43 / −0.35 [0.09] | −0.94 | ROBUST |
| Swing 2–4W | MOMENTUM | FAILED | 130/60/68 | 4.97 / 10.33 / −0.10 | −0.70 | ROBUST |
| Swing 2–4W | BREAKOUT | FAILED | 87/46/41 | 8.17 / 5.54 / −1.72 | −2.31 | ROBUST |
| Swing 2–4W | PULLBACK | INSUFFICIENT_DATA | 0/0/1 | — | — | — |
| Swing 2–4W | MEAN_REVERSION | FAILED | 74/38/41 | 1.68 / −0.13 / −2.89 | −3.48 | FRAGILE |
| Swing 2–4W | VOLUME_EXPANSION | FAILED | 129/56/68 | 5.14 / 3.79 / −1.09 | −1.69 | ROBUST |
| Swing 2–4W | RELATIVE_STRENGTH | FAILED | 129/59/67 | 6.81 / 6.83 / −1.83 | −2.42 | ROBUST |
| Position 1–3M | all 7 | INSUFFICIENT_DATA | VAL/OOS ≤ 20 | — | — | — |

### Closest candidates (still not survivors)
- **Swing 3–10D MOMENTUM** — only trial with a material positive OOS net after stress
  (+0.31%) and above baseline. Neighbours are now ROBUST (were FRAGILE on 09-23).
  Walk-forward folds: +15.0 / +3.5 / −2.5 / −7.8 / +3.8. DSR FAIL. Same regime-dependence
  as before; gap fill and CA controls did not create an edge.
- **Swing 3–10D RELATIVE_STRENGTH (foreign flow)** — OOS gross +0.61%, net +0.01%
  (barely covers the 0.60% stress round-trip), 4/5 folds positive, ROBUST neighbours.
  One negative fold → FRAGILE. DSR FAIL. Not a production candidate.

### What changed vs 2026-09-23
- Stock history is continuous 2023-01-02→2026-09-22 (882 sessions, 0 gaps). IS next-day
  sample roughly doubled (e.g. TREND 450→968) because Jan–Oct 2025 is no longer split.
- SWING_2_4W MOMENTUM / BREAKOUT / MEAN_REVERSION left INSUFFICIENT_DATA and **FAILED**
  on OOS — the previous “not enough data” was not hiding a winner.
- Prices are exchange-reference adjusted; 133 price-distorting CA events in the
  survivorship audit range; spanning trades excluded.
- 2023–2024 bars are used only as PIT warm-up before the locked 2025-01-02 start.

### Structural findings
- PULLBACK still almost never fires on liquid IDX names — not re-tuned.
- POSITION_1_3M still cannot reach 30 trades in VALIDATION/OOS with a ~21-month
  locked window and 42-session holds. That is a window-length limit, not a data hole.
- IS/VALIDATION still look better than OOS (Apr–Sep 2026) for most families —
  consistent with regime change, not a stable edge.

## Limitations (explicit)
- Survivorship **NOT_VALIDATED** (no delisting/suspension/ticker-change registry).
- Costs remain illustrative; no real IDX fee/tax schedule or measured slippage
  (`NOT_CONFIGURED`).
- Close-to-close fills; stop fills at stop level (optimistic on gaps); no lot size /
  ARA-ARB / liquidity limits.
- DSR/BH use per-period portfolio returns; overlapping windows make p-values approximate.
- Broker/index summaries still have holes (not used by this study). Offline V2/V3.x
  labs predate gap segmentation and CA exclusion.

## Decision
No family is promoted. Screener rows remain `production_eligibility=NOT_VALIDATED`.
The 2026-09-23 “re-run after gap + CA controls” condition is now met. Remaining
research blocker for a *tradable* claim is a real cost/slippage model plus
survivorship-safe universe data — not another parameter search on these families.
