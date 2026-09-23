# Trading Plan & Journal — Excel → Product Mapping

**Source of truth (structure):**  
`C:\Users\ThinkPad T495s\OneDrive\Documents\Trading Plan & Jurnal_V1.xlsx`

**Audit date:** 2026-09-23  
**Status:** READ-ONLY ANALYSIS — implementation not started  
**Product home:** TAB 7 — Trading Plan & Journal  

Related: `docs/ARCHITECTURE_AUDIT.md`

---

## 1. Workbook inventory

| Sheet | Purpose | Layout | Formulas | Validations |
|---|---|---|---|---|
| **Dashboard** | Monthly KPI, equity, calendar, top P/L, tomorrow watchlist, capital ledger | Dashboard UI | ~331 | none |
| **Panduan** | User manual (Indonesian) | Text column A | 0 | none |
| **TradingPlan** | Pre-trade checklist + levels | **Vertical fields (rows) × one trade per column** | ~99 | dropdowns |
| **Jurnal** | Post-trade journal | Same vertical layout | ~244 | dropdowns |
| **RekapMingguan** | Weekly rollup from Jurnal + Plan | One week per column | ~160 | none |

Defined names: **none**.

**Panduan explicit note (row 81):** sample data in all tabs is **DUMMY/CONTOH** for demonstration. Do not treat September 2026 sample trades as production history unless user imports intentionally.

---

## 2. Workflow (must preserve)

```
NIGHT BEFORE / PRE-MARKET
  └─ Fill TradingPlan column (confirmations + S/R + Entry/CL/TP)
       └─ Confirm Score (Auto) + Result (Auto)
            └─ Action (manual) + Plan result (Trade / No Trade)
                 └─ Appears on Dashboard "Daftar Pantauan Besok"

DURING / AFTER TRADE
  └─ Fill Jurnal column (actual entry/exit/lots/psychology)
       └─ Fee & P/L Net auto from Dashboard fee %
            └─ Target RR pulled from matching TradingPlan (date+emiten)
                 └─ Dashboard calendar / KPI / RekapMingguan update on EXIT date
```

Key rules from Panduan:

1. **One column = one trade/plan**, not one day. Multiple trades same day = multiple columns.  
2. Aggregations use **Tanggal Exit** (not entry) for calendar/KPI/weekly.  
3. Hold days = `NETWORKDAYS(entry, exit) - 1`.  
4. 1 lot = **100 shares** (BEI standard).  
5. Fees configurable on Dashboard (`Fee Beli %`, `Fee Jual %`); defaults 0.15% / 0.25% (Stockbit fee page cited as of Aug 2026 — **fee config**, not Stockbit branding).  
6. TF1H, TF30M, RSI **intentionally removed**; 11 confirmations are enough.

---

## 3. TradingPlan — field dictionary

Layout: Column A = field label; Columns B… = trades.

| Excel row / label | Type | Source | Values / formula | Web DB field (proposed) | Notes |
|---|---|---|---|---|---|
| (row1) fill count | auto | formula `COUNTA` | — | *(omit UI)* | housekeeping |
| (row2) header chip | display | manual pattern `dd/mm TICKER` | — | `display_label` optional | can be derived |
| Tanggal | date | **manual** | date | `plan_date` | plan date |
| Emiten | text | **manual** | ticker | `ticker` | |
| TF1D | enum | **manual** | Bullish / Sideway / Bearish | `tf_1d` | |
| TF15M | enum | **manual** | Bullish / Sideway / Bearish | `tf_15m` | |
| TF5M | enum | **manual** | Bullish / Sideway / Bearish | `tf_5m` | |
| MACD | enum | **manual** | Bullish / Sideway / Bearish | `macd_bias` | |
| Volume | enum | **manual** | Buy / Sell | `volume_bias` | |
| Supertrend | enum | **manual** | Buy / Sell | `supertrend_bias` | |
| MA5 | enum | **manual** | OK / NOK | `ma5_ok` | |
| MA20 | enum | **manual** | OK / NOK | `ma20_ok` | |
| MA50 | enum | **manual** | OK / NOK | `ma50_ok` | |
| VWAP | enum | **manual** | OK / NOK | `vwap_ok` | |
| Broksum | enum | **manual** | Acc / Normal / Dist | `broksum` | **User judgment**, not auto bandar claim |
| Confirm Score (Auto) | int | formula | −11…+11 | `confirm_score` | server-computed |
| Result (Auto) | enum | formula | Buy / Wait & See / No Trade | `result_auto` | server-computed |
| Action | enum | **manual** | Buy on weakness / Buy on Breakout / No Trade | `action` | |
| Current Price | number | **manual** | price | `current_price` | |
| S1 | number | **manual** | support | `s1` | structural |
| S2 | number | **manual** | support | `s2` | |
| S3 | number | **manual** | support | `s3` | |
| R1 | number | **manual** | resistance | `r1` | |
| R2 | number | **manual** | resistance | `r2` | |
| R3 | number | **manual** | resistance | `r3` | |
| Entry Price | number | **manual** | price | `entry_price` | Excel single entry (see §6 for Entry Zone extension) |
| CL | number | **manual** | cut loss | `cl` | Excel single CL |
| TP | number | **manual** | take profit | `tp` | Excel single TP |
| RR (Auto) | number | formula `(TP-Entry)/(Entry-CL)` | | `rr_planned` | |
| Plan result | enum | **manual** | Trade / No Trade | `plan_result` | final human decision |

