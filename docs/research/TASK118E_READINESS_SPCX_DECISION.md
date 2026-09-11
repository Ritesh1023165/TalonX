# Task 118E — readiness recovery, SPCX freshness, and the research decision (2026-09-11)

Cutoff for the live sections: **2026-09-11T15:22–15:26 UTC** (regular
session, open since 13:30 UTC).

## Part 1/2 — readiness: actual gap and recovery decision

Live snapshot (`quant.db.bar_buffer`, 1-minute, `min_bars_required=120`):
**25/43 ready**, 18 not-ready, ranging 80–111 bars (vs. 24/43 at Task
118D's ~14:55 check, 18/43 at Task 118B/C's earlier checks) — **steady,
continuing, genuine recovery**, not stalled.

| symbol | bars now | bars ~30min earlier | rate (bars/min) | est. bars needed | est. ETA (UTC) |
|---|---:|---:|---:|---:|---|
| BLK | 80 | 64 | ≈0.52 | 40 | ≈16:39 |
| JNJ | 82 | 65 | ≈0.57 | 38 | ≈16:29 |
| ADC, NUE, AFL, MA, PG, ABT, BLSH, IBM, V, C, MCD, ADP, JPM, BAC, KO, UNH | 82–111 | — | not separately re-measured | 9–38 | **before** BLK/JNJ on the same trend |

**Estimate, explicitly labelled uncertain**: this is a linear extrapolation
from two spaced snapshots (~30 min apart), not a guarantee — live-tick
arrival is not exactly one bar per minute (some symbols show gaps). The
**slowest** laggers (BLK, JNJ) are estimated to reach readiness roughly
**60–80 minutes** from this cutoff; the rest sooner.

**No code/config recovery action was taken.** Reasoning: (1) the root
cause (external yfinance bulk-preseed failure) was already established in
Task 118A/B as a provider-side transient, not a TalonX defect; (2) natural
live-tick accumulation is **already working and bounded** (a real,
estimable ETA under 90 minutes for the worst case, not indefinite); (3)
this task's own explicit safety bar for any new recovery mechanism
("historical warmup must not emit retrospective actionable signals or
paper trades, or replay historical exit events into open positions,"
"merge/deduplicate safely without corrupting live buffers") requires
isolated implementation and focused testing that could not be completed
safely in the time available without risking exactly the class of defect
this multi-day investigation has repeatedly found and fixed elsewhere
today. Building and deploying a new, inadequately-tested backfill path
under time pressure was judged a worse outcome than a bounded, already-
in-progress natural recovery with a known ETA. **No readiness requirement
was lowered to report a green status** — 18/43 are honestly reported
not-ready.

Today's `suppression_counts` (live): `LOW_VOLATILITY` across **25**
distinct tickers — exactly the 25 currently-ready symbols, confirming the
18 not-ready symbols have zero suppression rows because they have not
reached evaluation, not because they were evaluated and passed. No claim
of a missed profitable trade is made — no candidate/price evidence was
sought for one.

## Part 3 — SPCX: no defect, a report-snapshot limitation

Traced directly: `quant.db.bar_buffer` shows a **fresh 1-minute bar for
SPCX at 2026-09-11T15:21:00Z** (close $146.93), ≈2 minutes old at the time
of this check — **not** a monitoring gap. The `experimental.log` shows
**continuous** `regime_shadow symbol=SPCX` evaluation roughly every 1–7
minutes through the cutoff, and exactly **one** isolated stale-tick event
(`Experimental exit check for SPCX: stale/invalid tick (age=574s > 300s)
-- leaving position pending, no fill invented`, ≈15:03:53Z) — the
freshness guard (Task 118A's fix) **correctly rejected** that one old
tick rather than filling on it. **Conclusion: Task 118D's reported
25-minute-old SPCX mark was purely a report-snapshot limitation (the
report simply had not been re-fetched since an earlier check) — not an
ongoing routing/consumer/valuation defect.** No fix was needed or applied.

**Current SPCX state** (authoritative `experimental_paper.db.positions`,
unchanged): still open, entry $148.2276, 16.86596 shares. **Fresh
unrealized P&L**: mark $146.9300 (bar timestamp `2026-09-11T15:21:00Z`,
~2 min old at report time) → **≈−$21.88 gross** (−0.88%), superseding
Task 118D's stale −$13.11 figure (both computed the same honest way —
mark minus entry, times shares — just at different, correctly-labelled,
observation times; price moved further against the position in between).
No cost applied (position not closed). Not fabricated — a real,
timestamped, sourced observation.

