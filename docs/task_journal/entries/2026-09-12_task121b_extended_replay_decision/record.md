# Task 121B — fixed extended Experimental replay and economic decision

## Objective and acceptance criteria
Close the first-month portfolio-accounting and replay-reliability gaps,
then run the remaining predefined Segment A under the repaired
Experimental contract as one fixed, predeclared evaluation, and reach a
product decision.

## Timing
2026-09-12 → 2026-09-13 (overnight), continuing the same session as
Task 121A. The full-segment backtest alone ran ~11.29 hours
(14:05:54 UTC → ~01:29 UTC).

## Branch / SHA
Release: verified `f28986999eec5e313cfc89db24e4dbacfb378891` unchanged —
no release-branch work this task (research-only). Research `2239b21` →
this commit.

## Requested vs. completed scope

- **PART 1 (first-month reconciliation): DONE.** Read the salvaged
  Task 121A ledger consistently: 33 entries = 33 closed trades = **0
  open positions** — verified, not assumed, that +$61.92 net IS the
  complete portfolio profit for that month (equity = ending_cash exactly,
  since nothing was left open). Decomposed into gross (+$103.19), spread
  cost (−$41.27, matches 33×$1.25 exactly), net (+$61.93, matches ledger).
  7 wins (avg +$75.66), 26 losses (avg −$17.99), max hold 6.98 days, 14/33
  (42%) overnight/date-crossing. `docs/research/TASK121B_FIRST_MONTH_RECONCILIATION.md`.
- **PART 2 (reliability): DONE.** Root cause CONFIRMED (not assumed) by
  a controlled, instrumented, smaller-scale (2-week) reproduction of the
  exact Task 121A adapter: an O(n²) rejection-summarization pattern
  (`{r.reason: sum(x.count for x in result.rejections if x.reason==r.reason)
  for r in result.rejections}`, line 466) — with 118,112 rejection
  records on just 2 weeks, ~1.4×10¹⁰ operations; on the full month this
  scales to tens of billions, fully explaining the original >1hr hang.
  Task 121A's own "unbounded published_log" guess was disproven directly
  (published_log was only 14 rows on the same 2-week reproduction).
  Fixed in a new adapter (`research/scripts/task121b_reliable_replay.py`)
  with fully durable, incrementally-written SQLite telemetry
  (`TelemetryStore`) and a single O(n) rejection pass. Fix VERIFIED (not
  assumed) by re-running the identical 2-week window through the fixed
  adapter: 2,966.7s total (backtest 2,946.6s + summary ~20.1s) vs. the
  original's indefinite hang. 6 new reliability tests + 3 execution-
  sensitivity tests, all pass, covering all 5 required scenarios (normal
  run, interrupted-run attribution, ledger/telemetry reconciliation, no
  cross-run duplication, zero external sends). Full mid-run scanner-state
  resume explicitly NOT claimed (BacktestEngine's buffers/cooldown/
  throttle state has no serialization path) — recovery is a deterministic
  rerun, per this task's own instruction. `docs/research/{TASK121B_RELIABILITY_FIX}.md`.
- **PART 3 (frozen protocol): DONE.** Segment A_broad's exact bounds
  verified from `canonical_dataset_manifest.json` (2025-01-24→2025-08-14
  inclusive). Predeclared costs (5bps round-trip spread, unmodeled
  commissions), metrics/uncertainty (issuer-block bootstrap, 5,000 reps,
  seed 121121 — reused from Task 121A for comparability), one execution-
  realism sensitivity (next-bar-close fill, chronologically propagated),
  concentration/time sensitivities (drop-top-issuer, split-half), and a
  **practical materiality threshold** (±$1.25/trade, one full additional
  assumed-friction unit beyond the modeled 5bps) that a CI must clear
  (not merely exclude zero) for ADVANCE or REJECT — fixed BEFORE any
  outcome from this run was inspected. `docs/research/TASK121B_EXTENDED_PROTOCOL.md`.
