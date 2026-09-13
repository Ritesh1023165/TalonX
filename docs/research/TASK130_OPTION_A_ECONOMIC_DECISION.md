# Task 130 Part 7/8 — Option A offline evaluation, results, decision, and integration handoff

Runs `research/scripts/task130_discovery_evaluation.py` exactly ONCE,
implementing the contract frozen in
`docs/research/TASK130_FROZEN_EVALUATION_PROTOCOL.md` before any return
was inspected. Full results:
`results/task130_option_a_discovery/task130_evaluation_results.json`
(copied to `docs/research/evidence/task130/`); closed-trade tables in
`closed_trades_track_{A,B}.json`.

## Implementation difference found and fixed during this task

The replay's `trades` table stores `executed_at` as a **real wall-clock
timestamp** (when the replay script happens to run), not the simulated
trading-session date. An early draft of this task's own analysis code
used that field for calendar/time-dependence analysis, which would
have silently collapsed every trade into "today." **Corrected before
any reported result**: this task queries the ledger's own `positions`
table (`entry_session`/`exit_session` columns — the actual simulated
XNYS session dates persisted by `talonx_v2/paper.py`) instead. Fixture
tests were updated to assert the corrected field is used
(`test_closed_trades_use_simulated_session_dates_not_wall_clock`). This
is disclosed here as a genuine implementation correctness issue found
and fixed within this task, not glossed over.

A second issue was found and fixed the same way: the first pass's
Track B "reconstructed equity" reported a −44% to −47% drawdown that
was an artifact of DEPLOYED CAPITAL (up to ~$200k committed to open
positions) being misread as a loss. Corrected to a `realized_equity`
series (cash + open positions marked at cost, never fluctuating until
realized) — the resulting drawdown (§ below) reflects only REALIZED
losses along the way, explicitly disclosed as NOT including
intra-holding unrealized mark-to-market fluctuation (no daily bar
marks are wired into this reconstruction).

## Funnel

| stage | count |
|---|---:|
| Processed episode records (Discovery Universe v1, 626 names, window) | 402 |
| `ENTERED` (qualifying, liquidity-passed, capacity-available) | 157 |
| `SKIPPED_ENTRY_STALE` (backlog at replay cold-start, >3-session-old) | 226 |
| `SKIPPED_CLOSE_*` (liquidity price-floor fail) | 7 |
| `SKIPPED_IN_COOLDOWN_*` (5-session per-issuer cooldown) | 8 |
| `SKIPPED_SYMBOL_ALREADY_OPEN` | 4 |
| Closed trades — **Track A** (historical, all `ENTERED`) | 157 |
| Closed trades — **Track B** (timestamp-proven prospective) | 153 |
| Cold-start entries excluded from Track B | 4 |
| Total `pending_entry_intents` ever created | 162 |
| Open positions at window end | 0 |
| `EXIT_UNRESOLVED` | 0 |

**No capacity exclusion occurred** (`MAX_CONCURRENT_20` never fired) —
minimum cash observed was **$181,392.76** of the $300,000 pool (≈12
positions deployed at peak, well under the 20-slot/$200k-notional
ceiling). The $300k/20-slot capacity constraint was **not binding** in
this specific evaluation — reported explicitly, not implied to have
been meaningfully stress-tested by this particular run.

## Track A — historical, ideal-timing evidence

- N=157 closed trades, 107 distinct issuers.
- Net mean **+1.8305%**/round trip, median +1.5131%, win rate 61.78%,
  PF 1.976.
- Issuer-block bootstrap 95% CI: **[+0.5993%, +3.1245%]** — excludes zero.
- Date-block (19 monthly blocks) bootstrap 95% CI: **[+0.3668%, +3.2799%]** — excludes zero.

## Track B — timestamp-proven prospective-policy evidence (the operative track)

- N=153 closed trades, 106 distinct issuers.
- **Net mean +2.0219%/round trip**, median +1.674%, win rate 62.75%,
  PF 2.1399.
- **Issuer-block bootstrap 95% CI: [+0.7222%, +3.3989%]** — excludes
  zero, entirely positive.
- **Date-block (19 monthly blocks) bootstrap 95% CI: [+0.5723%,
  +3.4573%]** — excludes zero, entirely positive. **Both uncertainty
  methods AGREE** (no disagreement-rule tiebreak needed).
