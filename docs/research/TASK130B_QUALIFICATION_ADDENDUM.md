# Task 130B — qualification addendum (frozen before any corrected return)

Written and committed BEFORE `research/scripts/task130b_durable_replay.py`
is run against the full 626-name population and BEFORE any corrected
economic figure is computed. Task 130 and Task 130A artifacts are
preserved unchanged (not deleted, not overwritten in place). The prior
+2.0219% result (Task 130A) remains **conditional evidence, not a
number this task is trying to reproduce.**

## Status carried in

`PASS_FOR_INTEGRATION_REVIEW` (Task 130A) is **UNDER REVIEW**, not
withdrawn and not reaffirmed, pending this task's repair. Integration
remains HOLD. Production remains paused (Task 129/its implementing
closure task).

## Exact defects this addendum repairs

1. **Identity reconciliation used a "60-day-grace" date-range
   heuristic** (Task 130A, `task130a_identity_and_stats.py`): for each
   of the 35 ambiguous symbols, ANY issuer-CIK whose Form 4 filings
   fell within 60 calendar days of the traded episode's own filing
   window was treated as a plausible match, without recovering the
   EXACT constituent records that actually formed the winning
   2-distinct-owner cluster. This is a coarse proxy, not proof.
2. **A latent CIK string-padding bug inflated the heuristic's own
   apparent ambiguity**: `"701985"` and `"0000701985"` (the same CIK,
   different zero-padding) were counted as two distinct issuers for
   symbol LB. Not previously corrected in Task 130A's own script.
