# Findings — September 8–10 Audit

No fixes are implemented in this task. Each item: evidence, impact, uncertainty, proposed
acceptance check. Severity: **P1** blocks the next session / capital-safety; **P2** materially
misleads an operator; **P3** cosmetic / low-impact.

---

## Consolidated defect register (D1–D7)

### D1 — Dashboard near-miss funnel not scoped to the enforced execution allowlist · P2
- **Evidence:** S3 `dashboard/section_v2_active_strategy.json` and `events.jsonl` list
  `single_insider_near_miss_issuers = [ADC, INTC, MUNEX, NMZ, PML]`; MUNEX / NMZ / PML are **not**
  in the enforced 39-name scope (`watchlist_scope.csv`, `scope_manifest_39.json`).
- **Impact:** an operator could believe V2 is tracking municipal/fund tickers. Execution is
  correct — S3 companion log drops 17 out-of-scope records every tick; only in-scope ABCL reached
  `processed_episodes`.
- **Uncertainty:** low — the funnel reads the whole InsiderStore; the fix location
  (`talonx_ops/prospective/funnel.py::build_funnel`) is known.
- **Proposed acceptance check:** with scope enforced to N names, the dashboard funnel's near-miss
  and cluster lists contain **only** symbols in the allowlist; a unit test feeds an out-of-scope
  code-P record and asserts it is absent from `build_funnel` output.

### D2 — Shim + worker double-counted as two Telegram `get_updates` owners · P2
- **Evidence:** S2 and S3 both show `supervisor.telegram_get_updates_owners = 2` while the
  network-layer probe reports `logical_owners = 1` / one PID with an established Telegram
  connection. The `.venv` launcher shim and its `pythoncore` worker child of one `run_talonx.py`
  are both matched by the raw cmdline check. (`9bec279` go/nogo notes it as "P3, Task 112T/113/114";
  S3 `FINDINGS.md`.)
- **Impact:** false "supervision STALE — INVARIANT VIOLATION: 2 Telegram get_updates owners" /
  "Telegram receive DEGRADED". No HTTP 409 in any session log; Telegram **send** healthy.
- **Uncertainty:** low — root cause confirmed across three sessions.
- **Proposed acceptance check:** on Windows with the venv shim, the owner count is 1 whenever
  exactly one `run_talonx.py` logical process holds a Telegram long-poll connection; dedupe by
  process group / established-connection probe.

### D3 — Dashboard EOD tile shows a stale / wrong-session reconciliation row · P3
- **Evidence:** S3 `dashboard/section_paper_eod.json` → `eod_reconciliation.status = "STALE"`,
  `values.status = "PARTIAL"`, `last_update = 2026-09-10T07:42:22Z` (a **pre-open** row);
  `overview.active_v2.eod_state = "PARTIAL"` while the authoritative `eod.state` progressed
  correctly. The stale row also shows `experimental_paper.open_positions = 2` vs the live 5.
- **Impact:** cosmetic; the EOD tile lags the real reconciliation by one session.
- **Uncertainty:** low.
- **Proposed acceptance check:** the EOD tile's `session_date` equals the current session; rows
  for other dates are ignored; a pre-open session shows `NOT_DUE_YET`, not a prior `PARTIAL`.