- Top-issuer removal sensitivity (top = by trade count): excl. top-1
  (SPG, 6 trades) → +2.1629%; excl. top-3 → +1.9907%; excl. top-5 →
  +1.9523%. **Sign never reverses, magnitude stays stable** — the
  result is not concentration-driven.
- Concentration: top-1 issuer (SPG) = 3.92% of trades, **−2.78%** of
  net P&L (SPG was a net LOSER despite being the most-traded issuer —
  concentration is not inflating the result).
- Calendar half-year stability: 2024H2 **+4.26%** (n=21), 2025H1
  **+2.72%** (n=47), 2025H2 **+2.09%** (n=52), **2026H1 −0.50%**
  (n=33). **Three of four half-years are independently positive** — the
  result is not driven by a single period. **The most recent half-year
  is negative** — a genuine, disclosed, active-monitoring concern, not
  hidden by the aggregate.

### Track B reconstructed campaign (isolated, $300k, cold-start trades excluded from cash)

- Ending cash / realized equity: **$330,935.40** (total return
  **+10.31%** over the ~19-month window).
- Max drawdown (realized-equity basis, cost-marked open positions):
  **−2.25%** — small, because this basis does not capture intra-holding
  unrealized swings (disclosed limitation, not fabricated precision).
- Min cash observed: $181,392.76 (capacity never binding, above).

### Track C — operational latency

**`UNAVAILABLE_REQUIRES_LIVE_OBSERVATION`** — by definition, no offline
replay can measure real SEC-EDGAR ingestion or delivery latency; not
approximated from historical filing dates.

## Benchmark / market-exposure context (not a gating criterion, per the frozen protocol)

SPY buy-and-hold over the identical window: **+20.28%** total return —
**exceeds Track B's own +10.31% realized-equity return**. This is
reported as context only, exactly as frozen: V2's economic criterion is
a **per-trade expectancy** test (mean net return per round trip),
not a portfolio-level "beat the market" test — this distinction was
fixed in the protocol BEFORE this result was seen, precisely to avoid
the Task 127/128 confusion between a positive per-mechanism signal and
overall portfolio outperformance. V2's capital utilization here is also
partial (≤$200k of $300k, not the ~100% SPY assumes), so the two
totals are not a like-for-like exposure comparison either.

## Coverage/mapping limitations (from the universe manifest, restated)

35 of 626 symbols have an ambiguous CIK mapping (>1 distinct CIK seen);
12 have zero Form 4 coverage in the research parquet (including SHOP,
one of Tier 1's own 39 SEC-resolved names — it contributed 0 trades
here purely from a data gap, not from failing any filter); 1 has zero
daily-price coverage. None of these were silently dropped — all are
named in `docs/research/evidence/task130/universe_manifest_discovery_v1_compact.json`.

## Statistical verdict

> **Track B: CI excludes zero, entirely positive, under BOTH
> predeclared uncertainty methods — `SUPPORTS_PREDECLARED_EFFECT`
> equivalent (primary economic criterion cleared: +2.02% > +0.50%,
> both bootstrap lower bounds > 0, no method disagreement).**

## Economic/integration-review verdict

> **`PASS_FOR_INTEGRATION_REVIEW`**

Applying the frozen criteria (`TASK130_FROZEN_EVALUATION_PROTOCOL.md`
§5) without modification: Track B's primary criterion is met (+2.02%
> +0.50%), both uncertainty methods' lower bounds exceed zero, the
top-1/3/5-issuer-removal sensitivity never reverses sign, and no
single calendar half-year is the sole source of a positive result
(three of four are independently positive). **All four conditions for
`PASS_FOR_INTEGRATION_REVIEW` are met.**

**This is NOT a deployment recommendation.** Per this task's own
explicit framing, `PASS_FOR_INTEGRATION_REVIEW` means a concrete
candidate for a LATER activation-review decision — not live activation,
not a promise this exact result repeats, and not a claim the $300k/
20-slot capacity limit has been meaningfully stress-tested (it was
never binding here). The 2026H1 half-year's negative reading and V2's
underperformance of simple SPY exposure over this window are both
carried forward explicitly, not smoothed over by the aggregate PASS.

