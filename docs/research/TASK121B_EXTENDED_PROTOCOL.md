# Task 121B Part 3 — frozen extended protocol

Written and committed BEFORE the extended/continuous replay was executed
against real outcomes (only the diagnostic hang-reproduction run, on a
DIFFERENT 2-week window chosen purely for speed, had been inspected at
the time this was frozen — no economic outcome from Segment A's
remainder informed anything below).

## 1. Exact window, verified from source

`results/task93_alpha_foundation/canonical_dataset_manifest.json`,
`segments.A_broad`: `start: "2025-01-24"`, `end: "2025-08-14"` (both
values as stored in the manifest; treated as **inclusive calendar
dates** — confirmed by direct row inspection: the loaded frame's last
timestamp for a `2025-08-14` inclusive filter is `2025-08-14 23:59:00+00:00`,
consistent with inclusive-both-ends).

**Frozen replay window: `2025-01-24` (inclusive) → `2025-08-14`
(inclusive)** — the full, exact Segment A_broad, all 35 symbols. No
partial-month or results-driven boundary selection.

## 2. Continuity — rerun from the start, not a stitched campaign

No complete checkpoint (indicator buffers, pending candidates,
per-symbol cooldown/loss-lockout expiry, global throttle state) exists
from the first-month run (Task 121A) — only its FINAL ledger snapshot
was salvaged. Per this task's own instruction, the first month is
**not** resumed; the full window above is run as **one continuous
replay from its own start**, using the corrected contract/adapter
(`research/scripts/task121b_reliable_replay.py`). The already-published
first-month figures (Task 121A / `TASK121B_FIRST_MONTH_RECONCILIATION.md`)
remain a valid, independently-verified reference point for comparison,
NOT a component stitched into this run's own portfolio.

## 3. Data exposure already inspected

100% of Segment A_broad has already been inspected by this research
program: the first month specifically by Task 121A (Experimental
contract), and the FULL span (2025-01-24→2025-08-14, all 35 symbols) by
Task 93 for the Original contract. **This extension is explicitly NOT an
untouched holdout** — restated per this task's own explicit instruction,
not merely inherited from Task 121's own equivalent disclosure.

## 4. Primary estimand

Net economics (dollar and percentage) of the frozen `EXPERIMENTAL_RELAXED_V1`
contract, under its documented, now-verified PRODUCTION-POLICY simulation
(signal-bar-close entry, `check_exits`-sampled stop/target-only exit, no
EOD flatten, no bearish-close) — i.e. the same contract and lifecycle
Task 121A proved parity for, extended to the full available window.

## 5. Costs and execution assumptions (predeclared, unchanged from
   Task 121A — restated here for a single point of reference)

- Spread: `apply_spread(price, 5.0, side)`, `ExperimentalPaperEngine`'s
  real default — ~5bps round-trip at an unchanged reference price
  (2.5bps/side), verified by a worked test. The ONLY modeled cost.
- Commissions/fees: **not modeled** (deliberate, documented, unchanged).
- Position sizing: fixed $2,500/trade, $100,000 starting cash, one
  position per symbol.
- Entry price: the signal's own bar close (immediate fill) — the
  PRIMARY, production-policy reference.
- Exit price: `check_stop_take`-sampled against each subsequent bar's
  own close (the finest causal granularity this 1-min dataset offers) —
  labelled, per Task 121A, as a disclosed proxy for live's continuous-tick
  sampling, not claimed identical to it.

## 6. Primary metrics and uncertainty method