**Experimental total realized P&L, reconfirmed**: still exactly
**−$324.4662160270568** — no new trades since Task 118D; the four closes
(VRT/STX/AMD/BLSH) remain flagged as first-live-validation of today's
exit-lifecycle fix, kept separate from any claim of established,
multi-cycle strategy validation.

## Part 4 — Task 118D accounting: precise level-by-level reconciliation

Traced from `processed_episodes` (the replay's own disposition ledger),
not re-labelled from memory:

| population | total processed episodes | ENTERED (= eligible + selected) | closed round trips | BUY+SELL rows | exit_unresolved |
|---|---:|---:|---:|---:|---:|
| A | 17 (10 ENTERED, 2 SKIPPED_CLOSE, 5 SKIPPED_ENTRY_STALE) | **10** | **10** | 20 | 0 |
| B | 385 (147 ENTERED, 5 SKIPPED_CLOSE, 221 SKIPPED_ENTRY_STALE, 8 SKIPPED_COOLDOWN, 4 SKIPPED_ALREADY_OPEN) | **147** | **147** | 294 | 0 |
| C | 402 (157 ENTERED, 7 SKIPPED_CLOSE, 226 SKIPPED_ENTRY_STALE, 8 SKIPPED_COOLDOWN, 4 SKIPPED_ALREADY_OPEN) | **157** | **157** | 314 | 0 |

**The reported 10/147/157 are ENTERED episodes, which equal closed round
trips** (every ENTERED episode resolved to exactly one SELL after its
10-day hold — `exit_unresolved: 0` in every population) — **not** "all
evaluated episodes" (that larger figure is the full disposition total:
17/385/402). `C_total(402) = A_total(17) + B_total(385)` **exactly**, and
`C_entered(157) = A_entered(10) + B_entered(147)` **exactly** — confirming
A and B are genuinely disjoint, independently-run populations with no
overlap or leakage, and C is their clean union at every level, not just
the trade-count level already checked in Task 118D.

**Task 116 comparison correction preserved**: the prior 620-name
population and its runtime remain non-interchangeable with C (unchanged
from Task 118D — restated, not re-litigated).

### Predeclared time-dependence sensitivity (new this task)

The issuer-block bootstrap (Task 118D) assumes issuer-repetition is the
dominant dependence structure. **One predeclared alternative** — a
month-of-entry time-block bootstrap (same seed family, 5,000 reps) — was
run to check whether overlapping holding periods / shared market-regime
timing changes the conclusion:

| | A CI95 | B CI95 | A−B difference CI95 |
|---|---|---|---|
| issuer-block (Task 118D) | [−7.06%, +2.64%] | [+0.94%, +3.48%] | **[−9.48%, +0.76%]** (includes zero) |
| **time-block (this task)** | [−10.27%, +1.67%] | [+0.56%, +3.82%] | **[−12.68%, −0.14%]** (excludes zero, marginally) |

**Honest finding: the two dependence assumptions do not agree on
whether the A−B difference is statistically distinguishable from zero**
— issuer-block says marginally inconclusive, time-block says marginally
negative. **This divergence is itself the result**, not resolved in
either direction — it demonstrates the A-vs-B conclusion is **not robust**
across reasonable resampling-unit choices at this sample size, reinforcing
(not contradicting) Task 118D's own caution about A's 6-issuer-block
count. Neither method was chosen after seeing which looked more
favorable — both are reported in full.

