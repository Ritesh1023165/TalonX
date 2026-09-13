# Task 123 — overnight attention diagnostic: results and decision

Protocol frozen in `docs/research/TASK123_FROZEN_PROTOCOL.md` before
either track was run against real outcomes. Timing correction to
Task 122: `docs/research/TASK123_TIMING_CORRECTION.md`. Script:
`research/scripts/task123_overnight_diagnostic.py`. Full artifacts:
`results/task123_overnight_diagnostic/` (local); small sanitized
summaries committed under `docs/research/evidence/task123/`.

## Part 3 — coverage (active / paused / historical, explicit)

| population | n | names |
|---|---:|---|
| All configured | 48 | — |
| **Active** (per `watchlist_coverage`'s own `status` field) | 43 | — |
| **Paused** | 5 | ASML, PATH, PLTR, RIG, SMCI |
| Active + existing daily-bar coverage (Track A universe) | **38** | see `TASK123_FROZEN_PROTOCOL.md` |
| Active, daily-covered, but paused-excluded from primary scope | — | 3 of the 5 paused names (PLTR, RIG, SMCI) DO have daily coverage — excluded here as a labelled choice, not a data gap |
| Active with NO located daily coverage | 5 | BABA, BLSH, SHOP, SKHY, SPCX |
| Active daily-covered ALSO with existing 1-min intraday coverage (Track B universe) | **12** | AAPL, AMAT, AMD, AVGO, CSCO, GOOGL, INTC, MSFT, NVDA, PYPL, STX, TSLA |

**Not called "35/48 full coverage" or any single blended fraction** —
each population above is reported on its own terms. Source precedence
(`task95g_broad_cross_sectional/_daily` first, `task107a_form4_feasibility/_prices`
fallback): checked explicitly — **zero tickers exist in both
directories** for this configured universe, so precedence was never
actually invoked (stated for completeness, not because a real conflict
existed). Data-quality checks (ordered/unique dates, valid prices/
volumes, complete 20-session trailing windows, correct next-exchange-
session via `talonx_v2.calendar`, adjustment provenance) are enumerated
per-symbol in `docs/research/evidence/task123/track_a_association_summary.json`'s
`exclusion_counts_by_symbol` — **zero duplicate/out-of-order/non-
positive/negative-volume rows found across all 38 symbols.**

## Part 4 — Track A results (daily association diagnostic, NON-ACTIONABLE)

| | |
|---|---:|
| Eligible observations | 67,608 |
| Trigger events (volume[S] ≥ 2.0× trailing 20-session avg, excl. S) | **2,557** |
| Distinct trading dates spanned | 1,905 |
| Excluded: insufficient trailing history | 760 |
| Excluded: missing next exchange session | 38 |
| Excluded: extreme return (data-quality guard) | 0 |

**Reference returns** (gross = pre-cost; net = after 5bps round-trip,
applied once):

| | trigger (conditional) | control (unconditional, same symbols/dates) |
|---|---:|---:|
| N | 2,557 | 67,608 |
| Gross mean | +0.2461% | +0.0774% |
| Net mean | **+0.1961%** | **+0.0274%** |
| Median (net) | +0.0388% | +0.0103% |
| Win rate | 51.8% | 50.6% |
| Worst 5% mean | −5.836% | −3.691% |

**Incremental difference (trigger − control), net**: **+0.1687%
(16.87bps)/event**. This is reported explicitly as the incremental
quantity, distinct from the trigger population's own absolute return —
per this task's own caution, a positive absolute conditional return
alone could just be the ordinary (positive) overnight effect; the
incremental figure isolates what the VOLUME condition adds beyond that.

**Uncertainty** (date-block bootstrap, 5,000 reps, seed 123123, joint
trigger/control resampling from the same resampled date-multiset): 95%
CI on the incremental difference = **[+0.0295%, +0.3085%]** —
**excludes zero**. Effective independent unit: 1,905 distinct trading
dates (not 2,557 events, not 38 issuers).

**Predeclared sensitivities**:
- Drop-top-1-issuer (MSTR, 112/2,557 triggers): mean moves from
  +0.1961% to **+0.1770%** — same direction, not reversed.
- Stricter trigger (2.5× instead of 2.0×, same population/window):
  N=1,279, net mean **+0.2091%** — same direction, slightly larger, not
  reversed.

**Materiality check**: the predeclared ±10bps band (5bps modeled cost +
one assumed-friction unit) is **partially, not fully, cleared** — the
CI's lower bound (+2.95bps) sits BELOW +10bps, even though the point
estimate (+16.87bps) and most of the CI's mass clear it comfortably.
Stated precisely, not rounded up or down to force a clean verdict.

## Part 5 — Track B: actionable feasibility and bounded test

**Feasibility**: existing 1-minute intraday data
(`task93_canonical_v1`) covers 12 of the 38 Track-A-eligible symbols,
over a COMMON window of 2025-01-24→2025-08-14 (~7 months) — sufficient
to construct the frozen pre-close contract, so the bounded test WAS
executed in this task (not blocked).

**Contract** (see `TASK123_FROZEN_PROTOCOL.md` for full detail):
decision cutoff 15:50 ET, same-time-of-day cumulative-volume trigger
(2.0×, unchanged), 2-minute alert delay, entry reference fill at 15:52
ET, exit reference fill at the next session's own open, 5bps cost.

| | |
|---|---:|
| Eligible observations | 579 |
| Trigger events | **31** |
| Excluded: missing entry-observation bar (no 1-min print at 15:52 ET) | 0–109 per symbol (TSLA 1, NVDA 0 vs. STX 109, AMAT 78, CSCO 77) — a genuine, disclosed intraday-data-sparsity limitation, not a bug |
| Excluded: insufficient trailing history | 50/symbol (the fixed 20-session warmup) |

| | trigger (conditional) | control (unconditional) |
|---|---:|---:|
| N | 31 | 579 |
| Net mean | **−0.2688%** | +0.2816% |

**Incremental difference, net**: **−0.5504%/event** — NEGATIVE, opposite
direction from Track A's daily-association finding. 95% CI (same
date-block bootstrap method, seed 123123): **[−2.1445%, +1.2090%]** —
wide, includes zero, dominated by the small sample (31 events, 100
distinct dates).

