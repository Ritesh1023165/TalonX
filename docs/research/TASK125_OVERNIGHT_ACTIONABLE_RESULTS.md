# Task 125 Part 5/6 — overnight-attention actionable candidate, extended evaluation and decision

Runs `research/scripts/task125_overnight_evaluation.py` exactly ONCE,
reusing Task 123 Track B's transformation and uncertainty method
unchanged (only the input directory/window differ per cohort — see
`docs/research/TASK125_FROZEN_EXTENSION_PROTOCOL.md`). Full
machine-readable output: `results/task125_intraday_extension/task125_evaluation_results.json`
(copied to `docs/research/evidence/task125/`).

**Portfolio scope note (per the frozen protocol and this task's own
instruction)**: every figure below is an EVENT-return statistic (mean/
median/CI over individual trigger observations). No capital-constrained
portfolio was simulated — no equity curve, no position sizing, no
drawdown. That is explicitly out of scope here, exactly as it was in
Task 123.

## Correctness check: Cohort D reproduces Task 123 bit-for-bit

Cohort D (the original 12 symbols, Task 123's own 2025-01-24→2025-08-14
sub-window, but read from THIS task's independently re-acquired,
feed-verified SIP data) reproduces Task 123's original Track B numbers
**exactly**: 579 eligible observations, 31 triggers, incremental net
**−0.5504%**, 95% CI **[−2.1445%, +1.2090%]** — identical to the figures
already published in `TASK123_OVERNIGHT_ATTENTION_RESULTS.md`. This
confirms two things predicted in the frozen protocol BEFORE this script
ran: (1) `task93_canonical_v1` genuinely is SIP data (an exact
numerical match would not be expected otherwise), and (2) this task's
re-implementation of the transformation carries no drift from Task
123's original code.

## Cohort results

| cohort | eligible | triggers | issuers | dates | trigger net mean | control net mean | incremental | 95% CI (incremental) |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| **A — original 12, expanded (2023–2025-08-14)** | 3,201 | 158 | 12 | 117 | **−0.1196%** | +0.1088% | **−0.2284%** | [−0.7946%, +0.3458%] |
| B — added cohort (BABA/SHOP/SPCX) | 395 | 31 | 3 | 31 | +0.2588% | −0.0158% | +0.2746% | [−0.4970%, +1.0535%] |
| C — combined (secondary) | 3,596 | 189 | 15 | 136 | −0.0575% | +0.0952% | −0.1527% | [−0.6333%, +0.3531%] |
| D — original sub-window, verified SIP | 579 | 31 | 12 | 20 | −0.2688% | +0.2816% | −0.5504% | [−2.1445%, +1.2090%] |

All four cohorts' 95% CIs on the incremental estimate **include zero**.

### Cohort A — the primary population (per the frozen decision hierarchy)

- Eligible observations: 3,201 (out of 8,124 candidate session/symbol
  pairs with cutoff-window coverage — see exclusion funnel below).
- 158 triggers across all 12 symbols, 117 distinct trigger dates
  (bootstrap resampled over **542 distinct trading dates total**, a
  ~5.4× increase in date-dependence resolution over Task 123's original
  100 distinct dates).
- Trigger gross return mean **−0.0696%**, net **−0.1196%** (win rate
  46.8%). Control (unconditional) net mean **+0.1088%**.
- Incremental (trigger−control) net: **−0.2284%**, 95% CI **[−0.7946%,
  +0.3458%]** — includes zero.
- **Absolute net trigger return is itself negative** (−0.1196%), not
  merely underperforming a positive control — this matters for the
  product decision (§ below): a positive incremental estimate riding
  on a negative absolute return would not by itself be a deployable
  signal, and here the incremental estimate itself is also negative.
- By year: 2023 n=56 mean −0.1144%; 2024 n=71 mean −0.0586%; 2025 n=31
  mean −0.2688% (the 2025 slice is Cohort D exactly). No year shows a
  positive mean.
- Concentration: top issuer (INTC) contributes 21/158 triggers (13.3%
  of the cohort); excluding INTC, the mean net return is +0.1598% (a
  sign flip) — reported as a descriptive comparison, not an
  independent CI, consistent with Task 123's own treatment of
  issuer-concentration sensitivity checks.

### Cohort B — the added cohort (BABA, SHOP, SPCX)

- 395 eligible, 31 triggers, but concentrated in only 3 issuers over
  31 distinct dates — **BABA alone contributes 18/31 triggers (58%)**.
  SPCX and SHOP together supply the remaining 13.
- Incremental net **+0.2746%**, 95% CI **[−0.4970%, +1.0535%]** —
  includes zero, and the point estimate does not itself clear the
  ±10bps materiality band by enough margin to be treated as anything
  but noise given n=31 and 3-issuer concentration.
- By year: 2023 n=12 mean −0.0574%; 2024 n=13 mean **+1.1424%**; 2025
  n=6 mean −1.023% — no stable direction across years, consistent with
  a small, concentrated, noisy sample rather than a real effect.
- This cohort is explicitly **secondary/exploratory** — 3 issuers is
  far too few to treat as a validated population in its own right, and
  it was never the primary cohort per the frozen protocol.

### Cohort C — combined (secondary, per protocol)

- Reported per the frozen protocol's explicit instruction to keep this
  secondary. Incremental net **−0.1527%**, CI **[−0.6333%, +0.3531%]**
  — includes zero, sitting between Cohort A's negative result and
  Cohort B's small positive/noisy one, as expected from a population
  average of the two. Not treated as a tiebreaker or a way to average
  away Cohort A's own negative reading.