## Part 5 — bounded composition check (predeclared before computing)

**Predeclared feature** (see `composition_check.py` docstring, written
before any result): 20-trading-day pre-entry realized volatility
(annualized %, issuer-level, first-entry date, strictly historical local
bar data). **Sector and market-cap tier explicitly omitted** — no
point-in-time source was available this session; not substituted with a
current classification.

**Result**: A's 6 issuers — mean pre-entry volatility **77.6%**
(ACHR 126.3%, MSTR 129.1%, UNH 84.0%, ADC 15.1%, ABT 41.3%, IBM 69.7%).
B's 101 issuers — mean **52.6%**. A's mean falls at the **96.8th
percentile** of 5,000 random 6-issuer draws from B (seed 118118) — A's
traded issuers are **substantially and unusually more volatile** than a
typical random subset of the broader panel.

**Interpretation, explicitly bounded**: this is a **descriptive
association**, not a causal claim. It is a plausible, testable factor
(a fixed 10-day hold / fixed 20bps cost structure not scaled to
volatility could plausibly perform worse on higher-volatility names) —
it is **not proof** that volatility caused A's negative result, and a
6-issuer sample cannot rule out chance. No feature was removed or added
after seeing this result; this was the one predeclared check.

## Required research decision

### A. ONE_TESTABLE_HYPOTHESIS — labelled EXPLORATORY, with a genuinely unused confirmation requirement

**Hypothesis**: elevated pre-entry realized volatility in the 39-name
scope's traded issuers (mean 77.6%, 96.8th percentile vs. the broader
panel) contributes to the scope's negative net expectancy at the frozen
10-day hold / 20bps cost structure, which is not volatility-scaled.

- **Causal rationale**: a fixed hold period and fixed cost convention
  applied to higher-volatility names plausibly realizes more noise/
  reversal risk within the hold window than the same structure applied
  to lower-volatility names — a mechanism, not just a correlation.
- **Existing data used so far**: retrospective only (the composition
  check above) — **explicitly exploratory**, already-inspected data,
  per this task's own labelling requirement.
- **Genuinely unused confirmation data**: **future, live 39-name-scope
  entries**, not yet observed — the only genuinely new data available to
  this programme (matching Task 118B's protocol).
- **Fixed protocol**: for each new live entry going forward, record the
  same pre-entry realized-volatility measure alongside the eventual
  realized net return; at N≥10 new live entries, test (within the SAME
  scope, not cross-population) whether higher-volatility entries realize
  worse net returns than lower-volatility ones.
- **Cost model / evaluation population**: unchanged — the frozen 20bps
  convention, the same live 39-name scope only (avoids the cross-
  population confound this whole Task 118 comparison was built to
  isolate).
- **Relation to prior rejected work**: distinct from Task 95K (risk-
  avoidance filter, found flagged names' forward returns were
  **positive** — the opposite direction, and a different mechanism
  entirely: a general risk flag, not a volatility-conditioned expectancy
  test within an already-validated signal).
- **Rejection criteria**: if forward high-volatility entries do **not**
  show worse realized net returns than low-volatility entries (no
  negative relationship, or a positive one), the hypothesis is rejected
  — treat A's historical negative result as more likely sampling noise
  at small N, not a volatility effect.
- **Expected deliverable**: a short, bounded update appended to the
  existing live-observation tracking (Task 118B's protocol) once N≥10
  new entries accumulate — **not** a new backtest, **not** a strategy or
  threshold change in the meantime.

**No scope expansion, feature removal, or live strategy change follows
from this hypothesis automatically** — it is a tracking addition to the
already-authorized live-observation programme, nothing more.

## Evidence / reproducible scripts

`results/task118_profitability/time_block_sensitivity.py`,
`composition_check.py` (checked in, both predeclared per their own
docstrings), outputs `reconciliation/{time_block_sensitivity,
composition_check}.json` (checked in, sanitized).
