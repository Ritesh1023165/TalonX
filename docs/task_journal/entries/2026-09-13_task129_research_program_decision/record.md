# Record

## Baseline verification (start of task)

- Research branch `research/talonx-profitability-2026-09` HEAD:
  `8f9dfc0b88d87730dc1f9c2649910d335ef8aa12` (matches expected exactly).
- Release worktree HEAD: `f28986999eec5e313cfc89db24e4dbacfb378891`
  (matches expected exactly), `git status --short` clean.
- No TalonX process running, no listening ports on 8787/8770/8760/
  8501. Redis reachable, 0 `talonx:*` keys.

## Actions taken, in order

1. Per the task's own explicit instruction ("start with the index...
   do not read every repository file indiscriminately"), consolidated
   the evidence from `docs/research/PRODUCT_STATUS.md`'s
   already-authoritative per-mechanism table (verified fresh, just
   written across Tasks 121A-128 within this same session) plus
   `docs/task_journal/TASK_INDEX.md` and
   `docs/research/TALONX_RESEARCH_LEDGER.md` — no new file reads were
   needed to resolve any material ambiguity, since every cited result
   had already been directly verified (source-code-read, primary-
   source-checked, or computed) earlier in this same continuous
   session.
2. Verified the roadmap start date (2026-09-11, Task 118H's product
   roadmap decision) via `TASK_INDEX.md` — retained, not reset.
3. Built `docs/research/TASK129_EVIDENCE_MATRIX.csv` — one row per
   distinct mechanism (10 rows: grouped rejected price/volume families,
   Original, Experimental, V2 configured-scope, V2 broader populations,
   overnight-attention Track A, overnight-attention Track B, 52-week-
   high, no-selection benchmark, turn-of-month), each with the required
   11 fields.
4. Applied the six-point next-experiment gate (Part 4 of the prompt) to
   every remaining candidate (turn-of-month, longer-horizon 52-week-
   high, further V2 live accumulation, a new free price/volume
   hypothesis) — none passed; each blocked by a product decision, a
   data ceiling (only 12 non-overlapping 6-month macro-blocks
   available), or the explicitly-excluded indefinite-live-observation
   substitute.
5. Named 5 concrete root causes of programme iteration, each grounded
   in a specific, already-documented repository event from this
   session (stale-worktree parity/Task121A, late accounting
   corrections/Tasks 120-128, unsupported product-restriction
   inferences/Task126, delayed data-extension checks/Tasks123-125,
   unverified provenance/Tasks124-125), each with a lightweight
   prevention rule reusing an existing mechanism (no new tooling
   proposed).
6. Wrote `docs/research/TASK129_RESEARCH_PROGRAM_DECISION.md` (1,421
   words, within the ≤1,500-word guidance) reaching
   `PAUSE_ALPHA_RESEARCH_UNDER_CURRENT_CONSTRAINTS`, with the finite
   future budget, explicit stop condition, and three-row roadmap.
7. Added a concise, dated correction blockquote to
   `docs/research/TASK128_BASELINE_PRODUCT_DECISION.md` (Part 8's four
   required clarifications) — no Task 128 calculation reopened or
   rerun.
8. Updated `docs/research/PRODUCT_STATUS.md` (header + a pointer
   paragraph to the Task 129 decision, plus the existing "Full
   evidence" list) and `docs/research/TALONX_RESEARCH_LEDGER.md` (a
   concise pointer entry) — minimal, not a rewrite of the underlying
   per-mechanism rows, per the task's own "only enough to point to the
   authoritative decision" instruction.
9. Updated `docs/task_journal/TASK_INDEX.md` with a Task 129 row.
10. Re-verified production/Redis/process preservation (same result as
    baseline). No backtest, no new download, no application change,
    no code beyond documentation was touched in this task.

## Production preservation (end of task)

Unchanged from baseline — no process started, no port opened, Redis
`talonx:*` key count still 0, release worktree still clean at
`f28986999eec5e313cfc89db24e4dbacfb378891`.
