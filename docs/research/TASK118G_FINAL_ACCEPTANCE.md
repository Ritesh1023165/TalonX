# Task 118G — final live acceptance (2026-09-11, checked 16:20–16:22 UTC)

**Verdict: PRE_EOD_ACCEPTANCE_COMPLETE.** Market close is 20:00 UTC (3h38m
away at completion) — this is a verified pre-close acceptance snapshot,
not a claim of monitoring through close.

## Part 1 — warmup acceptance, finished

**Current readiness: 43/43** (live-verified, `quant.db.bar_buffer`).
**NUE**: 142 1-minute bars (latest `2026-09-11T16:20:00Z`, fresh), **and**
genuine subsequent strategy evaluation confirmed — `suppression_counts`
shows `LOW_VOLATILITY: 22` rows for NUE today (real gate evaluation, not
merely a buffer-ready flag). No exact NUE-reaches-120 transition timestamp
was preserved in the log (the recovery sweep left it at 116/120, per
Task 118F's own report, and no further "loaded N bar(s)" completion line
for NUE appears afterward) — **first observed READY is this check's own
timestamp, `2026-09-11T16:20:50Z`; the exact transition is not invented**.
Arithmetically, closing a 4-bar gap at the observed ~1 bar/minute live
rate would put the true crossing around ~15:57Z — stated as an estimate,
not a logged fact.

**No historical alerts, entries, or exits were emitted by preseed or the
recovery sweep** — verified directly: `dispatch_audit.alerts` and
`rejected_candidates` both show **zero** rows in the entire restart/sweep
window (`2026-09-11T15:51:00Z`–`15:53:00Z`).

### Accurate attribution — not all credited to the new sweep

| stage | readiness | source |
|---|---:|---|
| pre-restart (natural accumulation only) | 30/43 | live-tick accumulation since this morning's incident (Task 118A–E) |
| immediately after ordinary startup preseed | **41/43** | the **existing**, unmodified startup preseed — fresh historical fetch on restart, not the new Task 118F code |
| after the bounded recovery sweep | **42/43** | Task 118F's new `run_bounded_recovery_sweep` — directly logged: `1/2 previously not-ready symbol(s) recovered in 2.6s` |
| current (this check) | **43/43** | ordinary subsequent live accumulation (NUE) |

**The sweep is credited with exactly the one symbol its own log line
proves it recovered** — not all 13 symbols that became ready across the
whole restart. This is a **bounded startup recovery sweep**, run once per
process start in the pre-market-data safety window — **not** continuous
mid-session recovery; no such continuous behavior exists in the deployed
code, and none is claimed.

## Part 2 — dated corrections to earlier readiness conclusions

Appended (not rewritten) to the specific documents below — see each file
for the exact inserted text:

- `docs/audits/task118a_priority_hotfixes_2026-09-11/PRIORITY2_ORIGINAL_WARMUP.md`
  (release branch): the provider failure **was** transient (confirmed
  again by Task 118F's real fetch probe); Task 118A correctly found no
  *provider-side* code defect, but did not identify the **application-
  side** defect (the unconditional `_preseeded_1m` marker preventing any
  retry) — that gap is now closed, corrected below with a link to
  Task 118F.
- `docs/research/TASK118E_READINESS_SPCX_DECISION.md` (this branch):
  Task 118E's "no code/config recovery action was taken" decision is
  correct for **that** task's own time budget, but is now superseded —
  Task 118F built, tested, and deployed exactly the recovery mechanism
  Task 118E declined to attempt under time pressure.

## Part 3 — live position and delivery check

**Experimental**: `experimental_paper.db` re-read directly (not the
display log) — **SPCX still open**, unchanged position (16.86596 sh,
entry $148.2276). Fresh mark **$148.6100** (bar `2026-09-11T16:20:00Z`,
~2 min old) → **unrealized +$6.45 (+0.258%)**. Realized total
**reconfirmed exactly −$324.4662160270568** — no new trades since
Task 118F; VRT/STX/AMD/BLSH remain flagged as recovery-affected
(first-live-validation of the Task 118A exit fix), distinct from SPCX
(never affected by any defect — its exit-check path was always correctly
wired, per Task 118E's own trace).

**V2** (independent check): cash $300,000, 0 open positions, tick 13,
`last_tick_utc: 2026-09-11T16:21:22Z` (fresh), `form4_records_seen: 8`
(SEC poll producing data), the same ABCL stale episode id
`07242bc857569f60` (unchanged — no replay), `pending_entry_intents: []`.
Ledger invariants green; fingerprint `11107198c5b81237` unchanged
(confirmed at deployment preflight, Task 118F).

**Delivery, by domain**:

| domain | today | note |
|---|---|---|
| Trading/Original | 0 alerts, 0 pushes | correct — LOW_VOLATILITY-dominated funnel |
| Intelligence | `SENT: 6` card rows = **1** API-acknowledged Telegram message (unchanged, `messages_sent_today: 1`) | **six cards is not six messages** — one aggregated digest, message_id 720, this morning; no new send attempted or needed for this check |
| System-admin | n/a this task | no new smoke test required or sent |
| Experimental | 0 external sends | structural boundary held throughout, including through today's deployment |

No old alert was resent to verify anything in this section.

## Evidence

Live `quant.db`/`dispatch_audit.db`/`experimental_paper.db` reads
(read-only), live `:8787` API reads, `original.log` (release worktree,
read-only) — all this session, checked 16:20–16:22 UTC.
