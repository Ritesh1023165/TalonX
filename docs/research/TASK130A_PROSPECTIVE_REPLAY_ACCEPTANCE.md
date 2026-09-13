# Task 130A — prospective-replay implementation acceptance

Covers `research/scripts/task130a_prospective_replay.py` (the corrected,
in-line-gated driver) and its 9 focused tests
(`tests/test_task130a_prospective_replay.py`, all passing before the
real run). Full protocol: `docs/research/TASK130A_REPAIR_PROTOCOL.md`.

## Prospective-eligibility enforcement (Part 2)

The entry gate is now INSIDE the session loop, before any capacity/
cash mutation: for every ripe episode, `intent is None or intent.status
!= "PENDING" or intent.created_session >= eligible_entry_session` →
`SKIPPED_NO_PRIOR_INTENT`, with **zero** cash/slot effect. A durable
`PENDING` intent is only created on the ONE tick strictly before the
target entry session (matching the episode/issuer/target session
1:1 by construction — keyed by `episode_id`), and immediately reserves
$10,000 cash + 1 slot — released only on consumption (FILLED) or
expiry (`EXPIRED_STALE`/`EXPIRED_COOLDOWN`/`EXPIRED_SYMBOL_OPEN`/
`EXPIRED_NO_PRICE`). An intent that would only exist AFTER its own
deadline cannot occur by construction (the creation window is `as_of <
eligible_entry_session <= next_session(as_of)` — a session strictly
before the deadline, never after).

Preserved unchanged: the causal 45-day catch-up window; second-owner
activation and duplicate/amendment dedup (`cluster_engine.detect_episodes`,
unmodified import); the existing `MAX_ENTRY_STALENESS_SESSIONS=3`
staleness rule; the 5-session re-entry cooldown; existing-position
exits (the exit-settlement pass is independent of entry-scope
eligibility — verified by test); delayed reconciliation of a timely
intent (a `PENDING` intent's reservation survives until its own entry
tick, whenever that is, without being re-created or duplicated).

## Simulated clock (Part 3)

Every timing concept is tracked at SESSION granularity, using the real
XNYS calendar (`exchange_calendars`) for session boundaries and
`talonx_v2.calendar.add_sessions`/`next_session_strictly_after`
(unmodified imports) for all date arithmetic — no intraday timestamp is
manufactured anywhere. Six timestamp-complete scenarios are directly
tested: timely intent → entry (`test_timely_intent_admits_entry_and_moves_cash`);
missing/cold-start intent → rejection, zero cash effect
(`test_cold_start_episode_creates_no_position_and_no_cash_change`); a
rejected cold-start does not arm cooldown or suppress a later valid
episode for the same symbol
(`test_cold_start_rejection_does_not_arm_cooldown_or_block_later_episode`);
capacity exhaustion at the 21st competing position
(`test_twenty_first_position_rejected_for_insufficient_slots`);
insufficient available cash (`test_insufficient_cash_creates_no_partial_fill_and_no_later_proceeds`);
existing-position exit independent of entry-scope removal
(`test_existing_position_exits_even_if_symbol_removed_from_future_candidates`).
**Scope limitation, disclosed**: this driver keeps state in-memory for
one continuous run (no incremental persistence / restart-from-midpoint
capability) — a deliberate, bounded choice for a single-pass ~10-second
research replay, not full production-grade durability; a genuine
mid-replay restart/idempotency test was not built (out of this task's
remaining budget) and is named here as a residual gap, not silently
assumed equivalent to Task 130's SQLite-ledger-based approach.

## Capacity, reservations, and event order (Part 4)

$300,000 isolated capital, $10,000 FIXED allocation (verified —
`test_insufficient_cash_creates_no_partial_fill_and_no_later_proceeds`:
available cash below $10,000 produces `SKIPPED_INSUFFICIENT_CAPITAL`,
never a smaller spend), max 20 concurrent (verified —
`test_twenty_first_position_rejected_for_insufficient_slots`: exactly
20 of 21 competing same-tick episodes enter, in deterministic
`(eligible_entry_session, issuer_cik, symbol)` order). Entries are
resolved before that same session's exits are credited
(`test_same_session_exit_proceeds_do_not_fund_that_mornings_entry`) —
a same-day exit's proceeds cannot fund that morning's entry. A missing
entry price releases the reservation without letting a same-session
competitor jump the now-fixed deterministic order.

## Phantom-exit fix (Part 5)

Task 130's `open_notional.pop(episode_id, allocation)` fallback is
**removed entirely** — this driver tracks real `OpenPosition` objects
in a dict; an exit can only ever settle a position that structurally
exists in `state.open_positions` (Python `KeyError`/`del` on a missing
key would raise, not silently default). `test_existing_position_exits_even_if_symbol_removed_from_future_candidates`
and `test_cost_reconciles_exactly_once_per_closed_trade` confirm every
closed trade traces to one real entry with the correct notional/shares
(`shares = ALLOCATION / entry_price`, not an assumed constant) and
exactly one 20bps cost application.

## Daily marked equity (Part 6)

Every session in the replay range (not only entry/exit event dates)
marks every open position at its symbol's own last available CLOSE
on/before that session (never a future price) — `test_unrealized_decline_appears_in_daily_marked_drawdown`
confirms a declining, still-OPEN position's unrealized loss appears in
the daily series before any exit realizes it. Reported per session:
cash, reserved cash, open-position cost basis, marked value, unrealized
P&L, cumulative realized P&L, equity, open/reserved counts, and any
stale marks (a symbol with no available close that day — held at cost,
flagged in `stale_marks`, never defaulted to zero or silently dropped).
**Capital utilization, precisely defined**: `capacity_utilization_pct_days_with_open_position`
= % of replay sessions with ≥1 open position (a FREQUENCY measure);
this is explicitly NOT the same as invested-capital/equity exposure
(average $ deployed ÷ average equity) — both are distinct and neither
substitutes for the other; only the frequency measure is reported this
task (the exposure-ratio measure is a residual, disclosed gap).

## Runtime dependency manifest

`talonx_v2.{cluster_engine, liquidity, quant_bridge, brain_bridge,
config, calendar, form4_source}` (unmodified imports, read from the
RESEARCH worktree's own copy, fingerprint-verified `11107198c5b81237`
before every run) plus `exchange_calendars` (XNYS session boundaries)
and the same daily bar directories/Form 4 parquet Task 130 used (no
new data). `talonx_v2.store`/`talonx_v2.paper` (the PERMISSIVE
production ledger/entry logic) are explicitly NOT used by this driver
— replaced by this task's own explicit, isolated, testable state
machine, per the repair protocol's own "isolated replay path" design.
