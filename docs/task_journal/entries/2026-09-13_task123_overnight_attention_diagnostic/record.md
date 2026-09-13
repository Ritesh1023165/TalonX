# Task 123 — overnight attention diagnostic with causal timing

## Objective and acceptance criteria
Correct Task 122's causal-timing defect (a same-day final-volume trigger
cannot be acted on at that same day's close), run the corrected bounded
daily-data association diagnostic, separately determine whether existing
intraday data supports a genuinely actionable version, and reach a
decision in this task.

## Timing
2026-09-13, continuing the same research thread as Task 122.

## Branch / SHA
Release: verified `f28986999eec5e313cfc89db24e4dbacfb378891` unchanged —
no release-branch work this task (research-only). Research `36b28ca` →
this commit.

## Requested vs. completed scope

- **PART 1 (timing correction): DONE.** Withdrew Task 122's implicit
  same-close-execution claim; defined Track A (non-actionable daily
  association) and Track B (actionable pre-close candidate) explicitly.
  Correction blockquote appended to `TASK122_CANDIDATE_DECISION.md` and
  a dedicated `TASK123_TIMING_CORRECTION.md` written. No substitution of
  yesterday's volume or post-close entry was made (both explicitly
  identified as different hypotheses, not silently swapped in).
- **PART 2 (frozen protocol): DONE**, `TASK123_FROZEN_PROTOCOL.md` —
  both tracks' universe, dates, trigger, return definition, cost/
  materiality (±10bps, justified independently — 5bps modeled cost +
  one assumed-friction unit), control population, uncertainty method
  (date-block bootstrap, joint trigger/control resampling, seed
  123123), and exactly two predefined sensitivities (2.5× trigger;
  drop-top-1-issuer) — all fixed before either track was run.
- **PART 3 (coverage): DONE.** Corrected active/paused/covered
  accounting from the LIVE `watchlist_coverage.build_coverage_map()`
  snapshot: 43 active / 5 paused (ASML, PATH, PLTR, RIG, SMCI) of 48
  configured. 38 active names have existing daily coverage (33 from
  `task95g_broad_cross_sectional/_daily`, 5 from
  `task107a_form4_feasibility/_prices` — zero overlap between the two
  directories, so source precedence, though stated, was never actually
  invoked). 5 active names have no located daily coverage (BABA, BLSH,
  SHOP, SKHY, SPCX). 12 of the 38 also have existing 1-min intraday
  coverage (`task93_canonical_v1`). No blended "35/48" or similar
  single-fraction claim made anywhere.
- **PART 4 (fast daily diagnostic, Track A): DONE**, 7 pre-checks
  written and passing BEFORE the full computation
  (`tests/test_task123_causal_timing.py`) covering all 6 required
  properties (trailing-average exclusion, calendar-correct next-session
  pairing, missing-session exclusion not silent-next-row substitution,
  cost applied once, corporate-action/extreme-return guard, zero-
  trigger vs. unavailable-data distinctness) plus a `DATA_UNAVAILABLE`-
  specific test. Full run: 67,608 eligible observations, 2,557 triggers
  across 1,905 distinct dates, 0 data-quality exclusions of any kind
  (duplicates/out-of-order/non-positive/negative-volume), 760 warmup-
  insufficient exclusions, 38 missing-next-session exclusions, 0 extreme-
  return exclusions. Trigger net mean +0.1961% vs. control net mean
  +0.0274% — incremental +0.1687%/event. Date-block-bootstrap 95% CI on
  the incremental: [+0.0295%, +0.3085%] — excludes zero. Both predefined
  sensitivities agree in direction (drop-top-1-issuer MSTR: +0.1770%;
  2.5× trigger: +0.2091%).
