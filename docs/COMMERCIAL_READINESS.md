# Commercial / IP / Data-Licensing Readiness — 2026-09-23

Engineering status only. **Not legal advice.** Items needing counsel, contracts or
provider agreements are `BLOCKED_EXTERNAL`; nothing here grants redistribution rights.

## Code licensing

| Item | Status | Evidence / action |
|---|---|---|
| Upstream code license | GREEN | `LICENSE` MIT retained (upstream `nichsedge/idx-bei`); keep copyright + permission notice in distributions |
| Upstream attribution in product | PARTIAL | Attribution in repo docs; product "About"/legal page is a UI-finalization task |
| SBOM | GREEN (factual) | `docs/SBOM.cdx.json` (CycloneDX 1.5) via `uv run idx sbom` — Python runtime closure (29) + frontend prod deps (6) |
| Dependency license inventory | PARTIAL | `docs/DEPENDENCY_LICENSE_INVENTORY.md` — declared metadata; 2 review items: `certifi` (MPL-2.0), `tqdm` (MPL-2.0 AND MIT), both unmodified. Status NOT_LEGALLY_REVIEWED |
| THIRD_PARTY_NOTICES / NOTICE | BLOCKED_EXTERNAL | Not generated — legal text must come from counsel/release process (DECISION_LOG: no fabricated NOTICE) |
| Runtime dependency declaration | GREEN | `pandas` / `numpy` were missing from `idx-bei` runtime deps (only via dev group) — fixed + regression test |
| Opt-in Yahoo/yfinance | GREEN (guarded) | optional extra `fx-yahoo`; off by default; not in runtime closure |

## Data-source rights

| Source | Use | Status |
|---|---|---|
| IDX public website/API (stock/broker/index summary, company profiles, financial ratios, corporate actions) | Core EOD data | **BLOCKED_EXTERNAL** — commercial redistribution/derived-data rights not established; public access ≠ license |
| Realtime vendor (IDX ITCH, IQ Plus, RTI, LSEG, Bloomberg…) | Realtime | **NOT_CONFIGURED** — vendor/legal selection by Product Owner (`docs/PRODUCTION_DECISION_PACK.md`) |
| KSEI ownership | Ownership drift | **NOT_CONFIGURED** — no verified legal source |
| KPK LHKPN | PEP radar | **BLOCKED_EXTERNAL** — optional/offline; legal review before commercial use |
| Yahoo Finance FX | FX quote | Opt-in only; **not** for commercial default path |
| Broker fee / tax schedule, slippage (TCA) | Net returns | **NOT_CONFIGURED** — needs broker contract + execution data |

## Branding
- Product brand RitelInsight; IDX/BEI used only as data-source labels. Full UI rebrand is part of
  UI & Product Finalization (DECISION_LOG 2026-09-23 product identity).

## Before commercial launch (checklist)
1. Counsel review of IDX data terms and derived-data display/redistribution.
2. Contracted realtime + (if used) ownership source.
3. NOTICE / THIRD_PARTY_NOTICES from counsel using `docs/SBOM.cdx.json`.
4. MPL-2.0 obligations confirmed for `certifi` / `tqdm` (unmodified use).
5. Contributor/provenance check; trademark check for "RitelInsight".