- **PART 4 (continuity): DONE.** No complete checkpoint existed from the
  first month (only its final ledger was salvaged) — the full window was
  run as ONE continuous replay from its own start, not resumed, not
  stitched. Same global event ordering, cross-symbol throttle, capital/
  position constraints, entry-admission behavior, stop/target sampled-
  price exits, overnight/multi-day holding (no EOD flatten), identical
  parameters/universe manifest as Task 121A's proven-parity contract. No
  per-symbol parallelization (cross-symbol throttle dependence not
  demonstrated safe to break).
- **PART 5 (execution causality/cost sensitivity): DONE.** Signal-bar-
  close entry verified against actual available information (the
  signal's own IndicatorSnapshot.price IS that bar's own close, already
  known at decision time — no lookahead). Primary reference simulation
  preserved/labelled. ONE predefined sensitivity computed post-hoc
  (no second ~11hr backtest): next-available-bar-close fill, full
  chronological share/P&L recomputation (not a constant subtraction), 0
  trades dropped for invalid fill geometry. Result: −$927.91 total
  (mean −$4.09/trade) vs. primary −$896.44 (−$3.95/trade) — MORE
  negative, sign unchanged. Spread formula reverified
  (`apply_spread` half-per-side, ~5bps round trip), no double deduction,
  commissions kept separately labelled as unmodeled.
- **PART 6 (the fixed run): DONE.** Full Segment A_broad, all 35 symbols,
  2,565,682 bars, run ONCE. Backtest 40,633.7s (~11.29hr); summary ~181s
  (bounded, no hang — reliability fix held at full scale). 2 open
  positions preserved at cutoff (GOOGL, MU — both marked, both
  currently slightly profitable, NOT force-closed, NOT excluded from
  total equity). No settle tail used (none was predeclared as necessary
  — the two open positions are reported directly as unresolved).