- **PART 5 (actionable feasibility, Track B): DONE — data supported the
  bounded test, executed.** 12 symbols × common 2025-01-24→2025-08-14
  window inspected for coverage/timestamp-semantics/completed-bars-
  before-close/entry-observation/next-open-observation. Frozen contract
  (15:50 ET cutoff, same-time-of-day cumulative-volume normalization —
  explicitly chosen over and distinguished from a prior-full-day
  average — 2-minute alert delay, 15:52 ET reference-fill entry, next-
  open reference-fill exit, 5bps cost) executed ONCE, no cutoff/delay/
  window search. Result: 579 eligible, 31 triggers, incremental net
  −0.5504%/event, 95% CI [−2.1445%, +1.2090%] — includes zero, small-
  sample-dominated. Corporate-action note: `task93_canonical_v1` is
  UNADJUSTED; its own existing data-quality audit already confirmed no
  stock splits in this window for any of its 35 symbols (cited, not
  re-derived); dividends not adjusted for (a raw price return, disclosed
  as non-comparable to Track A's total-return proxy).
- **PART 6 (decision): DONE.** Diagnostic: **`ASSOCIATION_SUPPORTED`**
  (CI excludes zero, robust to both sensitivities; qualified — the CI's
  lower bound does not fully clear the predeclared materiality band).
  Actionable: **`NOT_SUPPORTED_UNDER_TESTED_CONTRACT`** (negative point
  estimate, CI includes zero, on the ONE frozen contract actually
  tested — not escalated beyond what N=31 supports, but also not used
  as license to search alternative cutoffs/delays). ONE next action
  named: close the hypothesis as an actionable candidate on currently
  available data; do not search variants; the exact missing input
  (broader/longer intraday coverage via the SAME existing free access)
  is named without being pursued this task.
- **PART 7 (journal/publication): DONE** — this entry;
  `TASK123_{TIMING_CORRECTION,FROZEN_PROTOCOL,OVERNIGHT_ATTENTION_RESULTS}.md`;
  small sanitized evidence (~186KB total) under
  `docs/research/evidence/task123/`; 12 new focused tests, all passing;
  correction appended to `TASK122_CANDIDATE_DECISION.md` (original
  preserved).

## Source / runtime / data manifest
New: `research/scripts/task123_overnight_diagnostic.py` (reuses
`talonx_v2.calendar.next_session_strictly_after` for calendar-correct
session pairing — the same frozen module V2 uses elsewhere — and pandas/
existing CSV data only; no new engine),
`tests/test_task123_causal_timing.py` (7 tests). Reused unmodified:
`results/task95g_broad_cross_sectional/_daily`,
`results/task107a_form4_feasibility/_prices` (both Alpaca SIP
`adjustment=all`, already-published), `results/task93_alpha_foundation/_canonical_data`
(Alpaca 1-min UNADJUSTED, already-published) — no new data acquisition.

## Tests / experiments / results / limitations
`pytest tests/test_task123_causal_timing.py
tests/test_task122_overnight_feasibility.py -q` → 12 passed. Two real,
fast (seconds), read-only computations over already-downloaded data.
Limitations, stated plainly: Track B's N=31 is a genuine small-sample
constraint from limited intraday coverage, not a computation error;
Track A's association, while statistically real, does not by itself
establish an executable product feature; the two tracks' return
definitions (total-return proxy vs. raw price return) are not directly
comparable, disclosed rather than reconciled.

## User-visible outcome
See `outcome.md`.

## Verdicts (kept separate)
- Part 1 (timing correction): `CAUSAL_DEFECT_CORRECTED`.
- Diagnostic (Track A): `ASSOCIATION_SUPPORTED` (qualified — materiality
  band only partially cleared).
- Actionable candidate (Track B): `NOT_SUPPORTED_UNDER_TESTED_CONTRACT`.

## Production effects, external sends, protected-state checks
None — research-only task. Release branch untouched (`f289869`
unchanged, verified at task start and end). No application process
started. Redis/production DBs re-verified clean at task end.

## Findings
- Fixed: Task 122's causal-execution defect (same-close entry from a
  same-close-only-known trigger).
- New: a real, sensitivity-robust, dependence-aware-CI-supported daily
  association (~17bps incremental overnight return, conditional on
  same-day volume) — a genuine research finding, but non-actionable by
  construction.
- New: the one genuinely causal actionable version of this mechanism,
  bounded by available intraday coverage, does not show a supported
  effect (N=31).
- Open: whether broader/longer intraday coverage (not currently
  available locally) would change the actionable answer — named, not
  pursued.
- Deferred: Task 122's Hypotheses 2/3 (52-week-high, turn-of-month) —
  untouched by this task, still available.

## Evidence links
`docs/research/{TASK123_TIMING_CORRECTION,TASK123_FROZEN_PROTOCOL,
TASK123_OVERNIGHT_ATTENTION_RESULTS}.md`,
`docs/research/evidence/task123/*` (this commit);
`results/task123_overnight_diagnostic/` (local, gitignored).

## Later corrections
None yet.
