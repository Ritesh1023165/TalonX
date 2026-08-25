# Primary Candidate Draft — Idiosyncratic Residual Momentum (LONG)

**State: PRIMARY_CANDIDATE_READY_TO_FREEZE** (draft only — Task72 freezes it)

## Mechanism

At 11:00 ET, compute the stock's residual return since the 09:30 open,
net of a causally-estimated (trailing 20 trading days, strictly before
today) market beta times SPY's own return over the same window. If that
residual is positive and exceeds a threshold, go long at the next bar's
open and hold to a fixed horizon.

## Why this is the one candidate that survived

Of 72 predeclared cells across 4 families, **every single one of this
candidate's own 8 cells** (2 threshold bands × 4 horizons) is
independently profitable, net of 10bps cost — nothing else in the whole
program showed that. It is also sign-stable across three genuinely
distinct time segments and three distinct calendar regimes (2025 Q1 / Q3 /
Q4), not concentrated in a handful of symbols or days, and shows real
economic margin above cost (friction absorption ratio 1.1–2.8×), not a
razor's-edge result.

## Headline (primary illustrative cell: threshold=0.75%, EOD exit)

- 217 trades, 35 symbols, 26 days
- Gross expectancy +0.227%, net @10bps +0.127%, PF 1.31
- Time segments (net): EARLY +0.06% → MIDDLE +0.08% → LATE +0.20%
- Regimes (net): 2025Q1 +0.06% / 2025Q3 +0.03% / 2025Q4 +0.22%
- Concentration: top1 symbol 9.2%, top1 day 18.9%

## Honest weaknesses (not hidden)

- **Day-clustered bootstrap CI crosses zero** at every cell (the
  symbol-clustered one mostly doesn't) — per the task's own instruction to
  report the weaker interpretation, this is disclosed as the operative
  caveat, not glossed over. With only ~22-26 trading days in the
  development pool, cross-sectional/market-wide dependence within a day
  cannot be ruled out.
- **SHORT side of the identical mechanism fails** — this is a LONG_ONLY
  candidate (explicitly allowed), not a symmetric discovery.
- **No sector-level control** — only market (SPY) beta is removed; the
  universe's heavy tech/semiconductor weighting means some of what looks
  idiosyncratic could be sector-common movement. Not demonstrated either
  way; recorded as an open question.
- **No stop/risk rule is frozen.** `risk_stop_diagnostics.csv`: median MAE
  0.61%, median MFE 0.99%, 90th-percentile MAE 2.19%. `STOP_UNRESOLVED` —
  explicitly Task72's job, not silently skipped.
- Same unresolved corporate-actions/split-adjustment gap as every prior
  family in this program.

## 15/15 nomination criteria

See `primary_candidate_draft.json`'s `criteria_check` for the full,
individually-justified pass/caveat on every one of Part 21's 15
conditions. 13 clear passes, 2 explicit caveats (provider-portability
caveat on an unused optional feature; stop/risk explicitly unresolved) —
neither caveat is a silent gap.

## What Task72 needs to do

Freeze the exact parameters (which threshold band, which horizon —
EOD and 180m both look strong; 0.75% threshold has more breadth, 1.5%
has a larger per-trade edge on less data), fingerprint the spec, design
and freeze a stop rule using DEVELOPMENT data only (never derived from a
holdout outcome), pre-register a validation protocol (same 8-criterion
discipline F6 used), and lock a genuinely clean holdout — **not** any part
of calendar year 2024 (Task70 consumed two blocks of it; the rest must
stay untouched per this task's own holdout-budget rule) and **not** the
2025-01-24..2026-08-14 range now used for this candidate's own
DEVELOPMENT (that range is contaminated for THIS candidate specifically,
even though it was already contaminated for other strategies before).
