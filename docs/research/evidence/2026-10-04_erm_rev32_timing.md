# EVENT_RESPONSE_MAP_V1: lock revision 3.2, full-scale timing before the one allowed re-execution

**Run:** 2026-10-04 00:22:35 – 00:38:33 UTC, on the real archive.

| | |
|---|---|
| Tool | `research/event_response_map_v1/tools/phase_d_timing.py` (not part of the lock) |
| Code | lock revision 3.2, the REAL `stage_run` |
| Real | event extraction: 8-K and Form 4 dated attribution, gaps, NO_EVENT sampling |
| Synthetic | prices fed to `outcomes`: same symbols, dates and event rows, random open/close |
| Outputs | written to a temp dir and deleted. No marker was created in the real results dir. |
| What was kept | counts and timings only, nothing containing returns |
| Network | refused by a socket guard throughout |
| Guard audit | one `timing_run` event recorded |
| Evaluate workers | 4 |

## Per-stage timings

| Stage | Duration | Counts |
|---|---|---|
| Load archive (RETURNS + ELIGIBILITY_ONLY) | 76 s | 6,323,392 + 6,315,307 bars |
| Eligibility (D-1, as-traded) + SIC-6770 mask | 56 s | 6,183,597 symbol-days; 2,017,905 eligible; 370 masked |
| Inputs: SEC filings (archive) + Form 3/4/5 parse | 52 s | 1,906,075 dev filings; 158,778 code-P rows |
| 8-K dated attribution, main | 122 s | 236,754 kept (consistent 230,247 · ambiguous 6,792 · no valid ticker 17,909 · disagree 1,460 · no bar 10,752) |
| Form 4 dated mapping + filter, main | < 1 s | 102,874 kept (match 105,150 · disagree 2,408 · ambiguous 2,118 · no valid ticker 6,587 · CIK not in universe 42,515) |
| Gaps, main | 14 s | 778,720 rows |
| Dedup + eligibility join | 8 s | 248,693 events |
| NO_EVENT control | 4 s | **395,519 events in total** |
| Outcomes (synthetic prices) + d0 coverage | 38 s | 395,519 events × 5 horizons, on 6,314,306 bars |
| Evaluate, 390 cells × 10,000 resamples (4 workers) | **439 s** | 390 / 390 |
| Survivorship diagnostic: load, eligibility, events, outcomes | 134 s | 1,222 events on 465,177 bars |
| Write outputs | < 1 s | |
| **Total** | **944 s (15.7 min)** | |

Events by type, after the eligibility join and NO_EVENT sampling:

| Type | Events |
|---|---|
| GAP_UP_3 | 55,136 |
| GAP_UP_5 | 21,468 |
| GAP_UP_10 | 4,802 |
| GAP_DOWN_3 | 52,027 |
| GAP_DOWN_5 | 19,454 |
| GAP_DOWN_10 | 4,390 |
| 8K_2.02 | 26,005 |
| 8K_1.01 | 10,010 |
| 8K_5.02 | 15,578 |
| 8K_7.01 | 19,551 |
| 8K_8.01 | 18,649 |
| FORM4_CLUSTER | 1,623 |
| NO_EVENT | 146,826 |

**Proposed execution time limit:** 2 × 944 s ≈ **32 minutes**.

**Attempt 1, for comparison:** the same code path before revision 3.2 was projected at **about 17 days** for one line alone (`phase_d.py:182`).