**This is not read as a contradiction of Track A** — N=31 on this exact
pre-close mechanism is far too small to support any inference in either
direction; the wide CI reflects that directly. It IS read as: the
specific tested actionable contract shows no supported positive
incremental effect, and the available existing intraday data (12
symbols, ~7 months) cannot resolve the question further without either
(a) more intraday history for the SAME symbols (not available locally)
or (b) intraday coverage for more of the 38 Track-A-eligible symbols
(not available locally) — named as the exact missing input, not
invented around.

**Corporate-action/execution limitations**: `task93_canonical_v1` is
UNADJUSTED; the dataset's own existing `data_quality_report.md` audit
already confirmed **no stock splits** occurred for any of its 35
symbols in this window — cited, not re-derived. Dividends are not
adjusted for in Track B (a raw price return), unlike Track A's
adjustment-embedded total-return proxy — the two tracks' return
definitions are NOT directly comparable for this reason, disclosed
explicitly. Entry/exit prices are REFERENCE FILLS (observed subsequent
1-minute bar closes/opens) — never claimed as achievable executable
quotes; no broker, no live order routing, no slippage model beyond the
flat 5bps convention was used or implied.

## Part 6 — decision

**Diagnostic verdict (Track A)**: **`ASSOCIATION_SUPPORTED`** — the
incremental (trigger-minus-control) net return has a 95% CI that
excludes zero ([+2.95bps, +30.85bps]), is robust in direction and
magnitude to both predeclared sensitivities, and is computed with a
dependence-aware (date-block, joint trigger/control) uncertainty
method across 1,905 distinct dates. **Qualified**: the CI's lower bound
does not fully clear the predeclared ±10bps materiality band — the
association is real but not unambiguously large enough, at the low end
of its confidence range, to guarantee it would survive realistic costs
beyond the already-modeled 5bps.

**Actionable-candidate verdict (Track B)**: **`NOT_SUPPORTED_UNDER_TESTED_CONTRACT`**
— the ONE frozen, pre-close, causally-valid mechanism actually tested
(15:50 ET cutoff, 2-minute delay, 12-symbol/7-month available intraday
data) shows a NEGATIVE point estimate and a CI that includes zero. This
is not escalated to a stronger rejection than the evidence supports
(N=31 is a real, disclosed, small-sample limitation) — but it is also
not read as "inconclusive, therefore worth another attempt": per this
task's own explicit instruction, no alternative cutoff, delay, or
holding period is searched to find a better-looking result on the same
limited data.

**Interpretation, stated plainly**: a profitable-looking DAILY
association (Track A) does not, by itself, advance an executable
strategy — it depends on information (final daily volume) that is not
available at the moment a same-day action would need to be taken. The
one genuinely causal, pre-close-only version of this mechanism that
existing intraday data can support was tested and did not show a
supported effect. Already-inspected history (both tracks used
already-published, no-new-cost data) remains exploratory, not
confirmatory. No Telegram enablement, no production promotion, no
window extension follows from either result.

## ONE next action

**Close the overnight-attention hypothesis as an actionable candidate**
for the configured-ticker product on currently available data — do not
search alternative pre-close cutoffs/delays/windows on the same
12-symbol/7-month intraday sample (explicitly prohibited, and would not
resolve the underlying data-coverage constraint regardless). Track A's
daily association result is retained as a genuine, disclosed research
finding (archived, not a promoted product signal) for potential future
reconsideration IF broader intraday coverage becomes available through
this program's existing free data-access channels (not a new
acquisition — a possible future task, not committed here).

**Smallest input that would change the actionable answer**: 1-minute
(or finer) intraday bars for more of the 38 Track-A-eligible symbols,
and/or a longer intraday history for the 12 already-covered symbols,
sourced through the SAME existing free Alpaca access this program
already uses (no paid data, no new provider) — named as the exact gap,
not pursued in this task.

**Separately**, this task does not select a replacement hypothesis —
Task 122's own shortlist (Hypothesis 2: 52-week-high proximity;
Hypothesis 3: turn-of-month) remains available for a future task's own
bounded feasibility check, unaffected by this task's result.
