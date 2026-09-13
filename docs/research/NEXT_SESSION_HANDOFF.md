# Next-session handoff (finalized 2026-09-11, updated 2026-09-13 / Task129 pause + TalonX closure)

> **2026-09-13 update (Task 129 + this closure task): RESEARCH AND
> APPLICATION ACTIVATION ARE PAUSED.** Programme decision
> `PAUSE_ALPHA_RESEARCH_UNDER_CURRENT_CONSTRAINTS` —
> `docs/research/TASK129_RESEARCH_PROGRAM_DECISION.md` +
> `TASK129_EVIDENCE_MATRIX.csv`. No supported profitable-alert
> candidate exists on the live-configured population; V2's
> configured-scope evidence remains genuinely `INCONCLUSIVE` (not
> rejected). **No production process is currently running** (verified
> read-only this task, timestamp below) — the "Startup / warmup
> recovery procedure" and "Candidate release" sections below describe
> HOW to restart if and when a resumption decision is made; they are
> reference material, not a scheduled or implied next action. **Do not
> restart the application from this document alone** — restart
> requires the same explicit resumption decision Task 129 and this
> closure task both describe below, not merely reading this handoff.

**Do not launch the next session automatically — this is a handoff
document, not a scheduler. No GO is declared here; GO/NO-GO is a
preflight-time decision made only after an explicit resumption
decision (see "Resumption conditions" below), not at arbitrary read
time.**

> **2026-09-12 update (Task119A/120)**: the candidate SHA changed from
> `5c0b3f3` to `f289869` — a dashboard-only integration (Task 119 +
> Task 119A's corrections: one Paper/EOD destination, truthful cost
> labels, a real exchange-calendar session boundary). **No strategy,
> threshold, scope, sizing, holding-period, or V2 fingerprint change** —
> verified: `talonx_v2/` and the fingerprint-defining module have a
> literal zero-line diff between `5c0b3f3` and `f289869`. This candidate
> has NOT been runtime-validated live (no application session was started
> this task) — the go/no-go conditions below still govern, unchanged in
> substance, just against the new SHA.

## Candidate release for the next session