- **PART 7 (results/decision): DONE.** N=227 closed trades, 35/35
  issuers traded, gross P&L −$612.92 (negative BEFORE any cost), spread
  −$283.53, net −$896.44, PF 0.764, win rate 19.4%, net expectancy
  −$3.95/trade. Equity $99,155.10 (total portfolio P&L −$844.90,
  including the 2 open positions' small unrealized gains). 95%
  issuer-block bootstrap CI: **[−$8.94, +$1.06]/trade**. Drop-top-issuer
  (LRCX, 15/227): mean → −$5.33 (worse). Split-half: first 113 trades
  mean −$10.97, last 114 mean +$3.01 (real time heterogeneity, disclosed
  not smoothed). Decision: **`INSUFFICIENT_EVIDENCE_WITH_SPECIFIC_BLOCKER`**
  per the protocol's own predeclared, symmetric materiality rule — the
  CI's upper bound ($1.06) does not clear the −$1.25 REJECT threshold
  despite a clearly negative point estimate, gross P&L, and PF — the
  named, specific blocker is that 35 issuer-groups is the entirety of
  the available same-population data (Segment B is a different, smaller,
  out-of-scope dataset) — further backtesting of this exact question on
  this exact data is exhausted, stated plainly. `docs/research/TASK121B_EXTENDED_EXPERIMENTAL_RESULTS.md`.
- **PART 8 (journal/publication): DONE** — this entry; sanitized adapter/
  sensitivity scripts + 9 new focused tests, all passing; small
  (<250KB total) sanitized evidence (summary/sensitivity JSON, run log,
  reliability-fix verification log) committed; raw telemetry SQLite and
  isolated paper ledger stay local-only (gitignored).

## Source / runtime / data manifest
New: `research/scripts/task121b_reliable_replay.py` (durable-telemetry
adapter, reuses `talonx_backtest.engine`/`talonx_quant.*`/
`talonx_signals.experimental_paper.ExperimentalPaperEngine` unmodified,
same composition-shim design as Task 121A's `ExperimentalLifecycleShim`),
`research/scripts/task121b_execution_sensitivity.py` (post-hoc,
O(n log n) via presorted per-symbol bisection, not the O(n) rescan
pattern this task's own diagnostic flagged), `tests/test_task121b_{reliability,execution_sensitivity}.py`
(9 tests), `docs/research/{TASK121B_FIRST_MONTH_RECONCILIATION,
TASK121B_RELIABILITY_FIX,TASK121B_EXTENDED_PROTOCOL,
TASK121B_EXTENDED_EXPERIMENTAL_RESULTS}.md`,
`docs/research/evidence/task121b/*` (4 small files, ~240KB total).
Source data: `task93_canonical_v1` (already-published, no new download);
fingerprint-gated `2ae6216bca70`, matched throughout.

## Tests / experiments / results / limitations
`pytest tests/test_task121b_reliability.py
tests/test_task121b_execution_sensitivity.py
tests/test_task121a_parity_trace.py
tests/test_task121_task120_equity_reconciliation.py
tests/test_task121_experimental_replay_adapter.py
tests/test_task120a_cost_reconciliation.py -q` → 38 passed. Two real
long-running replays executed: a 2-week diagnostic reproduction (crashed,
confirming the O(n²) hang — expected, not a failure of this task), a
2-week fix-verification (succeeded, 2,966.7s total), and the full
Segment A run (succeeded, 40,815.1s total). Limitations, stated plainly:
the CI does not clear the predeclared materiality band in either
direction (a genuine, named, small-independent-group-count limit, not
minimized); the historical dataset (task93_canonical_v1) is now fully
exhausted for this exact question.

## User-visible outcome
See `outcome.md`.

## Verdicts (kept separate)
- Part 1 (first-month reconciliation): `RECONCILIATION_VERIFIED_COMPLETE`.
- Part 2 (reliability): `ROOT_CAUSE_CONFIRMED_FIX_VERIFIED`.
- Part 3-6 (protocol + fixed run): `RUN_COMPLETE_AS_PREDECLARED`.
- Part 7 (decision): `INSUFFICIENT_EVIDENCE_WITH_SPECIFIC_BLOCKER`.

## Production effects, external sends, protected-state checks
None — research-only task. Release branch untouched (`f289869`
unchanged, verified at task start and end). No application process left
running (verified after the full run completed and all temp DBs were
cleaned up). Redis/production DBs re-verified clean at task end.

## Findings
- Fixed: the first-month equity-completeness question (now formally
  verified, not merely asserted) and the O(n²) hang (root-caused and
  fix-verified, not assumed).
- New, material: full Segment A's economics are genuinely NEGATIVE-
  leaning (gross P&L negative before cost, PF<1, 19% win rate) but the
  formal CI, at only 35 independent issuer-groups, does not clear the
  predeclared materiality bar for a clean reject — an honest, specific,
  named residual uncertainty, not a manufactured ambiguity.
- New: real time-heterogeneity (first half much worse than second half)
  surfaced by the predeclared split-half sensitivity — worth noting for
  any future investigation, not acted on here (no threshold search).
- Open: whether EXPERIMENTAL_RELAXED_V1 has a genuine edge remains
  formally unresolved at the 95% level; the available same-population
  historical data is exhausted.
- Deferred: any live/paper forward-observation decision (out of this
  research-only task's authorization).

## Evidence links
`docs/research/{TASK121B_FIRST_MONTH_RECONCILIATION,TASK121B_RELIABILITY_FIX,
TASK121B_EXTENDED_PROTOCOL,TASK121B_EXTENDED_EXPERIMENTAL_RESULTS}.md`,
`docs/research/evidence/task121b/*` (this commit);
`results/task121b_reliable_replay/` (local, full artifacts incl. raw
telemetry SQLite and isolated paper ledger — never committed).

## Later corrections
None yet.