### Confirm Score formula (preserve exactly)

For each confirmation:

- Bullish / Buy / OK / Acc → **+1**  
- Bearish / Sell / NOK / Dist → **−1**  
- Sideway / Normal / empty handled as **0** (Sideway & Normal)

Sum of: TF1D, TF15M, TF5M, MACD, Volume, Supertrend, MA5, MA20, MA50, VWAP, Broksum.

### Result (Auto) formula (preserve exactly)

1. If TF1D = Bearish → **No Trade**  
2. Else if Volume = Sell **AND** Supertrend = Sell → **No Trade**  
3. Else if Broksum = Dist → **No Trade**  
4. Else if score ≥ 6 → **Buy**  
5. Else if score ≥ 2 → **Wait & See**  
6. Else → **No Trade**

Thresholds configurable (Panduan notes `>=6` / `>=2` can be tightened).

### RR (Auto)

```
RR = (TP - Entry) / (Entry - CL)   if denominator ≠ 0
```

---

## 4. Jurnal — field dictionary

| Excel label | Type | Source | Web DB field | Notes |
|---|---|---|---|---|
| Tanggal Entry | date | manual | `entry_date` | |
| Emiten | text | manual | `ticker` | |
| Sesuai Plan | enum | manual | `followed_plan` | `ya` / `tidak` |
| Alasan Masuk | text | manual | `entry_reason` | |
| Harga Entry | number | manual | `entry_price` | |
| Support CL | number | manual | `support_cl` | planned structural CL |
| Harga CL | number | manual | `stop_price` | actual stop used |
| Target RR (Auto) | number | formula from TradingPlan match | `target_rr` | match `plan_date+ticker` |
| Harga Exit | number | manual | `exit_price` | |
| Tanggal Exit | date | manual | `exit_date` | **aggregation key** |
| Cara Exit | enum | manual | `exit_method` | trailing / TP / CL |
| Jumlah Lot | number | manual | `lots` | ×100 shares |
| Nilai Beli (Rp) | auto | `entry * lots * 100` | `buy_value` | |
| Nilai Jual (Rp) | auto | `exit * lots * 100` | `sell_value` | |
| Fee Beli (Rp) | auto | `buy_value * fee_buy_pct` | `fee_buy` | from settings |
| Fee Jual (Rp) | auto | `sell_value * fee_sell_pct` | `fee_sell` | |
| P/L Kotor (Rp) | auto | `exit_price - entry_price` | `gross_pl_per_share` | **per share**, not × lots |
| P/L Net (Rp) | auto | `(sell - fee_sell) - (buy + fee_buy)` | `net_pl` | **canonical P/L** |
| P/L Net (%) | auto | `net_pl / (buy + fee_buy)` | `net_pl_pct` | |
| RR Realized | auto | `(exit-entry)/(entry-stop)` | `rr_realized` | uses Harga CL |
| Hold (hari bursa) | auto | NETWORKDAYS−1 | `hold_trading_days` | |
| Pelanggaran | enum | manual | `violation` | see enums |
| Emosi | enum | manual | `emotion` | |
| Pelajaran | text | manual | `lesson` | |

### Target RR lookup (preserve semantics)

Match Jurnal `(Tanggal Entry, Emiten)` to TradingPlan `(Tanggal, Emiten)` and pull `RR (Auto)`.

**LIMITATION (Excel):** if two identical date+ticker plans exist, SUMPRODUCT **sums** RRs — rare; web should enforce unique `(user_id, plan_date, ticker)` or explicit `plan_id` FK.

---

## 5. Dashboard — derived views (web modules)