- **SHA**: `f28986999eec5e313cfc89db24e4dbacfb378891` (`f289869`) — integrates Task 119 (`d65a410`) +
  Task 119A's corrections on top. Strategy-code-identical to `5c0b3f3`
  (Task 118F's deployment); only `dashboard_web.py`,
  `dashboard_web_static/index.html`, `talonx_ops/dashboard_read.py`,
  `talonx_ops/paper_performance.py` (new), and
  `talonx_signals/market_sessions.py` (+1 function) changed.
- **Effective configuration**: V2 fingerprint `11107198c5b81237`
  (unchanged, re-verified this task), 39-name `resolved-active-watchlist`
  execution scope, 45-day lookback, `composite-yf` pricing, official
  V2/Intelligence Telegram delivery enabled, Experimental external
  delivery OFF, `--tick-seconds 150 --heartbeat-seconds 30`.
- **Env vars required before `start`**: `TALONX_INTEL_DELIVER_CARDS=1`,
  `TALONX_INTEL_DRY_RUN_DELIVERY=0`, `TALONX_INTEL_DELIVER_PER_CYCLE=20`,
  `TALONX_INTEL_DELIVER_TIMEOUT_SECONDS=20`,
  `TALONX_INTEL_DELIVER_DIGEST_INTERVAL_SECONDS=21600`,
  `TALONX_INTEL_DELIVER_AGE_CUTOFF=1`.
- **New this candidate**: the `:8787` cockpit's "Paper / EOD" tab now
  shows per-lane realized/unrealized P&L, equity, and arithmetic
  reconciliation (folded in from Task 119/119A); the "Active V2" tab's
  $300,000 campaign ledger card gains the same for V2. No new tab, no new
  env var, no new dependency.

## Startup / warmup recovery procedure and readiness checks

1. `python -m talonx_ops.prospective preflight --expected-sha f28986999eec5e313cfc89db24e4dbacfb378891`
   — all 17 gates must read `[OK]`.
2. `python -m talonx_ops.prospective start ...` (same flags as today,
   §Candidate release above).
3. Watch `original.log` for `Initial Quant preseed complete: N/43` then,
   **only if N<43**, `Bounded preseed recovery sweep complete: R/M ...`.
4. **Per-symbol unsupported-data handling**: any symbol still not-ready
   after the sweep is reported explicitly (never silently treated as
   ready) and is expected to close via ordinary live accumulation during
   the session — if a symbol remains persistently not-ready across
   multiple sessions, that is new evidence worth a fresh, bounded
   investigation (not covered by today's fix, which is a one-shot
   startup sweep only).
5. Verify readiness independently against `quant.db.bar_buffer`
   (≥120 1-minute bars), not the log summary alone.

## Open-position and pending-notification obligations

**Re-verified read-only 2026-09-13T09:40Z (this closure task), directly
against the authoritative SQLite ledgers — not copied from any prior
report:**

- **Experimental: SPCX remains open**, position identifier `SPCX`
  (`~/.talonx/experimental/experimental_paper.db`, table `positions`):
  **16.865960067130683 shares**, entry price **$148.22755360794068**,
  entry timestamp **2026-09-10T19:29:45.777729+00:00**, cost basis
  $2,500.00, existing exit policy **stop $144.6133321126302 / target
  $152.06332906087238** (unchanged since entry — resolves under this
  existing policy on its own next qualifying tick once the application
  is restarted; no manual action taken or implied here).
  - **Last stored mark / valuation provenance (corrected 2026-09-13,
    handoff-correction task)**: The inspected ledger mark table is
    empty. Earlier September 11 reports recorded a historical
    reference mark of $151.21 at 20:08 UTC. Its provenance has not
    been reconciled with this ledger inspection. It is not a current
    valuation. The earlier reports are preserved, not deleted — this
    is not an assertion that the historical mark was fabricated, and
    it is not an assertion that its underlying source has now been
    verified; the two observations (empty ledger mark table vs. an
    earlier-reported $151.21 mark) simply have not been reconciled.
  - **Monitoring-gap timestamp (corrected 2026-09-13, handoff-correction
    task)**: Earlier EOD evidence places canonical shutdown after
    20:09 UTC on September 11. The stored activity timestamp
    (2026-09-11T08:59:27-04:00, the most recent ledger row of any
    kind) and that shutdown timestamp describe different observations
    — the stored-activity timestamp does not by itself establish when
    the application or exit evaluation actually stopped. The exact
    last SPCX exit evaluation is unresolved. Uninterrupted evaluation
    before shutdown is not inferred from either timestamp alone.
  - **Exit evaluation for SPCX is currently INACTIVE/unavailable**
    because no application process is running (verified this task —
    see "Application state" below) — this is an observation gap, not
    a resolved or flattened position. **A future restart must disclose
    this gap explicitly** and follow the existing recovery/stale-check
    policy on its own next qualifying tick — it must NOT claim
    uninterrupted monitoring across this gap, and must NOT fabricate
    or back-fill a closing fill for any time during the gap.
- **V2**: re-verified read-only this task directly against
  `v2_lane.db` (`positions` table: 0 rows; `portfolio` table: cash
  $300,000.00 flat) — **0 open positions, no pending entry/exit
  obligations**, confirmed accurate and unchanged. ABCL episode
  `07242bc857569f60` remains terminal (`SKIPPED_ENTRY_STALE`).
- **Intelligence**: not re-queried this task (no open position/ledger
  obligation of this kind exists for the informational lane); 0
  pending cards at last check, carried forward unverified.
- **No other obligation carries over.**

## Feed / exit-evaluation / delivery verification (next session)

- Confirm `talonx:ingest:liveness` key is present, TTL refreshing, and
  `last_market_event_age_seconds` stays low during the regular session.
- Confirm at least one Experimental exit-check log line appears for SPCX
  shortly after open (proves the exit path is live, independent of any
  new entry).
- Confirm Intelligence `card_delivery.messages_sent_today` (not just
  `sent_today`) if any new digest fires.

## Canonical EOD procedure (unchanged)

`python -m talonx_ops.prospective close`, at/after the verified XNYS
close for that session, target completion within 90 minutes. Verify
`base_reconciliation.mismatches == []` and clean shutdown (`psutil` pid
check + port check + `redis.ping()`), exactly as done today.

## Known limitations (carried forward)

- Heartbeat-lapse locus (Task 118C) — unresolved.
- Historical "45 candidates" counter source — unresolved.
- SHOP has no local daily-bar price coverage in the frozen research
  dataset (research-replay-only; irrelevant to live trading). **Task 120
  update**: 5 more live-scope names share this gap — ABCL, ACHR, ADC,
  AGNC, and (materially) MSTR — meaning no historical replay of the
  39-name scope to date has been fully representative of the live-traded
  population. Named as the smallest next evidence-acquisition task above.
- The bounded recovery sweep is startup-only — a mid-session bulk
  provider failure has no automatic recovery (explicit, known gap).

## Explicit go/no-go conditions for next start

**GO** if: preflight all-`[OK]`, no live prior stack detected, V2 ledger
continuity confirmed, Redis reachable, **AND an explicit resumption
decision has been made** (see below — a passing preflight alone is
never sufficient while the programme is paused). **NO-GO / investigate
first** if: any preflight gate fails, a competing writer is detected,
the V2 ledger fingerprint/md5 differs unexpectedly from this session's
final state, **or no resumption decision has been made yet.** **This
decision is made at next-session preflight time, not here — and is
gated on the resumption decision below, not on this document alone.**

## Next market session

Not scheduled. The prior text ("Monday 2026-09-14") described a launch
that did not proceed — **application activation is paused** (Task 129)
and no next session is currently planned. When a resumption decision
is made, `talonx_v2.calendar.is_session` remains the correct way to
identify the next actual trading session at that time.

## Application state as of this closure task (2026-09-13T09:40:01Z, read-only)

- Release `f28986999eec5e313cfc89db24e4dbacfb378891` and research
  `e0d26bde41d6691bee30c73576b999c3aa9b4713` — both verified exactly as
  expected, both worktrees clean.
- **No TalonX process is running**: 0 Python processes of any kind, 0
  listening ports on 8787/8770/8760/8501. Four stale `.run/task99c_*.pid`
  files exist (from an unrelated, much earlier task) — all four PIDs
  checked individually and confirmed NOT running; not a live session.
- Redis reachable (`PING` → True), 0 `talonx:*` keys — read-only,
  nothing modified.
- No ongoing monitoring is implied by this snapshot — it is a
  point-in-time check, not a standing watch.

## Programme decision and resumption conditions (Task 129)

**`PAUSE_ALPHA_RESEARCH_UNDER_CURRENT_CONSTRAINTS`** —
`docs/research/TASK129_RESEARCH_PROGRAM_DECISION.md` +
`docs/research/TASK129_EVIDENCE_MATRIX.csv` (authoritative). No
supported profitable-alert candidate exists on the live-configured
population; this is not a claim that all possible strategies fail, and
paid data is not asserted as a guaranteed fix. Implemented application
capabilities (alerts, paper portfolios, dashboard, long/short-horizon
support) are validated as WORKING SOFTWARE; none of them currently
carry a validated profitable TRADING STRATEGY on the live-configured
scope — V2's own evidence remains genuinely `INCONCLUSIVE`, not
rejected.

**Named resumption conditions (exact, from Task 129 §5)**:
1. An explicit user product decision authorizing a genuine long-hold
   alert type, or accepting non-differentiating calendar-wide alerts —
   would unblock an already-scoped candidate without new data.
2. Authorization for a materially new, paid, or non-price data/feature
   class (e.g. consensus estimates, options) — the specific bar this
   programme's own closure clause already sets.
3. V2's paper ledger accumulating a materially larger sample on its
   already-frozen contract, observed as part of normal, periodic
   product review — **not** a dedicated research task, and **not**
   grounds to resume research on its own without a fresh bounded
   proposal.

**A future resumption proposal must specify** (Task 129 §6, restated):
what new information or capability has become available; which
documented limitation (named in the evidence matrix) it addresses; one
bounded experiment and the specific product decision it would change;
data provenance, cost, acceptance criteria, and an explicit stop
condition; any required authorization. This closure task does **not**
recommend paid data, scope expansion, filter relaxation, or another
candidate — none of those is supported by evidence named here.

## One next research/product action

**None scheduled.** Research and application activation remain paused
pending a concrete resumption decision per the conditions above. The
prior Task 119/119A/120A–C history (dashboard reconciliation delivered;
V2 39-name-scope replay corrected to N=57, net@20bps=−0.85%, 95%
CI=[−4.57%,+1.11%]) remains accurate and is superseded only in the
sense that the whole alpha-research programme it fed into is now
paused — see `docs/research/PRODUCT_STATUS.md` and
`docs/research/TASK129_RESEARCH_PROGRAM_DECISION.md` for the full,
current, authoritative picture.
