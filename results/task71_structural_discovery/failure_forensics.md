# Task71 Forensic Failure Audit

Full evidence trail in `failure_forensics.csv`. This document answers the
task's specific lettered forensic questions and gives the bottom-line
"which failures were genuine alpha failures" verdict.

## 1. Were failures genuine alpha failures?

**Mostly yes, with important nuance:**

- **Genuinely negative/absent effects** (clean rejections, not artifacts):
  F5 (compression precondition — "clean negative: compression alone
  predicts nothing"), F1/F2 (wrong-sign vs. hypothesis — a real, measured
  reversal where continuation was hypothesized), FPRC_V1 (gross expectancy
  ≈0, nothing to erode), ORPB_V1 (gross expectancy already negative
  pre-cost), F6_FADE_V1's replication (broad, statistically confident
  negative result, no integrity issue found).
- **Real but sub-friction effects** (not "false," just not tradeable at
  realistic cost): F4 (relative strength) is the clearest case — a
  carefully causal, bootstrap-CI-excluding-zero, correctly-signed effect
  that is simply smaller than 10bps round-trip cost. This is an
  **ECONOMIC_EDGE_TOO_SMALL** failure, not a hypothesis failure — the
  phenomenon may be real, the friction margin is not there.
- **Underpowered, not falsified**: ORPB_V1 (46 trades, CI crosses zero) and
  F3's headline definition (n=76, isolated) are **SAMPLE_SIZE**/
  **MULTIPLE_TESTING_RISK** cases where the evidence doesn't clearly
  support OR refute the hypothesis — they were correctly NOT promoted, but
  they are not the same kind of failure as F5's clean negative.
- **Program-level implementation churn**: the legacy Quant strategy's
  three successive baselines (Task 8 → 26 → 36) each corrected a real bug
  (short-inclusion, then stop-geometry) that materially changed the trade
  population each time. None of the three ever reached a positive,
  cost-surviving, adequately-sampled result — the strategy's status
  remains **officially UNPROVEN**, not "rejected as unprofitable" and not
  "vindicated." No prior conclusion is invalidated by this — the
  UNPROVEN status was already the honest one at each checkpoint.

## 2. No previous conclusion is retroactively relabeled as successful.

Every classification in `failure_forensics.csv` preserves the original
task's own verdict; Task71 only adds a structured cause classification on
top.

## Lettered forensic questions

**A. Costs applied consistently and correctly?** Yes, everywhere checked —
FPRC/ORPB both report 0bps/5bps side-by-side with the same formula
pre- and post-fill; F1-F6 all use the same 5bps one-way/10bps round-trip
convention from `research/task67a_lib/screening_framework.py`; F6's
evaluator computes `net_return = gross_return - cost_bps/10000` uniformly.
No inconsistency found.

**B. Same-bar or future-data lookahead present?** No — checked explicitly.
FPRC_V1 and ORPB_V1 both mandate next-bar-open entry after confirmation
(`pre_replay_gates.json: confirmation_to_fill_is_next_available_bar: true`
for FPRC). F6's evaluator explicitly delays entry to the bar strictly
after the decision bar (a deliberate divergence from Task67B's own
screening convention, which used same-bar close — Task68A's freeze
process caught and corrected this before F6 was frozen, the ONE place a
lookahead-adjacent convention existed and it was fixed prior to freezing,
not discovered after).

**C. Bar timestamps/session boundaries correct?** Yes, no defect found in
any of the audited strategies.

**D. Regular/extended-hours semantics consistent?** Consistent within each
strategy's own scope; F6 explicitly only uses regular-session bars
(09:30-16:00 ET). No extended-hours strategy has been tested yet — Family
B (Task71) is the first to require it.

**E. Split/corporate-action adjustments handled consistently?** Not
separately audited in the original tasks; Alpaca's raw (unadjusted, per
`download_historical_1m.py`'s `adjustment: "raw"` parameter) bars are used
throughout. This means a stock split within any DEVELOPMENT/VALIDATION/
REPLICATION window would show as a large single-bar price discontinuity.
No task has explicitly checked for or found one. **Flagged as an
unresolved forensic gap** — see `development_universe_audit.json`'s
corporate-action note.

**F. Long/short fills and exits causal?** Yes — no violation found in any
audited strategy. F6's own Task70 evaluation directly measured zero causal
violations (decision-to-entry always >0 seconds).