## Eligibility funnel (Cohort A, the primary population)

| stage | count |
|---|---:|
| candidate session/symbol pairs with any cutoff-window bar | 8,124 |
| excluded: insufficient trailing history (< 20 fully-covered prior sessions) | 2,514 |
| excluded: missing entry bar (no bar at exactly 15:52 ET) | 2,401 |
| excluded: missing next session's open bar | 7 |
| excluded: extreme return (corporate-action guard, |gross|>50%) | 1 |
| **eligible** | **3,201** |

- The `missing_entry_bar` and `insufficient_trailing_history` rates
  are large fractions of the candidate pool. This is **inherited,
  already-accepted behavior**, not a new defect from this task's
  acquisition: Cohort D's exact reproduction of Task 123's original
  579/31 figures (same code, same underlying rate on the shared
  sub-window) confirms this exclusion pattern was already present and
  accepted in the original evaluation. No forward-fill or bar
  substitution was applied anywhere to reduce it.
- The single `extreme_return_excluded` hit in Cohort A/C corresponds
  to one of the two confirmed 2024 stock-split discontinuities
  (AVGO/NVDA — see `TASK125_DATA_ACCEPTANCE.md`); the guard performed
  exactly as predeclared.

## Statistical verdict

Applying the frozen decision criteria (`TASK125_FROZEN_EXTENSION_PROTOCOL.md`
§6) to Cohort A, the primary population:

> **`INCONCLUSIVE`** — the incremental 95% CI **[−0.7946%, +0.3458%]**
> includes zero.

(Cohorts B, C, and D are also each individually `INCONCLUSIVE` by the
same rule — no cohort's CI excludes zero.)

## Product verdict

> **`DO_NOT_ADVANCE`**

Reasoning, applying the frozen criteria without modification after
seeing results: `ADVANCE_TO_FURTHER_VALIDATION` requires
`EVIDENCE_SUPPORTS_PREDECLARED_EFFECT` on Cohort A AND a positive,
economically credible absolute net return — neither condition holds
(statistical verdict is `INCONCLUSIVE`, not `SUPPORTS`, and Cohort A's
absolute net trigger return is itself negative, −0.1196%).
`EVALUATION_BLOCKED_BY_DATA_QUALITY` does not apply — the eligibility
funnel and corporate-action guard behaved exactly as predeclared, with
no defect found, only an already-known, already-disclosed data
sparsity (missing-entry-bar rate) inherited unchanged from Task 123.
What remains is the frozen protocol's own explicit instruction: *"If
the result is negative or economically inadequate, close this
contract."* Cohort A's point estimate is negative on both the
incremental basis (−0.2284%) and the absolute basis (−0.1196%), with a
CI that includes zero and does not clear the materiality band in
either direction — this is the negative/economically-inadequate case,
and this task closes the contract accordingly, consistent with
`DO_NOT_ADVANCE` verdicts reached under the same pattern (CI includes
zero, non-positive point estimate) in Tasks 120A–C, 121B, and 123.

This is now a **materially stronger negative/null result** than
Task 123's original: 3,201 eligible observations over 542 distinct
trading dates (vs. 579 observations over 100 dates), spanning three
different calendar years (2023–2025) instead of one 7-month window,
and the primary cohort's point estimate stayed negative in every one
of those years. The added cohort's small positive reading (Cohort B)
is explained by concentration in a single issuer (BABA, 58% of its
triggers) and does not generalize across years within that cohort
either.

## Limitations

- This remains an event-return statistic, not a capital-constrained
  portfolio simulation — no equity, no drawdown, no position sizing.
- SPCX's extreme illiquidity (573/606 dates with any cutoff-window
  bar, ~4.7 bars/day) means its contribution to Cohort B/C is thin and
  noisy on its own; it was not excluded a priori (a coverage-based,
  not performance-based, decision per the frozen protocol) but its
  practical contribution to the added cohort's statistics is small.
- Raw/unadjusted prices mean dividends are not reflected and any
  future undiscovered split would need the same mechanical
  extreme-return guard, not a manual correction — a known, disclosed
  limitation carried over unchanged from Task 123.
- Issuer/date dependence: even with 542 distinct dates and the
  date-block bootstrap's joint resampling, common-shock correlation
  across the 12–15 large, liquid tech/mega-cap-adjacent names in this
  universe means the EFFECTIVE number of independent observations is
  smaller than the raw trigger count — this is exactly what the
  bootstrap method (not a naive per-observation CI) is designed to
  respect, and it is why 158 or 395 raw triggers do not by themselves
  constitute a "properly powered" claim.

## One next decision

Close the overnight-attention pre-close actionable candidate
(EXPERIMENTAL_RELAXED_V1's successor hypothesis) as tested — do not
search alternative volume thresholds, delays, exits, or ticker subsets
within this contract, and do not schedule another rerun or indefinite
live observation as the path forward, per this task's own explicit
instruction. The daily-data association (Task 123 Track A) remains
retained as a disclosed, qualified, non-actionable research finding —
unaffected by this closure. Two untouched, literature-grounded
hypotheses from Task 122's shortlist (52-week-high proximity — George
& Hwang 2004; turn-of-month — McConnell & Xu 2008) remain available for
a future task to pick up; this result does not reopen or touch either.
