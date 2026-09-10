# Candidate Reconciliation — September 8–10, 2026

Each session and each observation cutoff is treated separately. Counter definitions are in
`README.md §4`. Source snapshots are in `evidence_manifest.csv`.

**Two rules applied throughout:**
1. The residual is **not** assigned to "repeat / in-flight evaluations" — there are no per-candidate
   records to support that. Where a session's evidence does not close the funnel to an exact
   integer, the residual is marked **UNRESOLVED**.
2. Zero downstream activity is **not** used as proof that no eligible event was lost.

---

## S1 — 2026-09-08 (SHA `54c9b40`)

**No numeric funnel snapshot was preserved for S1.** Qualitative reconstruction only:

| lane | observation | source |
|---|---|---|
| Original intraday | 0 quant publications; every candidate suppressed (opening-range blackout / confluence < 2). 0 to Brain / Core / Dispatch / Telegram. `official_telegram alerts_all_time = 0`. | `results/task113_v2_full_day/_eod_reconciliation_summary.json` |
| Experimental | 57 `directional_alerts`; 115 `dispatch_log` rows, all `RECORDED` / `DRY_RUN_HELD`; 0 paper trades; 0 external sends. | same |
| V2 | 24 code-P records → 1 cluster (ABCL) → 1 stale-skipped episode → 0 fresh eligible → 0 signals / 0 buys / 0 sells / 0 open. Ledger equation intact. | `_eod_reconciliation_summary.json` |

**S1 residual: none computable** (no `evaluated` / `metrics:quant:*` snapshot). Downstream = 0 everywhere; **not** treated as proof nothing was missed.

---

## S2 — 2026-09-09 (SHA `9bec279`) — CLOSES EXACTLY

From the read-only pre-EOD forensic audit (`results/prospective_2026-09-09/pre_eod_forensic/forensic_summary.json`, captured 2026-09-09T17:20Z):

### Counter ownership
- `metrics:<date>:quant:evaluated` and `metrics:<date>:quant:*` are a **shared Original + Experimental pool** — the Redis keys carry **no lane suffix**. (P3 / D6.)
- The 9 "published" that day were **all Experimental** — all 9 `talonx_quant.consumer: Signal:` INFO lines are in `experimental.log`, zero in `original.log`. Experimental publishes on the isolated `talonx:exp:*` channel and never routes to Brain/Core/Dispatch/Telegram.

### Pre-evaluation drops (NOT in the `evaluated` pool — kept separate)
| drop | count |
|---|---:|
| `dropped_duplicate_bars` | 25,338 |
| `failed_min_volatility` | 14,278 |

### Evaluated pool = 121
| terminal disposition | count | in `metrics:quant:*`? |
|---|---:|---|
| failed_confluence | 74 | yes |
| dropped_opening_blackout | 25 | yes |
| published (all Experimental) | 9 | yes |
| failed_rr_gate | 4 | yes |
| failed_trend_gate | 2 | yes |
| dropped_uk_session_closed | 2 | yes |
| dropped_us_session_closed | 1 | yes |
| **subtotal with counter** | **117** | |
| THROTTLE / COOLDOWN / failed-revalidation | 4 | **no** — only on `talonx:quant:rejected` + `rejected_candidates` DB |
| **total** | **121** | |

**Invariant: 74 + 25 + 9 + 4 + 2 + 2 + 1 + 4 = 121 = evaluated. Unexplained residual = 0.**

### V2 independent accounting (S2)
24 code-P records → 1 cluster (ABCL) → 1 stale-skipped episode → 0 fresh eligible → 0 signals / 0 buys / 0 sells / 0 open. `ledger_equation_broken = false`. Exact.

---

## S3 — 2026-09-10 (SHA `e1de6c1`) — RESIDUAL UNRESOLVED

