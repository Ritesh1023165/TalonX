# Task 121A — corrected Experimental replay: results and decision

Supersedes Task 121's economic result (which used an incorrect,
Original-shaped exit lifecycle — see
`docs/research/TASK121A_PROVENANCE_AND_CONTRACT.md`). Contract, harness,
and parity evidence are in that companion document; this document covers
Parts 5-7 (the frozen replay, economics, and decision).

## Part 5 — the frozen replay

**Window** (frozen before any outcome was inspected — chosen purely from
Task 121's own compute-budget note and this task's fresh rate
measurement, see below): `2025-01-24 → 2025-02-22` inclusive
(`[start, end_inclusive]`, both bounds inclusive of the full calendar
day), all 35 `task93_canonical_v1` symbols — **375,628 bars**, 0
data-quality blocking issues, 35/35 symbols covered.

This is the SAME price history Task 93 (Original) and Task 121 (the
one-week Experimental pass) already inspected — **not** an untouched
holdout, stated plainly.

**Runtime**: a fresh rate measurement on THIS adapter (not reused from
Task 121's one-week number, and not a blind re-assertion of Task 121's
own ~2.5hr/month estimate either) — a 2-day smoke test measured ~125
bars/sec. The full month's backtest itself (`BacktestEngine.run()`)
completed in **5,312.8 seconds (~88.5 minutes)**, confirmed by an
in-process timer around the `engine.run()` call, not estimated.

**Completion status — a real, disclosed reliability gap.** The
post-backtest summary-construction step (in `run_replay()`, AFTER
`engine.run()` had already fully returned) hung at 100% CPU for over an
hour past that point, confirmed via repeated `psutil` process inspection
(status `running`, sustained 100% CPU, stable ~884MB RSS — not a crash,
not a deadlock on I/O, an actual runaway computation). The REAL
backtest/ledger computation was already 100% complete and durably
persisted in the isolated SQLite ledger (`ExperimentalPaperEngine`'s own
`trade_history`/`positions`/`portfolio_state` tables) at that point — so
rather than wait indefinitely or discard 88.5 minutes of completed
compute, the stuck process was killed and the ledger was read directly
with a small, separate, **read-only** salvage script
(`docs/research/evidence/task121a/month1_corrected_SALVAGED.json` is
its exact output). **Every economic figure below comes from that real,
completed ledger — none of it is estimated, interpolated, or
re-simulated.**

What was lost: the funnel-level telemetry that lived only in the stuck
process's in-memory `BacktestResult`/`published_log` (raw candidates
generated, fully-qualified publications, per-reason rejection counts,
true per-trade stop-vs-target exit-reason breakdown beyond the coarse
`AlertAction` the SQL ledger itself stores) — this was never written to
disk before the process was killed. **Reported as UNAVAILABLE for this
run, not fabricated or backfilled.**

**Root-cause and fix for future runs**: the likely (not conclusively
proven) cause is `ExperimentalLifecycleShim.open_position`'s
`SKIPPED_POSITION_ALREADY_OPEN` log entry — with no EOD flatten and no
bearish-close (both confirmed-correct per Part 2), a position can stay
open for days while cooldown-bounded candidates keep re-attempting it,
each attempt appending to an unbounded in-memory list. Fixed in the
adapter (a per-symbol cap of 20 detailed entries, then an aggregate
count) for any future longer run — this fix was NOT in effect for this
run (found after the fact), so `skip_already_open_total_by_symbol` is
not available for this specific replay either.

## Part 6 — economics (from the real, completed ledger)

