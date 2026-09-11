# TalonX — Three-Day Controlled Paper-Session Audit (September 8–10, 2026)

Sanitized evidence bundle for independent roadmap review. All figures trace to preserved session
snapshots under `results/` (git-ignored) and are reproducible from the source references in
`evidence_manifest.csv`.

---

## 1. Scope and dates

| session | date (XNYS) | campaign day | role |
|---|---|---|---|
| S1 | 2026-09-08 (Tue) | 1 | First full-day V2 live-paper qualification (Task 113). Operator ran the base stack + a V2 companion in two terminals. |
| S2 | 2026-09-09 (Wed) | 2 | Autonomous prospective operator (`talonx_ops.prospective`) — one-command start, 30-min checkpoints. |
| S3 | 2026-09-10 (Thu) | 3 | Controlled live-paper **activation**: execution scope enforced to 39 names in code, `composite-yf` reference pricing, official Telegram delivery armed, one labelled connectivity smoke test. |

All three sessions ran the **frozen** `INSIDER_BUY_CLUSTER_V2@1` strategy (fingerprint
`11107198c5b81237`, unchanged all three days) as the active Original-flow **paper** strategy on a
local `$300,000` cash-only ledger (`v2_lane.db`). No real capital, no broker, no shorts.
The application was **stopped after the September 10 EOD close** and has not been restarted.

## 2. Running SHA per session

| session | HEAD SHA | short | notes |
|---|---|---|---|
| S1 2026-09-08 | `54c9b4006a993131f932e9b9c820f06f9f702269` | `54c9b40` | P1 fix (`ABCL` historical-replay staleness guard) committed pre-open, replacing `d78faa0`. V1 fp `2ae6216bca70`, V2 fp `11107198c5b81237` unchanged. |
| S2 2026-09-09 | `9bec2791dee84e7097f5d3bb3c5d475cfa732111` | `9bec279` | Task 114 unified V2 dashboard + autonomous operator. |
| S3 2026-09-10 | `e1de6c10635c583cfee15f8425ac2b9b50d23a58` | `e1de6c1` | Task 117 scope enforcement (`48d2946`) + scope-review fixes (`71c6d69`, `5aed385`) + release-pin (`0d52e7c`, `e1de6c1`). |

Branch for all three: `research/talonx-strategy-validation`. Tree clean at each session's HEAD.
This bundle is published at HEAD **`e1de6c1`** (see final commit).

## 3. Available vs missing evidence

### Available (preserved snapshots)
- Per-session V2 service status JSON, 30-min checkpoint chains, `events.jsonl`.
- Canonical EOD reports (`prospective close` stdout/exit/reports) for S2 and S3; Task-113
  reconciliation summary for S1.
- Consistent SQLite `.backup()` snapshots of `v2_lane.db`, `dispatch_audit.db`,
  `paper_trading.db`, `experimental_paper.db`, `exp_alerts.db`, `ingestion_ledger.db`,
  `eod_reconciliation.db`, `quant.db` (S3 pre-close and post-close).
- S3 Original app log (`talonx.log`), V2 companion log, supervisor log.
- Redis identity/keyspace captures (non-consuming) for S2 and S3.
- S3 activation evidence: preflight, migration md5 chain, Telegram smoke-test record,
  bit-for-bit replay-vs-Task-116 comparison.
- S2 read-only pre-EOD forensic audit (`forensic_summary.json`) — closes the S2 candidate
  accounting to an exact integer invariant.

### Missing / not recoverable
| gap | consequence |
|---|---|
| S3 Redis `metrics:<date>:quant:*` counter snapshot | The mid-session ping's "126 candidates / 3 publications" cannot be reconciled to a **closed** integer invariant for S3 (it was closed exactly for S2). |
| S3 Experimental-lane process log (`experimental.log` / equivalent) | S3 Experimental quant-signal publications are reconstructed from `exp_alerts.db` (`directional_alerts`), not from a signal log. |
| S1 per-lane message counters / ping | S1 candidate accounting is qualitative (0 published everywhere downstream); no numeric funnel snapshot preserved. |
| Screenshots (all sessions) | No screenshot tool in the evidence-capture sessions; dashboard **JSON API** responses are preserved instead. |
| Telegram message IDs for the ORCL long-term sends (LT6–LT8) | Only the smoke test carries a stored message ID (710). LT6–LT8 are API-`telegram_sent=1` with a timestamp, no stored ID. |
| Human-confirmed Telegram **receipt** | Only API-confirmed send is in evidence. The user reports receiving fewer messages than the reports claim were sent — **unresolved** (see `telegram_reconciliation.csv`). |