### D4 — `prospective start` prints "NO-GO / session NOT started" while the stack is running · P2
- **Evidence:** S2 `_day2_go_nogo.json` ("`prospective start` exited 2 on a startup-timing race
  … the stack IS up and healthy") and S3 activation `launch_output.txt` — both times the
  post-start `run_preflight(require_stack_up=True)` ran before `dashboard_web.py` bound :8787.
  Recurred on **both** autonomous-start sessions.
- **Impact:** an operator could re-run the start command and spawn a **second** stack / second
  `v2_lane.db` writer. Highest-value P2.
- **Uncertainty:** low — deterministic race, observed twice.
- **Proposed acceptance check:** after `prospective start` returns, exactly one supervisor / one
  V2 companion / one checkpoint daemon are running and the printed verdict reflects the **spawn**
  result, not a preflight snapshot taken before the dashboard port binds; a bounded port-wait
  (or a downgraded "port not yet bound → WARN") precedes the post-start preflight.

### D5 — Intelligence (`intelligence_delivery`) outbox never drains · P2
- **Evidence:** `ingestion_ledger.db.intelligence_delivery` (S3 post-close snapshot): **9,843
  rows, 100 % `state = PENDING` / `disposition = NEW`, `sent_at_utc` NULL for every row, 0 ever
  `SENT`**. Enqueued 9,779 on 2026-09-04 (bulk backfill) + 6 (S1) + 35 (S2) + 23 (S3). Bands:
  HIGH 5,837 / MEDIUM 3,216 / LOW 767 / CRITICAL 23. `intelligence_delivery_log` shows only
  `ENQUEUE` events — no `SEND`/`ATTEMPT`.
- **Impact:** Task-96 event-intelligence cards (significance-scored 8-K / 10-Q / Form-4) are
  rendered and queued for Telegram but **never delivered**. Distinct from the Original long-term
  route (`talonx:alerts:longterm` → `talonx_dispatch.consumer`), which **did** deliver the ORCL
  fundamental alerts. So on these three days no *actionable* fundamental alert was lost via this
  path — but any event that exists **only** as an intelligence card would be silently undelivered.
- **Uncertainty:** medium — it is not established whether this outbox is *intended* to be dry-run
  (Task 96F: "no external send") or whether the drainer is meant to be wired. 23 CRITICAL-band
  rows sitting unsent is the concerning subset.
- **Proposed acceptance check:** a product decision is recorded. If delivery is intended: the
  drainer sends `state → SENT` for eligible rows with an age cap; the 9,843-row historical backlog
  is triaged (bulk `→ EXPIRED`) **before** enabling so the first drain does not flood the channel;
  CRITICAL-band rows are reconciled explicitly. If dry-run is intended: the dashboard and any
  "Intelligence delivery enabled" copy are corrected to say "rendered, not delivered".

### D6 — Candidate accounting is incomplete / not lane-attributable · P3
- **Evidence:** `metrics:<date>:quant:*` Redis counters carry **no lane suffix** — Original and
  Experimental increment the same keys (S2 forensic: all 9 "published" were Experimental, 0
  Original). THROTTLE / COOLDOWN / failed-revalidation dispositions are recorded only on
  `talonx:quant:rejected` + `rejected_candidates` DB, **not** in `metrics:quant:*`, so the integer
  surface under-counts `evaluated` (S2: by exactly 4). S3 has **no preserved Redis metrics
  snapshot**, so its `126 − 18 − 10 − 1 − 3 = 94` display gap **cannot be closed** to an exact
  integer (`candidate_reconciliation.md` S3). S2, which *did* capture the counter family + both
  lane logs, closed to residual 0.
- **Impact:** post-hoc funnel reconciliation is impossible without ad-hoc log forensics; the
  dashboard "Quant published / Candidates" tile is a comingled Original+Experimental figure
  mis-readable as Active-V2.
- **Uncertainty:** low on cause; the S3 numeric residual is genuinely **UNRESOLVED**.
- **Proposed acceptance check:** `metrics:<date>:quant:*` keys are lane-suffixed (or Experimental
  uses an `exp:` namespace); THROTTLE/COOLDOWN/revalidation have their own counters; for any
  session, `evaluated == Σ(terminal dispositions)` closes from the integer surface alone; a
  per-session snapshot of these counters is written into the session evidence dir at EOD.

### D7 — Long-term / heads-up sends missing from `last_telegram_push` telemetry · P3
- **Evidence:** `dispatch_audit.long_term_alerts` id 7/8 have `telegram_sent = 1` +
  `telegram_sent_at` 2026-09-10T20:30:4xZ, but `dispatch_audit.last_telegram_push` newest row is
  ORCL `long_term` `2026-09-09T06:58Z`. The S3 08:45Z ORCL earnings heads-up is likewise absent.
- **Impact:** a telemetry consumer reading `last_telegram_push` for "last delivery time"
  under-reports; the authoritative record is `long_term_alerts.telegram_sent_at`.
- **Uncertainty:** low.
- **Proposed acceptance check:** every successful Telegram push (intraday, long-term, heads-up)
  writes a `last_telegram_push` row; a test sends a long-term alert and asserts the row appears.

---

## Contradictions / corrections found during export

### C1 — CORRECTION to the Day-3 EOD report: the "3 quant publications" are Experimental, not "unresolved / transient"
- The Day-3 `EOD_SESSION_REPORT.md` / `CANDIDATE_RECONCILIATION.md` classified the S3 mid-session
  "Quant publications 3" as **UNRESOLVED — a transient in-memory counter with no persisted
  counterpart**.
- **Preserved evidence now shows** `exp_alerts.db.directional_alerts` contains **exactly 3
  `WOULD_PASS` Experimental directional alerts before the 16:24:25Z ping cutoff**: SHOP BEARISH
  14:28:42Z, BLSH BEARISH 15:22:13Z, SKHY BEARISH 16:10:20Z. Combined with the S2-proven fact
  that `metrics:quant:*` is comingled Original+Experimental with no lane suffix, and that on S2
  **all** "published" were Experimental, the identity is established: **the S3 "3 publications" =
  those 3 Experimental `WOULD_PASS` directional signals**, published on the isolated `talonx:exp:*`
  channel — which is why "Brain received 0 / Dispatch received 0 / Telegram pushed 0". No Original
  publication, no V2 publication, no signal lost.
- Confidence: **HIGH** (exact count match + established comingling). It is **not** labelled
  dedup-suppressed (no evidence of that). The residual **94** is still UNRESOLVED (no S3 Redis
  metrics snapshot).

### C2 — LT7 vs LT8: material update of one event, not a duplicate and not two events
- Both `dispatch_audit.long_term_alerts` id 7 and id 8 carry `is_earnings_related = 1` and derive
  from the **same** ORCL 8-K Item 2.02, accession **`0001193125-26-387905`** (ingested 20:30:41Z).
  Distinct outbox IDs (`9db24f03…`, `e004cc42…`), sent 3 s apart (20:30:46.594Z, 20:30:49.719Z).
- Content differs in the **fair-value estimate**: LT7 `intrinsic_fair_value = 175.00`
  (`previous_fair_value` NULL); LT8 `intrinsic_fair_value = 165.00`, `previous_fair_value = 175.00`,
  MoS 12.6 % → 7.3 %. Same qualitative findings (backlog $638B / +363 %, $67B AI contracts,
  F-Score 7/9).
- **Classification: material update / re-evaluation of the same event** — LT8 supersedes LT7's
  fair value. Not an exact duplicate; not a distinct event. Whether emitting both to Telegram
  (rather than one edited/superseding message) is desired is a **product question**, not proven a
  defect.

### C3 — Oracle alerts across S1–S3
| session | long-term ORCL alert | trigger | fair value | delivered |
|---|---|---|---|---|
| S1 2026-09-08 | none in `long_term_alerts` (ids 1–5 not preserved; `last_telegram_push` shows none for S1) | — | — | — |
| S2 2026-09-09 | `#LT6` `hold_quality` (info), 06:58:34Z | ORCL 8-K earnings re-read 06:58:26Z | 175.00 (MoS ~7.1 %) | SENT (API), outbox `6a111f52…` |
| S3 2026-09-10 | `#LT7` 20:30:46Z, `#LT8` 20:30:49Z | ORCL 8-K Item 2.02 acc. `0001193125-26-387905` | LT7 175.00 (MoS 12.6 %); LT8 **165.00** (MoS 7.3 %) | both SENT (API) |
- ORCL recurs as a long-term subject on all sessions where evidence exists. The S2 `#LT6` and the
  S3 `#LT7` both cite fair value **175.00** — S3 `#LT8` is the first downward revision (→165.00).
  S2 `#LT6` (`previous_fair_value` NULL) and S3 `#LT7` (`previous_fair_value` NULL) both present as
  "new", i.e. the store did not carry S2's 175.00 forward as S3's baseline — a minor
  **content-lineage gap** (each session's first ORCL alert looks like a first-ever assessment).

### C4 — Shutdown completeness differed between S2 and S3 (not a regression — S3 was cleaner)
- **S2** canonical close (`eod_close_20260909T201230Z`): supervisor / companion / checkpoint
  daemon stopped, but `residual_talonx_processes` still listed `dashboard_web.py`,
  `talonx_signals.run`, `run_talonx.py` — a follow-up `post_eod_cleanup_20260909T202954Z` reaped
  them.
- **S3** canonical close: `residual_talonx_processes: []`, `shutdown_clean: true`, all 14 PIDs
  gone, ports free, no respawn — verified independently.
- Not a contradiction in outcome (both sessions ended fully stopped), but the S2 close's
  ownership-aware reap did **not** cover base-stack grandchildren in one pass. Worth a
  **regression check**: `prospective close` reaps the whole owned process tree (supervisor +
  its children) in a single bounded pass. Track as **D4-adjacent** (same family as the
  startup/ownership plumbing).

### C5 — `known_non_filer` labels are application classifications, not verified issuer facts
- `watchlist_scope.csv` marks BABA, BLSH, SKHY, SPCX `NOT_SEC_COVERED` with the reason carrying
  the application's `known_non_filer`-style rationale. These are **not independently verified** —
  they are the resolver's disposition. The audit does not assert as fact that (e.g.) BABA never
  files a Form 4; only that the resolver excluded it from the SEC-covered set. Any downstream use
  must re-verify before treating a name as permanently out of scope.

---

## Must-fix ranking for the next step (bounded delivery/dashboard/accounting fixes)

1. **D4** (+ C4) — false NO-GO / incomplete shutdown reap → real risk of a double stack.
2. **D5** — product decision + backlog triage before any "Intelligence delivery enabled" claim.
3. **D6** — lane-suffix the quant counters + persist an EOD metrics snapshot so the funnel closes.
4. **D1 / D2 / D3 / D7** — operator-clarity, no capital-safety impact.
