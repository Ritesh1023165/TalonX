# Claude Handoff — after Task71

## Immediate next priority

**Task72: freeze `IDIOSYNCRATIC_RESIDUAL_MOMENTUM_LONG`** (see
`primary_candidate_draft.{json,md}`). Do not re-run Task71's discovery
grid, do not tune any of the 8 already-positive cells, do not chase the
SHORT side or any of Families A/B/D again — those are cleanly closed.

## What Task72 specifically needs to decide/do

1. **Pick exact frozen parameters** from the 8 already-computed cells:
   threshold band (0.75% has more breadth — 217 trades/35 symbols/26 days;
   1.5% has a bigger per-trade edge on less data — 93 trades/31 symbols/22
   days) and horizon (EOD and 180m are both strong; 60m is weaker but
   still positive; 120m is in between). Pick based on pre-Task71
   reasoning (robustness/simplicity, like F6's own 60m-over-120m
   rationale), NOT by re-running anything to see which number is biggest.
2. **Design and freeze a stop**, using DEVELOPMENT data only (the same 4
   slices this task used) — see `risk_stop_diagnostics.csv` (median MAE
   0.61%, median MFE 0.99%, 90th-pctile MAE 2.19%) as the starting
   diagnostic. A volatility/ATR-based or structural (e.g. AVWAP
   invalidation, reusing Family A's causal AVWAP code in
   `research/task71_lib/features.py::session_avwap`) stop would both be
   defensible; do not choose a stop by maximizing DEVELOPMENT P&L.
3. **Pre-register a validation protocol** BEFORE touching any holdout —
   reuse `results/task68_f6_freeze/validation_protocol.json`'s 8-criterion
   structure as the template (it's exactly what Task70 executed
   correctly). Decide up front what VALIDATION_PASS/FAIL/INCONCLUSIVE mean
   for this candidate.
4. **Lock a genuinely untouched holdout.** This is the trickiest part:
   - Task70 already consumed `2024-02-01..03-15` and `2024-09-03..10-18`.
   - This candidate's own DEVELOPMENT data is `2025-01-24..2026-08-14`
     (well, the 4 slices within it) — that range is now contaminated
     FOR THIS CANDIDATE specifically, even though it was already
     contaminated for other strategies before.
   - Remaining clean 2024 territory (never touched by anything, per this
     task's inventory): roughly `2024-01-01..2024-01-31`,
     `2024-03-16..2024-09-02`, `2024-10-19..2024-12-31`. Re-verify this
     inventory yourself before trusting it — don't just take my word for
     it, re-run the same kind of exposure audit Task70 and Task71 both
     did.
   - The pre-existing forward-reserved plan
     (`2026-08-25..2026-10-21` from `data_split_contract.json`) may now
     have partially or fully elapsed depending on today's actual date —
     check first.

## If you're asked "why didn't Task71 just try harder on Family B or D"

Don't. Family D never once cleared cost in any of 4 regimes × 3 time
segments on either side — there's no margin to find by tweaking. Family
B's only two positive cells are each sitting right next to a strongly
negative cell on the same threshold/direction at a neighboring horizon —
chasing that specific cell further is exactly the kind of post-hoc
multiple-testing trap this task's own forensic audit (Part 1) diagnosed
as F6's failure mode. Read `failure_forensics.md`'s "biggest research
failure mode" section before being tempted.

## If you're asked about the day-clustered CI caveat

It's real and it's the correct thing to be cautious about — with only
~22-26 distinct trading days across the development pool, cross-sectional
dependence (many symbols moving together on one macro day) can't be ruled
out. This doesn't disqualify the candidate (it's disclosed, not hidden,
and the symbol-clustered CI plus the 3-regime/3-segment sign stability are
real corroborating evidence), but it means Task72/73's validation should
pay close attention to day-level breadth in whatever holdout gets locked —
more distinct days, not just more trades, would directly address this
weakness.

## Files worth reading first

- `task71_summary.md` (this task's full narrative)
- `primary_candidate_draft.md` (the nomination, all 15 criteria)
- `failure_forensics.md` (why prior candidates failed, and the
  multiple-testing lesson this task's own design responds to)