### Observation cutoffs
| cutoff | source | candidates | displayed rejections | "publications" |
|---|---|---:|---|---:|
| mid-session ping @ 16:24:25Z | operator ping text (relayed) | 126 | confluence 18 · opening-blackout 10 · trend 1 | 3 |
| end-of-day @ ~20:30Z | `dispatch_audit.rejected_candidates` + `quant.suppression_counts` (S3 snapshots) | n/a (see below) | confluence 18 · opening-blackout 10 · trend 1 (**unchanged from the ping**) + volatility 14,973 | 0 (`published_quant_signals_today`) |

### The display arithmetic (`126 − 18 − 10 − 1 − 3 = 94`)

**What the 94 is NOT:** it is not "repeat / in-flight evaluations" — no records support that.

**Structural explanation (same mechanism proven exactly for S2):**
- "126 candidates" is the **comingled Original + Experimental** `evaluated` counter. The
  "displayed rejections" (18 / 10 / 1) are **Original-lane only**, terminal, and **exclude the
  volatility pre-filter**.
- The Experimental lane on S3 produced **116 `directional_alerts`** (`exp_alerts.db` snapshot),
  of which by the 16:24:25Z cutoff: 85 `WOULD_REJECT LOW_CONFLUENCE`, 3 `WOULD_REJECT TREND_GATE`,
  1 `WOULD_REJECT LOW_RISK_REWARD`, **3 `WOULD_PASS`** (SHOP 14:28Z, BLSH 15:22Z, SKHY 16:10Z).
  Those 3 `WOULD_PASS` are the "3 publications". **None** of the ~89 Experimental `WOULD_REJECT`
  rows appear in the Original-lane "displayed rejections".
- Plus the S2-proven **off-counter class** (THROTTLE / COOLDOWN / revalidation) that is not in
  `metrics:quant:*` at all.

So the 94 ≈ (Experimental terminal rejections) + (Original off-counter dispositions) + (any
Original gate rejections beyond the 3 displayed, e.g. `LOW_RISK_REWARD`, session-closed).

### Why S3 does NOT close to an exact integer
The S3 **Redis `metrics:<date>:quant:*` counter snapshot was not preserved**, and no S3
Experimental process log was captured. Without them the individual terms above cannot be summed
to exactly 94. **Residual: UNRESOLVED.** It is the same *kind* of gap as S2 (which closed only
because the S2 forensic captured the Redis counter family and both lane logs).

### S3 V2 independent accounting (authoritative — not the unscoped dashboard funnel)
| item | value | source |
|---|---:|---|
| execution scope enforced | 39 issuers | `v2_service_status.json`, companion log ×307 ticks |
| out-of-scope records dropped / tick | 17 (e.g. MUNEX, NMZ, PML) | companion log |
| in-scope code-P records kept / tick | 8 | companion log |
| code-P records, 45-day window / today | 24 / 0 | V2 funnel |
| ≥2-distinct-owner clusters | 1 — ABCL (stale, `SKIPPED_ENTRY_STALE`, episode `07242bc857569f60`) | `v2_lane.db.processed_episodes` |
| fresh eligible clusters | 0 | V2 funnel |
| V2 signals / intents / BUYs / SELLs | 0 / 0 / 0 / 0 | `v2_lane.db` |

Today's 14 Form-4 filings (DELL×5, AFL, PG×6, V, ADP, JPM) were **not** open-market purchases
(`code_p_records_today = 0`) — option exercises / dispositions / grants. No new cluster formed.

---

## Cross-session summary

| | S1 2026-09-08 | S2 2026-09-09 | S3 2026-09-10 |
|---|---|---|---|
| funnel closure | not computable (no snapshot) | **exact, residual 0** | **UNRESOLVED** (no Redis metrics snapshot) |
| Original intraday publications | 0 | 0 | 0 |
| Experimental publications | (57 directional alerts; count not split) | 9 | 3 by 16:24Z (of 8 `WOULD_PASS` / 116 directional all day) |
| V2 publications | 0 | 0 | 0 |
| comingled-counter defect present | yes (D6) | yes (D6) | yes (D6) |
| off-counter disposition class present | unknown | yes (=4) | assumed yes, not quantified |