## 4. Lane and counter definitions

### Lanes
| lane | what it is | ledger / channel | external delivery |
|---|---|---|---|
| **V2 trading** | `INSIDER_BUY_CLUSTER_V2@1` — ≥2-distinct-owner code-P (open-market purchase) insider clusters, next-session-open entry, 10-trading-day hold. The audited strategy. | `v2_lane.db`; `v2_alert_outbox` → `deliver_outbox` → official Telegram | **armed, HOLD-safe** (S3); nothing to send all 3 days |
| **Original intraday** | The legacy `run_talonx.py` intraday technical strategy (`talonx_quant` → `talonx_brain` → `talonx_dispatch`). Inactive baseline during V2 sessions. | `paper_trading.db.trade_history`; `dispatch_audit.alerts` | official Telegram; 0 intraday alerts all 3 days |
| **Original long-term** | Buy-and-hold fundamental "hold_quality" assessments triggered by SEC filings (8-K earnings etc.). | `dispatch_audit.long_term_alerts`; `talonx:alerts:longterm` | official Telegram; the only strategy-adjacent sends in the window (ORCL) |
| **Intelligence** | Task-96 descriptive event & risk intelligence — significance-scored 8-K/10-Q/Form-4 event cards. Informational, not trade orders. | `ingestion_ledger.db.intelligence_delivery` (a **separate** Telegram outbox) | enqueue-only — **outbox never drains** (D5) |
| **Experimental** | `talonx_signals` relaxed-threshold research lane (`EXPERIMENTAL_RELAXED_V1`). Internal validation paper only. | `experimental_paper.db`; `exp_alerts.db`; `talonx:exp:*` (isolated) | **structurally blocked** — every record `sent=0` + `DRY_RUN_HELD` |
| **System / admin** | Operator connectivity checks, provider warnings, Redis reconnects. | logs; `activation/telegram_smoke_test.json` | the S3 smoke test (message 710) only |