| Excel block | Behavior | Web equivalent |
|---|---|---|
| Bulan Aktif (C5) | Month selector | `month` query param / UI control |
| Fee Beli/Jual | Global settings | `user_settings.fee_buy_pct`, `fee_sell_pct` |
| KPI row | Total trades, win rate, net P/L, avg %, W/L | Journal dashboard cards |
| Total Equity | `capital_base + sum(net_pl)` | Equity module |
| Kalender trading | Daily net P/L by **exit date** | Month calendar |
| Ringkasan bulan | Avg %, net Rp, TP count, CL count, winrate | Monthly summary |
| Top profit / loss emiten | Ranked by net P/L | Leaderboard |
| Daftar Pantauan Besok | Plans where `Tanggal = watch_date` (default next session) | Watch strip (max 5 in Excel) |
| Deposit / Withdraw ledger | Manual capital adjustments | `capital_transactions` table |

Charts (Excel native): equity curve month, weekly P/L, monthly P/L year — recreate with chart lib, not Excel objects.

---

## 6. RekapMingguan — derived views

Per week column:

| Metric | Source |
|---|---|
| Periode Mulai / Selesai | manual week bounds |
| Total Trade / Win / Loss / Win Rate | Jurnal by exit date |
| Total P/L Net / Avg P/L Net % | Jurnal |
| Total Fee Dibayar | fee buy + fee sell |
| Avg RR Rencana | TradingPlan RR in week |
| Avg RR Realized | Jurnal |
| Sesuai Plan / Melanggar Plan counts | Jurnal |
| Pelanggaran breakdown | entry impulsif, cut loss telat, revenge, size gak sesuai, lainnya |
| Catatan Pola Emosi | manual notes |
| Perbaikan Minggu Depan | manual notes |

---

## 7. Enums (must match Excel strings for import)

```
tf_bias:        Bullish | Sideway | Bearish
flow_bias:      Buy | Sell
ok_flag:        OK | NOK
broksum:        Acc | Normal | Dist
action:         Buy on weakness | Buy on Breakout | No Trade
plan_result:    Trade | No Trade
result_auto:    Buy | Wait & See | No Trade
followed_plan:  ya | tidak
exit_method:    trailing | TP | CL
violation:      tidak ada | entry impulsif | cut loss telat | revenge | size gak sesuai | lainnya
emotion:        tenang | FOMO | panik | serakah
```

---

## 8. Excel → Database → API → UI mapping

### 8.1 Tables (proposed)

```
users
user_settings (fee_buy_pct, fee_sell_pct, confirm_buy_threshold=6, confirm_wait_threshold=2, ...)
capital_transactions (type deposit|withdraw, amount, date, note)
trading_plans (...fields §3..., user_id, status, created_at)
journal_entries (...fields §4..., user_id, plan_id NULLABLE, created_at)
```

Plan status extension for product (beyond Excel):

| Status | Meaning |
|---|---|
| `PLANNED` | Plan filled, not traded |
| `OPEN` | Position open (optional bridge; Excel has no open-position sheet) |
| `PARTIAL` | Partial exit (extension; Excel is full close per column) |
| `CLOSED` | Linked journal exists |
| `CANCELLED` | Plan result No Trade / abandoned |

**ASSUMPTION:** Excel models **closed round-trips** primarily. Open positions are a web extension; document clearly in UI.

### 8.2 API (proposed)

```
GET/POST   /api/trading-plan
GET/PATCH  /api/trading-plan/{id}
POST       /api/trading-plan/{id}/compute   # confirm_score, result_auto, rr

GET/POST   /api/journal
GET/PATCH  /api/journal/{id}
GET        /api/journal/dashboard?month=YYYY-MM
GET        /api/journal/calendar?month=YYYY-MM
GET        /api/journal/weekly?week_start=YYYY-MM-DD
GET        /api/journal/watchlist-tomorrow?date=YYYY-MM-DD

GET/PUT    /api/settings/trading
GET/POST   /api/capital-transactions
```

All scoped by authenticated `user_id` from session/token — **never** from client body alone.

### 8.3 UI structure (mobile-first)

Excel’s column-per-trade is desktop-spreadsheet native. Web must use:

- **List / cards** of plans & journal entries (row-per-trade)  
- Detail form with same fields & dropdowns  
- Dashboard month view + calendar  
- Weekly review page  

Do **not** force a spreadsheet grid as the only mobile UX.

---

## 9. Gap analysis vs product brief (§12 in master brief)