**The prior Task 112R headline (+1.01%/10td, 39-name live scope) is
explicitly NOT what produced this PASS** — this result is a materially
different population (626 vs. 39 names), different capacity rule, and
a stricter prospective-intent policy (Track B specifically), evaluated
fresh against its own frozen criteria, as required.

---

## Part 8 — integration handoff (specified because the result passed)

**Design only — nothing in this section is implemented in this task.**
No production ingestion, broad delivery, dashboard redesign, or live
activation occurs here.

### Minimum implementation delta

1. **Discovery manifest refresh**: Discovery Universe v1 (this task's
   626-name manifest) needs a periodic (e.g. weekly) refresh process
   that re-derives membership from the same evidence chain (Task
   116-panel-equivalent ∪ Tier 1's SEC-resolved names) — stale/
   incomplete-coverage behavior: a refresh that cannot verify full
   coverage must FAIL CLOSED to the last-known-good manifest, never
   silently shrink or broaden the universe.
2. **One owned ingestion service** covering after-hours and pre-open
   SEC EDGAR catch-up (the existing `--live-lookback-days 45` window,
   continuously polled) — a single, clearly-owned process, not
   duplicated across lanes.
3. **Shared SEC request budget**: 8 requests/second, shared across ALL
   components that hit SEC EDGAR (existing Form 4 ingestion,
   Intelligence's own EDGAR polling) — a single rate-limit budget, not
   per-component independent limits that could jointly exceed SEC's
   own fair-use expectations.
4. **Durable accession deduplication**, cursor-after-persist (never
   advance a resumption cursor before the corresponding record is
   durably written — matches the existing `_dedupe`/idempotency pattern
   already verified this task in `cluster_engine.py`/`store.py`).
5. **Trading-session-close interaction**: continuous discovery must not
   create a NEW entry intent for a session that has already closed
   without going through the existing next-session-open causal entry
   rule — reuses the existing `entry_offset_sessions=1` mechanic
   unchanged.
6. **Existing-position management is independent of new-entry
   eligibility** — already verified this task (Tier 4 of
   `TASK130_OPTION_A_CONTRACT.md`): `settle_due_exits` never consults
   the execution allowlist.
7. **Independent alert subscription** (Tier 3: `WATCHLIST_ONLY` /
   `BROAD_DISCOVERY`) from paper EXECUTION scope (Tier 4: Discovery
   Universe v1) — two separate config surfaces, never coupled.
8. **Base alerts** contain only verified cluster facts (issuer, the
   ≥2 distinct owners, filing accession links, entry/exit session) —
   no speculative narrative.
9. **Optional, bounded enrichment** (e.g. a short descriptive summary)
   — explicitly NOT a mandatory new LLM integration; the base alert
   must be complete and correct without it.
10. **Lifecycle-specific deduplication** (one alert per episode per
    lifecycle event — INTENT/FILL/EXIT/STALE — matching the existing
    `_enqueue_alert`'s `dedup_key` pattern verified this task) and
    explicit ambiguous-send handling (never silently drop a send whose
    routing outcome is unknown).
11. **Lane counters and existing-dashboard compatibility**: Discovery
    Universe v1 activity must be visibly distinguishable from Tier 1's
    existing 39-name live scope in any shared dashboard view — additive
    counters, not a replacement of the existing V2 lane display.

### Funnel to be surfaced by any integration

`coverage → persisted filings → Code-P records → distinct owners →
clusters → eligibility/staleness → intents → paper dispositions →
delivery outcomes` — exactly the funnel this task's own offline
evaluation reports (§Funnel above), extended with a live delivery-
outcome stage this offline evaluation cannot produce (Track C).

### What remains a genuinely open question for that later activation review

- Whether the $300k/$10k/20-slot capacity rule, never binding here, is
  the right sizing for a broader 626-name universe under real
  (possibly clustered) future signal arrival.
- Whether the 2026H1 half-year's negative reading is noise or an early
  sign of a weakening effect — only resolvable with more elapsed time,
  not invented here.
- The 12-symbol Form 4 coverage gap (including SHOP) and 35-symbol CIK
  ambiguity, both disclosed, neither resolved in this task.

This task does not recommend activation. It recommends only that a
later, separately-authorized integration-review task take up the
above, informed by this evaluation.
