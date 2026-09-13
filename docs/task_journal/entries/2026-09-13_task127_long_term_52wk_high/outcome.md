1. **Statistical and product verdicts**: Statistical =
   **`INCONCLUSIVE`** (incremental 95% CI [−6.96%,+0.23%] includes
   zero, upper bound barely positive; 9/12 non-overlapping 6-month
   blocks negative). Product = **`DO_NOT_ADVANCE`** — the added
   tercile-selection complexity is not justified: the no-selection
   benchmark (simply holding the eligible universe) outperformed it
   (+13.70% vs +10.85% net/6mo absolute).

2. **SHAs**: release verified `f28986999eec5e313cfc89db24e4dbacfb378891`
   unchanged (research-only task). Research `7c8bcab` (confirmed
   exact) → **`<this commit>`**, pushed to
   `research/talonx-profitability-2026-09` only. Protocol-freeze
   checkpoint pushed separately as `241887e`.

3. **Product corrections and source-grounded adaptation**: Task 126's
   "no existing multi-month strategy = no authorization" inference
   withdrawn; "ticker-specific differentiation is a hard requirement"
   inference withdrawn (turn-of-month itself remains un-re-evaluated).
   George & Hwang (2004) verified from the primary record: TERCILE
   (not decile) sort on close/252-day-high, monthly formation,
   Jegadeesh-Titman-style overlapping 6-month holds — this task's
   long-only adaptation preserves the ranking construction (tercile
   across the 38-name universe) and the exact published 6-month hold,
   dropping only the short leg (product design: long-only).

4. **Exact signal, holding period, causal execution model**:
   `nearness = close_t / max(close, trailing 252 trading days)`,
   causal. Monthly formation (last trading day of month); entry at the
   OPEN of the first trading day of the FOLLOWING month (never the
   same month-end close); 6-CALENDAR-month hold (source's own headline
   test, unshortened); exit at the open of the first trading day 6
   months after entry. Up to 6 overlapping cohorts concurrently open.

5. **Coverage, costs, and corporate-action limitations**: 38 active-
   covered configured tickers (33 from 2019-06-03, 3 from 2019-01-02,
   2 later-listed from Dec 2020) — today's watchlist projected
   backward, a real, disclosed survivorship limitation, not a true
   point-in-time universe. 5bps round-trip cost (base) + 15bps adverse
   sensitivity, applied once per round trip. `adjustment=all` directly
   verified (not asserted) continuous through the two known 2024
   splits; dividends embedded identically on both strategy and
   benchmark sides, not double-counted.

6. **Absolute and benchmark-relative portfolio economics**: Strategy A
   net +10.85%/6mo (CI [+6.25%,+15.99%], entirely positive) —
   strongly positive but attributable to broad market beta (SPY
   +242.68% over the same window). Benchmark B1 (no selection) net
   +13.70%/6mo — HIGHER than the strategy. Incremental (A−B1):
   −2.846%/6mo, 95% CI [−6.96%,+0.23%].

7. **Uncertainty, concentration, drawdown**: non-overlapping 6-month
   block bootstrap (12 blocks, 5,000 reps, seed 127127) — 68 monthly
   cohorts explicitly NOT treated as 68 independent observations.
   37/38 issuers selected at least once (MCD most at 37, ACHR least at
   2) — broad, not concentration-driven. Chronological $100k
   portfolio's marked-equity max drawdown: −13.43%.

8. **One next action / stop decision**: explicit stop — archive this
   exact contract (negative/inadequate incremental result per the
   frozen criteria). No ranking-fraction, lookback, holding-period, or
   ticker-subset search proposed. Turn-of-month remains separately
   closed and untouched. No candidate in this program currently
   carries an `ADVANCE_TO_FURTHER_VALIDATION` verdict pending action.

9. **Production preservation**: no release-branch change; no
   application process started; Redis `talonx:*` key count 0 both
   before and after.

10. **Journal/reports**: `entries/2026-09-13_task127_long_term_52wk_high/`
    + `docs/research/{TASK127_PRODUCT_CONTRACT_CORRECTIONS,TASK127_FROZEN_LONG_TERM_PROTOCOL,TASK127_LONG_TERM_ECONOMIC_DECISION}.md`
    + `docs/research/evidence/task127/*.json` +
    `research/scripts/task127_52wk_high_evaluation.py` +
    `tests/test_task127_52wk_high_fixture.py` — protocol freeze at
    `241887e`, remainder at this commit, both pushed.

Priority followed as instructed: correct product intent → one frozen
long-term contract → complete economic evaluation → decision, all
completed in this single task. A clean, source-grounded, fully-run
evaluation found the selection mechanism does not add value over
simply holding the eligible universe — reported as a genuine
INCONCLUSIVE/DO_NOT_ADVANCE result, not a product-fit deferral.