**G. Did EOD flatten truncate a strategy relative to its hypothesis?** No
— checked for both FPRC_V1 and ORPB_V1 (both intraday-only hypotheses with
no explicit target requiring more time than 15:50 ET allows) and F6
(fixed 60m exit, never approaches the flatten in the vast majority of
cases). **15:50 ET flatten is correctly NOT classified as a bug anywhere**
in this audit — consistent with the task's own instruction.

**H. SIP-vs-IEX provider mismatch?** Actively investigated once (ORPB_V1,
Task63R) and **ruled out** as an explanation for an early data gap — the
gap was a genuine SIP data hole (confirmed by comparing no-feed-param vs.
explicit feed=sip vs. feed=iex payload hashes), not a feed-default bug.
Per the task's own instruction, this historical SIP-vs-SIP finding does
NOT invalidate any validation/replication conclusion — it only matters for
future runtime portability (see `provider_semantics_assessment.json`).

**I. Survivorship/selection bias in universe choice?** Yes, structurally —
see `survivorship_bias_assessment.json`. The 35-symbol universe is today's
liquid mega-cap set, applied retroactively across all history. No task has
reconstructed historical index constituents. Documented as
`CURRENT_UNIVERSE_BACKCAST_BIAS`, not fabricated away.

**J. Overlapping trades/events creating pseudo-independent samples?**
Partially addressed — F4's calibration/application-half split and F6's
per-(symbol,day) uniqueness both limit this, but cross-sectional
same-day events (e.g. many symbols firing on the same SPY-wide move) were
not explicitly declustered anywhere prior to Task71. This is exactly why
Task71's own diagnostics (Part 14) require cluster-by-day bootstrap CIs
alongside cluster-by-symbol.

**K. Market-wide moves inflating apparent independence?** Same concern as
J — not previously addressed. Task71's Family A/C/D diagnostics report
both symbol- and day-clustered CIs and take the weaker one.

**L. Multiple-testing/search-budget exposure, quantified.** Stage 1 (Task
67A/67B) screened **6 families × 3 definitions = 18 definitions**, each
across up to 4 horizons (15/30/60/120m) = a base grid of ~72 horizon-level
comparisons, with F4 and F5 each running 2-3x secondary analyses
(raw/SPY-adjusted/sector-adjusted; signed/unsigned) on top — well over 100
distinct numeric comparisons in Stage 1 alone. F3's own rejection
explicitly invoked multiple-testing/cherry-pick risk for its isolated
n=76 "winner." FPRC_V1 and ORPB_V1 add 2 more sequential single-candidate
architectures (no internal parameter sweep, but each is one more shot
against the same infrastructure/universe). F6_FADE_V1's Task70 validation
adds one more (pre-registered, single) test. **Grand total exposure across
the whole program to date: on the order of 100+ distinct numeric
comparisons**, of which exactly one (F6) was promoted, and it failed
replication. This is consistent with — not contradicting — a
multiple-testing-adjusted read where zero of ~100+ comparisons produced a
result that survived independent replication.

**M. Could a prior positive discovery be explained by specification
luck?** F6 is the direct test case: it was the single definition (out of
18 screened) that cleared Stage-1 promotion criteria, and it failed
replication on a broader sample with a reversed sign. This is close to
exactly what "the one lucky definition out of many" looks like when
followed to a real out-of-sample test. F3's headline n=76 result was
flagged by the researchers themselves as this same pattern and correctly
never promoted. No other family reached the promotion bar, so no other
specification-luck case exists to evaluate.

## Biggest research failure mode identified

**Screening many definitions/families against one bounded development
window, then trusting a promotion decision made on statistical criteria
alone (CI excludes zero, adequate breadth) without an explicit
multiple-testing adjustment.** F6 passed every Stage-1 criterion
legitimately, was frozen honestly, and STILL failed replication. This is
not evidence any individual step was done badly — it is evidence that
~18-100+ comparisons against one dataset will produce roughly one
"passing" result by chance alone, and Stage 1's own criteria (while
rigorous) were not adjusted for how many other definitions had already
been tried. Task71's design lock addresses this directly: a bounded,
predeclared grid (72 cells, not "search until something works"), explicit
multiple-testing accounting (Part 13), and cluster-aware statistics (Part
14) are now mandatory for every family before nomination.