3. **State was in-memory only** (Task 130A, dataclass-based `State`):
   every intent, position, reservation, and cooldown lived in one
   Python process's object graph for the life of one script run. No
   crash/restart/duplicate-effect behavior was ever exercisable,
   because nothing was ever persisted transactionally to disk between
   ticks. This is a genuine, previously-disclosed limitation (Task
   130A's own acceptance document said so) — not merely a style
   choice.
4. **Event ordering was correct in intent (Task 130A's repair already
   fixed "close proceeds cannot fund the same morning's open" in
   principle) but was never expressed as explicit, separately-testable
   session phases** — there was no structural guarantee that
   post-close-detected same-day filing information could not leak into
   that same morning's entry evaluation, only a comment describing the
   intended order.
5. **Missing-price handling was not bounded/retried** — Task 130A's
   driver treated a missing entry bar as an immediate
   `SKIPPED_NO_ENTRY_BAR` / reservation release, rather than a
   provisional, retried state within an explicit reconciliation
   window (this repair adds `ENTRY_PRICE_RECONCILIATION_MAX_SESSIONS`,
   symmetric to the existing 5-session exit fall-forward).
6. **No genuine restart/failure-path tests existed.** Task 130A's own
   9 fixture tests exercised only single, uninterrupted, in-memory
   runs.

## What is NOT changed

Same hypothesis (`INSIDER_BUY_CLUSTER_V2@1`), same evaluation window
(2024-09-01 → 2026-03-31, with an added explicit settlement tail — see
below), same Discovery Universe v1 population (626 names, from Task
118D's `population_manifest.json`, reused verbatim), same signal
thresholds (≥2 distinct Code-P owners / 10-trading-day cluster
window, liquidity gate `median_dollar_volume ≥ $5,000,000` AND
`last_close ≥ $5.00` over a trailing 20-session causal window), same
holding period (+10 trading sessions, ≤5-session fall-forward), same
economic thresholds (mean net > +0.50%/round trip after 20bps; 95%
issuer-block bootstrap lower bound > 0). **This is qualification
repair — fixing HOW durability, identity, and event ordering are
tested and enforced, not what the contract is.** No parameter or
issuer-subset search is performed.

## New, disclosed characteristic of the frozen `cluster_engine`

While constructing this repair's own failure-path tests, direct
inspection of the unmodified `detect_episodes_for_issuer` (via a
minimal, reproducible script — not inferred) established a real
behavior of the FROZEN, already-deployed production clustering
algorithm that was not previously documented in this research program:

> The greedy window scan (`while j < n and (ords[j]-start_ord) <=
> cluster_window_trading_days`) advances `j` across the ENTIRE
> 10-trading-day window from the FIRST record's filing date, even
> though the episode itself only "fires" (and its constituent records
> are attributed) at the 2nd-distinct-owner activation point, which
> can occur earlier in that same window. After firing, the algorithm
> resumes scanning from `i = j` — i.e. from the END of the whole
> scanned window, not from the record immediately after activation.
> Any subsequent, otherwise-independent filings that happen to fall
> inside that same 10-session window (even if they arrive AFTER the
> episode already activated) are silently consumed into the already-
> fired window and never form a second episode.

Concretely verified: four synthetic records for one issuer — two
owners filing 2024-08-14/08-15 (10 trading days apart from a third
filer), and two more owners filing 2024-09-03 — produce **exactly one**
episode (activation 2024-08-15, using only the first two owners) when
all four fall within one 10-session window from the first record; the
09-03 filings are discarded entirely, never becoming their own
episode. When the second pair is moved further out (2024-09-03, 13
trading-day-ordinals from the first record — see
`tests/test_task130b_durable_replay.py::test_cold_start_rejection_does_not_arm_cooldown_or_block_later_valid_episode`),
two genuinely separate episodes are produced.

**This is a real, in-scope-frozen characteristic of the production
`talonx_v2.cluster_engine` (fingerprint `11107198c5b81237`), not a
defect this task is authorized to fix** (no algorithm/parameter
change is in scope). It is recorded here as a disclosed limitation of
the discovery/episode-formation step itself: additional legitimate,
independent insider-buying signal on the same issuer arriving within
10 trading sessions of an already-fired cluster can be silently
dropped rather than forming its own tradeable episode. This affects
population coverage (fewer episodes than a naive "every 2-owner
window" count would suggest), not any already-admitted trade's
identity or pricing. It does not invalidate Part 2/3's identity
findings for the 8 traded ambiguous symbols, which trace the exact
constituent records of episodes that DID fire.

## Identity evidence requirements (Part 2/3 basis)

For every traded, ambiguous symbol, identity evidence is recovered
by RE-RUNNING the unmodified `detect_episodes_for_issuer` against that
symbol's own Form 4 records and matching each trade's own
`eligible_entry_session` to the specific episode that produced it —
never by a CIK/date-range proxy. The recovered episode's exact
constituent records (`accession`, `issuer_cik`, `owner_cik`,
`filing_date`, `code`, `shares`, `price`, `form_type`,
`is_amendment`) are the evidence chain. CIK values are normalized
(`_norm_cik`) before any equality comparison, closing defect #2 above.
Where more than one issuer CIK could plausibly correspond to a
traded symbol across the study window (e.g. a corporate rename, a
ticker reused by an unrelated company, or two entities filing under
the same ticker), **all** competing identities are enumerated from the
symbol's own filing history, not just the one nearest the trade date;
resolution is then stated explicitly per symbol (see Part 3 report).
A shared issuer CIK across constituent records is treated as
necessary evidence of issuer identity — it is NOT, by itself, treated
as proof that the historical price series represents the exact
security purchased, since the dataset carries no security/share-class
title field (a disclosed data limitation, not silently worked
around).

## Durable state transitions and transaction boundaries

`talonx_v2.store.V2Store` (unmodified import, existing schema) is
reused on an explicitly isolated SQLite path per run — no new
persistence architecture is introduced. A PENDING row in the existing
`pending_entry_intents` table IS the reservation; there is no separate
reservation ledger. Every state-changing operation below is a single
committed SQLite write (or, where multiple fields must change
together, a single method call that performs them under one
connection/commit):

- **Intent creation = reservation**: `upsert_entry_intent` is
  idempotent (a second call for the same `episode_id` returns the
  existing row unchanged) and, once committed, is immediately visible
  to a fresh `V2Store` connection against the same file.
- **Reservation consumption = position creation**: `phase_open`
  performs `set_cash(cash - ALLOCATION)`, `insert_open_position(...)`,
  and `mark_entry_intent(intent_id, "FILLED")` in sequence; a position
  is never created without its cash debit, and an intent is never
  marked FILLED without a corresponding position row (verified by
  `test_interrupted_entry_transition_is_idempotent_no_duplicate_position`
  — re-running `phase_open` for an already-FILLED intent is a no-op).
- **Expiry/cancellation = reservation release**: cooldown-blocked,
  symbol-already-open, and price-boundary-exhausted intents are each
  marked to a distinct terminal status
  (`EXPIRED_COOLDOWN`/`EXPIRED_SYMBOL_OPEN`/`EXPIRED_NO_PRICE`) and
  simultaneously dropped from `pending_entry_intents()` (status-driven
  membership) — releasing the reservation exactly once.
- **Exit settlement = cash credit + cooldown + position close**:
  `phase_close` calls `close_position(...)`, `set_cash(cash +
  proceeds)`, `append_trade(...)`, and `set_cooldown(...)` in
  sequence for each due exit.

No committed reservation is ever left without its originating intent
row (the intent row IS the reservation), no cash debit is ever left
without a corresponding position row, and no credited exit is ever
left without a settled (CLOSED) position — enforced by construction
(single-writer, sequential phase execution) and exercised directly by
the Part 6 failure-path tests below.

## Explicit simulated session phases (repairs defect #4)

Each simulated trading session (`as_of`) now runs four, explicitly
separated phases, in this fixed order:

1. **OPEN** — resolve entries for episodes whose PENDING intent was
   created on a STRICTLY EARLIER session's POST-CLOSE phase. Consumes
   cash/slots; commits positions.
2. **CLOSE** — settle due exits (scheduled +10td or fall-forward) at
   this session's own close; retry any pending missing-price entry
   reconciliation within its bounded window.
3. **POST-CLOSE** — only now are this session's OWN filings/records
   ingested, new episodes detected, and new PENDING intents (for a
   FUTURE eligible-entry session) created.
4. **MARK** — daily mark-to-market of every still-open position.

Because today's own filing information is not ingested until AFTER
today's OPEN phase has already run, it is structurally impossible for
same-day filing information to reserve capacity retroactively before
that day's own morning entries — this is enforced by phase ORDER, not
merely by a comment, and is exercised directly by
`test_same_session_close_proceeds_cannot_fund_that_mornings_open`
(repaired in this task to seed a genuinely open position rather than
rely on natural cluster formation, per the task's own instruction) and
by the general OPEN-before-CLOSE-before-POST-CLOSE structure.

**Date-only filings remain assumed session-level available** (the
research parquet carries no intraday dissemination timestamp) — this
is the SAME convention every V2 task in this program has used, stated
explicitly as an assumption. This is an OFFLINE, ideal-price
replay: entry/exit prices are the security's own historical
open/close bars, not a live, delayed quote feed. This offline
assumption is qualified by fixture tests (missing-price
reconciliation, below) rather than silently claimed equivalent to a
live, delayed-data production run.

## Missing-price / reservation policy (repairs defect #5)

A missing or provisional entry reference price on a timely intent's
own target entry session does NOT immediately expire it. The intent
remains PENDING and is retried at each subsequent session's OPEN phase
for up to `ENTRY_PRICE_RECONCILIATION_MAX_SESSIONS = 5` sessions
(symmetric to the existing exit fall-forward). Retries are idempotent
(re-attempting an already-FILLED or already-terminal intent is a
no-op). If the boundary is exceeded with no valid price ever observed,
the intent is expired and its reservation released **exactly once**
(`EXPIRED_NO_PRICE`). No later open, current, or invented price is
ever substituted, and no retrospective entry is ever created for an
episode that lacked a timely PENDING intent — historical ingestion
alone (detecting an episode after the fact) can never, by itself,
create a campaign trade; only a durable PENDING intent created before
the target entry session can.

## Study-window versus settlement-tail boundary

No new eligible-entry session is admitted after **2026-03-31** (the
study cutoff, unchanged from Task 130/130A — this is also where the
underlying daily-bar dataset ends). A `SETTLEMENT_TAIL_SESSIONS = 20`
trading-session tail follows the cutoff, during which ONLY
previously-admitted obligations (already-open positions' scheduled
exits, and any missing-price reconciliation already in flight before
cutoff) are processed — no new POST-CLOSE episode detection or intent
creation occurs once `as_of` passes the study cutoff. Equity and open
positions AT the study cutoff are reported separately from the state
after the tail completes (`STUDY_CUTOFF_REACHED` audit event records
cutoff-moment equity/open-position count independent of subsequent
tail settlement). Drawdown is reported over the study window and,
separately, over the tail-inclusive series; the drawdown series
includes starting equity as its first observation.

## Original versus supplemental concentration tests

The ORIGINAL, already-frozen trade-COUNT-ranked issuer-removal test
(Task 130's own convention) is preserved unchanged. The SUPPLEMENTAL,
clearly-labelled P&L-CONTRIBUTION-ranked removal test (Task 130A's
addition) is preserved unchanged alongside it — neither is
substituted for the other, and neither is selected after seeing which
definition "passes."

## Acceptance requirements (unchanged, restated)

Primary: mean net return per closed round trip > +0.50% after 20bps.
Statistical: 95% issuer-block bootstrap lower bound > 0. Time-
dependence: date-block (monthly) bootstrap must AGREE (both exclude
zero) under the same conservative disagreement rule. Top-issuer-
removal sensitivity (both original count-ranked and supplemental
P&L-ranked) is diagnostic, reported, never used to select a
population. No single calendar half-year may be the sole source of a
positive result — 2026H1's negative reading stays visible, period
boundaries are not moved or excluded.

**An economic pass alone does not close missing identity, durability,
or valuation evidence.** The final verdict (Task130B's own acceptance
document) reports SEPARATE verdicts for identity/security-price
integrity, historical economics, durable prospective lifecycle,
missing-price/restart behavior, and valuation/window accounting — no
single number collapses these. Numerical equality with Task 130A's
+2.0219% is not evidence of implementation equivalence and is not a
target; every material difference in the per-episode comparison (Part
9) is explained on its own terms.