Same convention as Task 121/121A (continuity across this research
thread, not a new choice made after seeing outcomes): closed trades,
distinct issuers, win rate, average win/loss, profit factor, net
expectancy (mean $/trade and % ), total net $ P&L, ending
cash + marked open-position value = equity, trade-event cash curve
(explicitly NOT a continuous daily mark-to-market — that would require
pulling a daily bar for every holding-period day of every position,
out of this task's bound, same disclosed limitation as Task 120B).

**Uncertainty**: issuer-block bootstrap, 5,000 reps, **seed 121121**
(the SAME seed Task 121A already used — reused deliberately for
comparability across the two runs on the same underlying contract, not
re-rolled after seeing this run's own outcome), 95% percentile CI on
net $/trade. Effective independent-group count = distinct issuers,
reported explicitly, never implied equal to N.

## 7. Predeclared sensitivities

1. **Execution-realism REPRICING sensitivity (Part 5)** — one predefined
   alternative fill model: entry at the **NEXT available bar's own
   close** (roughly a 1-minute order-submission-latency proxy) instead
   of the signal's own bar close, holding the SAME stop_price/
   target_price (both are ATR/pivot-derived from the signal's own
   geometry, independent of the realized entry price) and the SAME
   recorded exit price/reason — i.e. the exit trigger is NOT
   re-evaluated against the delayed entry timing. Computed post-hoc from
   the SAME already-loaded bar-close lookup (no second ~10-hour
   backtest) — shares/dollar P&L are genuinely recomputed from the
   delayed price (not a constant subtracted from the primary number),
   and a trade is DROPPED from this sensitivity's population (flagged,
   not silently kept) if the delayed fill would fall outside the
   signal's own stop/target bracket. **Precision, added after this
   protocol's own results were reported (Task 122 correction): this is
   a per-trade REPRICING sensitivity, not a fully chronologically-
   propagated alternative portfolio simulation** — it does not
   re-derive whether a delayed fill would have changed occupancy/
   cooldown state for later candidates. Label it accordingly in any
   summary of these results.
2. **Drop-top-1-issuer** (by trade count) — both means published,
   neither silently substituted.
3. **Time/period concentration** — trades-per-month table and a
   split-half (first half vs. second half of the window, by trade
   sequence) net-expectancy comparison, to surface whether any result is
   driven by one contiguous stretch.

No threshold grid, no new signal family, no post-hoc loser removal.

## 8. Practical economic materiality threshold (justified before
   outcomes)

The modeled cost is 5bps round-trip on a $2,500 notional = **$1.25 modeled
cost per trade**. A plausible ADDITIONAL real-world friction this replay
does NOT model (commissions, market-impact on size, wider realized
spread during volatility) is conservatively bounded at **another ~5bps**
($1.25/trade) — doubling the total assumed friction is a standard
conservative multiplier for going from a modeled-cost backtest to a
live-cost expectation, not a number chosen after seeing this run's
result. **An effect is called practically meaningful only if the 95% CI
does not merely exclude zero, but excludes a band of ±$1.25/trade
(one full additional assumed-friction unit) around zero** — i.e. the
CI's near-zero bound must clear the plausible extra-cost margin, not
just clear zero by an infinitesimal amount. This bar is set now, before
this run's own CI is known.

## 9. Fixed stopping date and decision rule

This is run **once**, to the full window in §1, with no re-extension
regardless of interim results (per this task's own explicit prohibition
on "automatic repeat with a larger window until significance appears" —
Segment A_broad's own end (2025-08-14) is itself the natural stopping
point; Segment B is a DIFFERENT, 10-symbol, differently-sourced dataset,
not a drop-in continuation, and extending into it is explicitly out of
this task's scope).

- **`ADVANCE_TO_FURTHER_VALIDATION`**: 95% CI clears the ±$1.25/trade
  materiality band (§8) in the POSITIVE direction, AND the execution-
  realism sensitivity (§7.1) does not reverse the sign, AND no single
  issuer or contiguous time period drives the entire result (§7.2/7.3).
  All four required together.
- **`REJECT_CURRENT_CONTRACT_FOR_PRODUCT_USE`**: 95% CI clears the
  materiality band in the NEGATIVE direction, OR frequency (already
  established as adequate in Task 121A) collapses over the extended
  window for a specific, named reason.
- **`INSUFFICIENT_EVIDENCE_WITH_SPECIFIC_BLOCKER`**: the CI does not
  clear the materiality band in either direction (including a CI that
  excludes zero but stays inside ±$1.25/trade — an interval spanning or
  hugging zero is NOT reframed as proof of a near-zero edge, per this
  task's own explicit instruction) — the exact residual uncertainty and
  whether resolving it is worth further effort within the existing
  roadmap is stated, not a generic "run it again."

---
Frozen 2026-09-12, before `research/scripts/task121b_reliable_replay.py`'s
full-window run was executed against real outcomes.