| | |
|---|---:|
| Closed round trips | **33** |
| Distinct issuers | **18** |
| Win rate | **21.2%** (7 winners / 33) |
| Profit factor | **1.13** |
| Net $ P&L (total, $2,500 fixed allocation/trade) | **+$61.92** |
| Net expectancy (mean $/trade) | **+$1.88** |
| Ending cash / equity | **$100,061.92** (0 open positions at window end — genuinely resolved, not force-closed) |
| Holding duration | min 180s (3 min) — max 603,000s (**~6.98 days**) — mean ~74,536s (~20.7 hours) |
| Exit reason (coarse, SQL ledger) | 33/33 `confirmed_bearish` (the ledger's own AlertAction label for BOTH stop_loss and target_exit — see Part 2; the fine-grained split was lost, see above) |
| By-issuer trade counts | AMAT 3, MU 3, LRCX 3, STX 3, AVGO 2, NFLX 2, SBUX 2, KLAC 2, INTC 2, PANW 2, ADI 2, and 7 more issuers with 1 trade each |

**The holding-duration figures are themselves direct, load-bearing
evidence for Part 2's corrected contract**: a maximum hold of ~7 days
and a mean of ~20.7 hours would be IMPOSSIBLE under Task 121's original
(incorrect) 15:50-ET-EOD-flatten assumption — this run's own trade table
independently confirms the corrected no-EOD-flatten, no-bearish-close
lifecycle is what actually produced these results, not merely asserted
from reading the source.

**Uncertainty** (predeclared method, issuer-block bootstrap, 5,000 reps,
seed 121121, 95% percentile CI — same convention as Task 121's own
protocol): **95% CI on net $/trade = [−$12.36, +$16.88] — includes
zero.** Effective independent-group count: 18 issuers (not 33 trades).
Drop-top-1-issuer (AMAT, 3/33 trades) sensitivity: mean moves from
+$1.88 to **+$3.23** (more positive, not less) — does not flip the sign
either direction.

**Frequency**: 33 closed trades in one calendar month is **~220×**
Original's own measured rate (Task 93: ~0.15 trades/month) — frequency is
clearly no longer the binding constraint for this contract, a materially
different finding from Task 121's zero-trade one-week result.

## Part 7 — decision

**`INSUFFICIENT_EVIDENCE_WITH_SPECIFIC_BLOCKER`**

Not a rejection: net expectancy is (mildly) POSITIVE, profit factor is
above 1.0, and the drop-top-1-issuer sensitivity does not flip the sign.
Not an advance: the 95% issuer-block-bootstrap CI **includes zero** —
this task's own predeclared interpretation rule (Task 121's protocol,
reused unmodified here) requires the CI to exclude zero, together with
adequate frequency, for `ADVANCE_TO_FURTHER_VALIDATION`; frequency alone
clearing its bar is not sufficient by itself.

**Exact blocker**: N=33 trades across 18 distinct issuers is not enough
statistical power to resolve the sign of Experimental's net expectancy
under its CORRECTED (now-confirmed-accurate) lifecycle — a materially
different, more information-rich result than Task 121's zero-trade week,
but still short of a decisive CI.

**Smallest resolving action**: extend the SAME frozen adapter/contract
(`research/scripts/task121a_experimental_replay.py`, unmodified logic,
only the window argument changes) to the remaining ~5.7 months of
Segment A. At the confirmed frequency (~33 trades/month), this would
plausibly accumulate on the order of 150-200 more closed trades across a
much larger issuer set — a materially more powerful basis for a CI-based
decision than this one month alone. This is a genuinely informative next
step (not an open-ended "run it again") because it directly targets the
one quantity (statistical power on net expectancy) that is currently the
sole blocker, using a contract and harness already proven correct this
task, not one requiring further methodology repair.

**Product implication if this remains inconclusive at scale**: unlike
Original (which cannot even generate enough trades to be measured),
Experimental's relaxed contract clearly CAN produce a `REGULAR_OPPORTUNITY`-
scale trade population — the remaining open question is purely economic
sign/magnitude, not frequency. This reframes the product question from
"does this contract ever fire" (resolved: yes, decisively) to "is its
edge positive net of the (now-confirmed, correctly-modeled) 5bps spread
cost" (open).