| Product brief ask | Excel has? | Decision |
|---|---|---|
| TP1 / TP2 / TP3 | Single `TP` + R1/R2/R3 | **Map:** keep Excel `tp` as primary planned TP; optionally map R1/R2/R3 → suggested TP1/TP2/TP3 with user confirm; do not delete R levels |
| CL1 / CL2 / CL3 | Single `CL` + S1/S2/S3 | **Map:** `cl` primary; S1/S2/S3 as structural invalidation ladder; optional CL1/2/3 derived later by engine — journal still records actual stop used |
| Entry Zone | Single Entry Price | **Extension:** add optional `entry_low` / `entry_high`; keep `entry_price` required for RR compatibility |
| RR ≥ 1:2 gate | Excel allows any RR (samples often < 2) | **Engine screener** enforces RR≥2; **Journal** must still allow recording real trades that violated plan (honesty) — show warning badge, don’t block journaling |
| Position size / Risk % / Risk Amount | Not in Excel | Optional extension fields; not required for v1 parity |
| Screenshot | Not in Excel | Future upload; not blocking |
| MFE / MAE | Not in Excel | Optional enrichment from market data after exit; label source |
| Status OPEN/PARTIAL | Not modeled | Soft extension |
| Confirm Score 11-check | **Core Excel IP** | **Must implement** — this is the user’s edge process |

---

## 10. Formula portability (server-side)

| Name | Port to |
|---|---|
| Confirm Score | `compute_confirm_score(plan) -> int` |
| Result Auto | `compute_result_auto(plan, thresholds) -> enum` |
| RR planned | `compute_rr(entry, cl, tp) -> float | null` |
| Buy/Sell value | `price * lots * 100` |
| Fees | `value * fee_pct` |
| Net P/L | `(sell - fee_sell) - (buy + fee_buy)` |
| Net P/L % | `net / (buy + fee_buy)` |
| RR realized | `(exit - entry) / (entry - stop)` |
| Hold days | trading-day calendar (IDX holidays table) — **ASSUMPTION:** start with weekday NETWORKDAYS; later subtract official holidays from ingestion calendar |

---

## 11. Import / export

Phase recommendation:

1. Implement native web forms matching field dictionaries.  
2. Add Excel/CSV import that maps columns → records (with dummy-data warning).  
3. Export journal/plans back to Excel-shaped sheet for user continuity.

Do **not** require Excel runtime in production.

---

## 12. Broksum honesty rule

`Broksum` in Excel is a **manual trader assessment** (Acc/Normal/Dist), often informed by broker summary tools the user views elsewhere.

In `[BRAND_NAME]`:

- Store as user field.  
- Do **not** auto-fill from market-wide broker concentration as if it were stock-specific bandar flow.  
- If future stock-specific broker data exists, offer **suggestion** with lineage — user still confirms.

---

## 13. Sample historical records (context only)

Observed filled plan columns (~24): BUMI, MBMA, BIPI, AMMN, WIRG, KPIG, BRMS, LAPD, AHAP, KIJA, DEFI, PADI, SRSN, BAJA, ASHA, SQMI, HOPE (Sep 2026).  
Journal ~22 closed trades; September KPI example: 22 trades, ~36% win rate, net P/L negative in sample.

**Treat as dummy** per Panduan unless user confirms otherwise.

---

## 14. Implementation checklist (when PHASE 12 starts)

- [ ] DB migrations for plans, journal, settings, capital  
- [ ] AuthZ ownership on every query  
- [ ] Port Confirm Score + Result Auto + RR + fee math with unit tests matching Excel fixtures  
- [ ] Mobile forms with exact enums  
- [ ] Dashboard / calendar / weekly rekap  
- [ ] Tomorrow watchlist from plans  
- [ ] Optional Entry Zone + TP/CL ladder fields without breaking Excel import  
- [ ] Import wizard with “dummy data” warning  
- [ ] No dependency on AI  

---

## 15. Open questions for Akhmad (do not guess)

1. Should web **block** saving a Plan with `RR < 2`, or only **warn** (Excel currently allows any RR)?  
2. Keep Indonesian field labels in UI, English API keys, or bilingual?  
3. Import real journal history from this file, or start empty and keep Excel as structure-only?  
4. Max plans shown on “pantauan besok”: keep Excel’s 5, or configurable?  
5. Final brand string for `[BRAND_NAME]`?

Until answered, defaults documented as:

| Question | Temporary default |
|---|---|
| RR < 2 on Plan | Warn, allow save; Screener engine still filters RR≥2 |
| Labels | Indonesian UI labels (match Excel), English snake_case API |
| Import | Structure-first; import opt-in |
| Pantauan max | 5 default, setting later |
