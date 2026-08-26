# Task75A Part 1 -- Effective Search-Count Audit

**Finding: NOT a prohibited promotion, but a genuine specification gap.**

Task74B's design lock declared `hypotheses_as_directions: [MOMENTUM,
REVERSAL]` as the family's 2-slot "directions" budget -- i.e. the
search-budget accounting treated MOMENTUM vs REVERSAL as the
pre-registered choice axis, not LONG vs SHORT. LONG and SHORT are a
deterministic PAIR that falls out of evaluating one hypothesis at one
threshold/horizon (top-rank and bottom-rank populations are both
computed together, not separately chosen).

Task74B correctly reported both halves separately (40 rows, not 20 --
the carried-over "no pooling to hide a failing side" rule). But it then
**promoted only the SHORT half of REVERSAL** after observing that the
LONG half was weak/unstable. The locked design never explicitly says a
single leg may be independently promoted -- it is silent on this,
not a violation, but not a clean authorization either.

**Decision: NOT BLOCKED.** The design was not "prohibited" in the sense
Part 1 asks about. But the honest multiple-testing denominator for this
candidate's provenance is **40** direction-level rows compared before a
winner was chosen, not 20 hypothesis-level cells. This is carried
forward into `validation_protocol.json` as an explicit caveat.

## Why this doesn't invalidate the nomination

- The margin is large (net@10bps 0.507% vs the 0.15% bar -- 3.4x), not
  a borderline squeak-through.
- All 6 parameter cells (2 bands x 3 horizons) of REVERSAL/SHORT share
  the same sign -- a genuine plateau, unlikely from a lucky flip.
- BOTH cluster bootstrap CIs (symbol and day) exclude zero at the
  anchor cell.
- Outlier-removal robustness (best-5-trades, best-3-days) remains
  positive.

## Program-wide caveat

No formal multiple-testing correction across this program's full
history (F1-F6, FPRC_V1, ORPB_V1, residual momentum, and now this
candidate) has ever been applied -- disclosed as an open limitation of
every candidate this program has produced, not unique to this one.