### Counters
| counter | definition | caveat established in this audit |
|---|---|---|
| **candidates / evaluated** | Bars that passed the cheap pre-filters and entered substantive gate evaluation, from `metrics:<date>:quant:*` Redis counters. | **Comingled Original + Experimental** — the Redis keys carry **no lane suffix**, so Original and Experimental both increment them (S2 forensic finding, P3 / D6). Not V2. |
| **publications / quant published** | Candidates that reached the publish stage. | Same comingling. On S2, **all 9 "published" were Experimental** (isolated `talonx:exp:*`, never routed downstream). On S3, the mid-session "3" corresponds to **3 Experimental `WOULD_PASS` directional alerts** before the 16:24:25Z cutoff (SHOP 14:28Z, BLSH 15:22Z, SKHY 16:10Z) — see `signal_delivery_trace.csv`. |
| **displayed rejections** (confluence / opening-blackout / trend) | Terminal gate suppressions in `dispatch_audit.rejected_candidates`, **Original lane only**, and **excluding** the volatility pre-filter. | The dashboard funnel shows only these three; it is **not** the full disposition set. |
| **pre-evaluation drops** | `dropped_duplicate_bars`, `failed_min_volatility` — dropped before the `evaluated` pool. | Not in `evaluated`; must be kept separate (avoids double-counting). |
| **off-counter dispositions** | THROTTLE / COOLDOWN / failed-revalidation. | Recorded only on `talonx:quant:rejected` + `rejected_candidates` DB, **not** in `metrics:quant:*` — so the integer surface under-counts `evaluated` by exactly this class (S2: residual 4 = this class; closes exactly). |
| **V2 execution scope** | The enforced allowlist size. S3: **39** SEC-covered active-watchlist issuers, recomputed each session start from `talonx_ops.watchlist_coverage.build_coverage_map()`. | S1/S2 had **no in-code scope filter** (the InsiderStore's full history was visible to V2); S3 added it (`48d2946`). |

## 5. Navigating the bundle

| file | contents |
|---|---|
| `README.md` | this file |
| `watchlist_scope.csv` | all 48 configured tickers × active state × SEC-coverage disposition × V2 eligibility × serving lane, with the 43-active / 39-covered S3 manifest and cross-day notes |
| `signal_delivery_trace.csv` | every recoverable S1–S3 publication / delivery attempt, paper outcome vs notification outcome, evidence ref + confidence; the S3 "three publications" addressed explicitly |
| `candidate_reconciliation.md` / `.csv` | per-session, per-cutoff funnel accounting; counter definitions; S2 exact closure; S3 `126−18−10−1−3 = 94` assessment (structurally explained, exact closure not possible from preserved evidence — residual **UNRESOLVED**) |
| `intelligence_delivery_audit.csv` | the 23 S3 enqueued cards (event id, accession, band, route, state, hold reason, sanitized summary) + the 9,843-row pending backlog summarized by date/type/state |
| `telegram_reconciliation.csv` | the 4 claimed S3 sends (smoke test 710, ORCL heads-up, LT7, LT8) reconciled — API ack vs receipt; LT7/LT8 content comparison; Oracle alerts across all 3 days; destination aliased `DEST_A` |
| `lane_outcomes.csv` | per session × lane: publications / cards / deliveries / paper entries / exits / open / realized+unrealized P&L / costs / pending obligations |
| `findings.md` | D1–D7 consolidated + contradictions found during export; each with evidence, impact, uncertainty, proposed acceptance check. **No fixes implemented.** |
| `evidence_manifest.csv` | exported file × source snapshot reference × acquisition timestamp × row count × SHA-256 |

## 6. Findings status — proven / inferred / unresolved

| # | finding | status | basis |
|---|---|---|---|
| **PROVEN** | | | |
| | V2 made 0 signals / 0 trades / 0 deliveries all 3 days; `v2_lane.db` logically unchanged (cash $300,000, 1 terminal ABCL `SKIPPED_ENTRY_STALE`). | proven | 3× EOD reconciliation, ledger md5 chain, checkpoint chains |
| | V2 fingerprint `11107198c5b81237` and V1 `2ae6216bca70` unchanged across all 3 sessions. | proven | checkpoints, Task-113/114 fingerprint scripts |
| | S3 execution scope enforced at 39 issuers every tick; 17 out-of-scope records dropped/tick; only in-scope ABCL reached `processed_episodes`. | proven | S3 companion log (307 ticks), `v2_service_status.json`, `v2_lane.db` |
| | Experimental external delivery OFF all 3 days — every `directional_alerts` / `experimental_trades` row `sent=0` + `DRY_RUN_HELD`. | proven | `exp_alerts.db` snapshots |
| | S2 candidate accounting closes to an exact integer invariant (evaluated 121 = sum of terminal dispositions incl. the off-counter class). | proven | S2 `forensic_summary.json` |
| | The `metrics:quant:*` counters are comingled Original+Experimental with no lane suffix. | proven | S2 forensic (9 "published" all in `experimental.log`, 0 in `original.log`) |
| | S3 Intelligence `intelligence_delivery` outbox: 9,843 rows, 100% `PENDING`, **0 sent ever**. | proven | `ingestion_ledger.db.intelligence_delivery` snapshot |
| | S3 canonical close: exit 0, `PASS_WITH_FINDINGS`, `shutdown_clean: true`, `residual_talonx_processes: []`, Redis retained (`run_id` unchanged). | proven | S3 `eod.json`, residual probe, Redis capture |
| **INFERRED** | | | |
| | The S3 mid-session "3 quant publications" = the 3 Experimental `WOULD_PASS` directional alerts before 16:24:25Z (SHOP, BLSH, SKHY). | inferred (high confidence) | exact count match + S2-proven comingling; **no S3 Experimental signal log** to make it direct |
| | The S3 "94 unexplained" candidates are the same structural cause as S2 (comingled counter + off-counter dispositions + Experimental terminal rejections not in the displayed 3-gate breakdown). | inferred | S2 analogue closed exactly; S3 lacks the Redis metrics snapshot to close numerically |
| | S3 provider `PROVIDER_SCHEMA_ERROR` (66) had no effect on the 0-signal outcome. | inferred (high) | market feed HEALTHY / coverage 1.0 all session; no data-availability gate row |
| **UNRESOLVED** | | | |
| | Exact S3 candidate-funnel closure (`126 − 18 − 10 − 1 − 3 = 94`). | **unresolved** | S3 Redis `metrics:quant:*` snapshot not preserved; not reconstructable |
| | Why the user received fewer Telegram messages than the reports claim were sent. | **unresolved** | only API-confirmed send in evidence; no delivery-receipt log; not investigated further this task |
| | Whether any eligible Intelligence event card was *lost* (vs merely undelivered) while the outbox backlog sat at 9,843. | **unresolved** | 0 downstream activity is **not** proof nothing was lost; the outbox has never drained |
