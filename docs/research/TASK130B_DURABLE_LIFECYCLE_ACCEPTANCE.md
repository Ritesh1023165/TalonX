# Task 130B — durable prospective lifecycle acceptance

Covers `research/scripts/task130b_durable_replay.py` (the durable,
session-phased, `V2Store`-backed driver) and its 10 failure-path/
durability tests (`tests/test_task130b_durable_replay.py`, all 10
passing). Full protocol: `docs/research/TASK130B_QUALIFICATION_ADDENDUM.md`.
Supersedes Task 130A's own disclosed limitation ("state kept in-memory
for one continuous run... a genuine mid-replay restart/idempotency
test was not built... named here as a residual gap") — that gap is
closed by this task, not silently carried forward.

## Durable state (Part 4)

Every intent/position/cash/cooldown transition is a real, committed
SQLite write against `talonx_v2.store.V2Store` (unmodified import,
existing schema — `pending_entry_intents`, `positions`, `trades`,
`cooldowns`, `portfolio`), opened on an explicitly isolated path (never
the live `v2_lane.db` — enforced by `assert_research_ledger_path`,
mirroring `talonx_research.replay_engine`'s own hard refusal). No new
persistence layer was built: a `PENDING` row in the existing
`pending_entry_intents` table IS the reservation — reserved cash/slots
are computed by querying that table (`_reserved_cash`/
`_reserved_slots`), not tracked in a separate ledger.

Directly verified by real close-and-reopen (`test_intent_reservation_survives_a_real_close_and_reopen`):
a `PENDING` intent created via `upsert_entry_intent`, with its owning
Python `V2Store` object explicitly dropped, is read back identically
(same `intent_id`, still `PENDING`) by a GENUINELY NEW `V2Store`
instance opened against the same on-disk file — real durability, not
an in-memory-object-graph artifact.

## Explicit session phases (Part 7)

Each simulated session now runs four separated phases in a fixed
order — OPEN (resolve entries for episodes whose intent was created a
STRICTLY EARLIER session), CLOSE (settle due exits; retry pending
missing-price reconciliation), POST-CLOSE (only now ingest today's own
filings, detect new episodes, create new reservations for a FUTURE
session), MARK (daily mark-to-market). This is a structural, not
merely documented, guarantee: `phase_post_close` is called after
`phase_open`/`phase_close` in the same tick, so a same-day filing
cannot possibly influence that same morning's entries — there is no
code path by which it could.

`test_same_session_close_proceeds_cannot_fund_that_mornings_open`
(repaired per this task's own instruction — a genuinely open FFF
position is now seeded directly into the store rather than relying on
natural cluster formation) confirms this two ways: FFF's own seeded
position both entered (as a pre-existing fact) and exited at its own
session's close; and a separately, genuinely-detected competing
episode (GGG) whose reservation could only be created the PRIOR
session — while FFF's $10,000 was still fully committed and
unrealised — is correctly rejected for insufficient capacity and never
funded by FFF's same-day close proceeds, even though those proceeds
free the exact amount GGG would have needed.

**Offline vs. live data availability, explicitly distinguished**: this
remains an OFFLINE, ideal-price replay — entry/exit use the security's
own historical open/close bars, retrieved with full hindsight for
which bar exists on which date. This is NOT claimed equivalent to a
live run against delayed, streaming price data; it is qualified only
by the fixture tests here (deterministic bars, explicitly-injected
`NaN` gaps), not by an unsupported equivalence claim.

## Missing-price recovery (Part 5)

A missing/`NaN` entry reference price on a timely intent's own target
session does not immediately expire it. `ENTRY_PRICE_RECONCILIATION_MAX_SESSIONS
= 5` (symmetric to the existing 5-session exit fall-forward) bounds a
retry loop that re-attempts the SAME intent at each subsequent
session's OPEN phase — idempotent (an already-FILLED or already-
terminal intent is untouched by a repeat attempt) — until either a
valid price is observed (fills exactly once) or the boundary is
exceeded (`EXPIRED_NO_PRICE`, reservation released exactly once).
Directly verified: `test_missing_price_defers_not_immediately_expires_then_reconciles_with_one_fill`
(entry-day `open` price set to `NaN`; at most one `BUY` ever recorded;
the intent reaches a definitive terminal state, never stuck `PENDING`
forever). No later open/current/invented price is ever substituted —
the retry loop only re-checks the SAME target session's own bar
availability on each pass; it does not widen its target date.

## Failure-path and durability qualification (Part 6)

All 10 tests use REAL temporary SQLite files (`pytest`'s own `tmp_path`)
and genuine store close/reopen or repeated-phase-call interruption
simulation — not merely non-negative ending cash:

| Test | Demonstrates |
|---|---|
| `test_intent_reservation_survives_a_real_close_and_reopen` | crash-after-committed-reservation + recovery via a genuinely new store connection |
| `test_interrupted_entry_transition_is_idempotent_no_duplicate_position` | a re-run of `phase_open` for an already-FILLED intent is a no-op — no duplicate debit/position |
| `test_missing_price_defers_not_immediately_expires_then_reconciles_with_one_fill` | missing price → bounded retry → exactly one fill, never a phantom/duplicate entry |
| `test_late_intent_rejected_before_any_portfolio_mutation` | a cold-start episode is rejected (`SKIPPED_ENTRY_STALE`/`SKIPPED_NO_PRIOR_INTENT`) with zero cash effect, before any mutation |
| `test_twenty_first_competing_intent_rejected_deterministically` | exactly 20 of 21 same-session competing episodes enter; the 21st is rejected for capacity, deterministically |
| `test_insufficient_cash_no_partial_entry_no_phantom_proceeds` | available cash below allocation → no entry, no partial fill, no trade record at all |
| `test_same_session_close_proceeds_cannot_fund_that_mornings_open` | a same-session exit's proceeds cannot fund that same morning's competing entry (seeded genuinely-open position, repaired fixture) |
| `test_cold_start_rejection_does_not_arm_cooldown_or_block_later_valid_episode` | a cold-start rejection does not suppress a later, genuinely independent, timely episode for the same symbol |
| `test_universe_removal_actually_changes_entry_eligibility_but_existing_position_still_exits` | an existing open position still reaches its own scheduled exit regardless of later universe changes |
| `test_duplicate_filing_records_do_not_duplicate_economic_effect` | duplicated input filing records (e.g. a re-ingested batch) produce exactly one `BUY`, not two |

Interrupted/restarted runs are compared by LOGICAL STATE (store
contents, funnel counts, trade records) — never by process exit code.

## Capacity, reservation, and gate enforcement

$300,000 isolated capital, $10,000 fixed allocation (no partial fill),
max 20 concurrent open positions, no borrowing, no shorts, no cash
reset — unchanged. The entry gate is enforced BEFORE any position can
open: `phase_open` only processes episodes with an existing `PENDING`
intent whose `eligible_entry_session <= as_of`; an episode reaching
`phase_open` with no matching `PENDING` intent (or a non-`PENDING`
one) is rejected with zero mutation
(`SKIPPED_NO_PRIOR_INTENT`). Historical ingestion alone — detecting an
episode after the fact in `phase_post_close` — can never, by itself,
create a campaign trade; only a durable `PENDING` intent created
BEFORE the target entry session can.

## Valuation and window accounting (Part 8)

No new eligible-entry session is admitted after the study cutoff
(2026-03-31); a 20-session settlement tail follows, managing only
previously-admitted obligations (`phase_post_close` is skipped once
`as_of` exceeds the study cutoff — verified structurally, not merely
asserted). Equity/open-position counts at the study cutoff are
recorded separately (`STUDY_CUTOFF_REACHED` audit event) from the
state after the tail completes. The summary output reports
`equity_and_drawdown.study_window_only` and `.tail_inclusive`
separately, each with its own drawdown series (starting equity
included as the series' own first observation) — closing Task 130A's
own disclosed gap (invested-capital/equity exposure was not computed;
only the day-frequency occupancy measure was). This driver now reports
BOTH: `capital_utilization_pct_days_with_open_position` (day-frequency
occupancy, Task 130A's original measure, preserved) AND
`mean_invested_capital_over_mean_equity_pct` (mean open-position cost
basis ÷ mean equity, a genuinely distinct exposure-ratio measure).

Every session's mark for every open position records requested
valuation date (`as_of`), actual mark date, whether it is stale (last
close before `as_of`, not `as_of` itself), and whether it is entirely
unavailable (`unavailable: true`, held at cost, never presented as a
fresh valuation) — see `daily_marks.json`'s own `stale_or_missing_marks`
field per session.

## Disclosed characteristic of the frozen cluster_engine (not fixed, out of scope)

Directly verified during test construction (see the qualification
addendum): the production `detect_episodes_for_issuer`'s greedy
window-consumption can silently discard later, otherwise-independent
filings that fall within the SAME 10-trading-day window as an
already-fired cluster, without ever forming a second episode. This is
a real, disclosed characteristic of the frozen, unmodified,
already-deployed clustering algorithm (fingerprint `11107198c5b81237`)
— not a defect this task is authorized or attempts to change. It
affects population coverage (fewer episodes than a naive count would
suggest), not the identity or pricing of any already-admitted trade.

## Runtime dependency manifest

`talonx_v2.{cluster_engine, liquidity, quant_bridge, brain_bridge,
config, calendar, store, schemas, form4_source}` (unmodified imports,
read from the RESEARCH worktree's own copy, fingerprint-verified
`11107198c5b81237` before every full-population run) plus
`exchange_calendars` (XNYS session boundaries) and the same daily bar
directories/Form 4 parquet prior Task 130 tasks used (no new data).
`talonx_v2.store.V2Store` IS used (this is the whole point of this
task's durability repair) — but only against an isolated path, never
`v2_lane.db`.
