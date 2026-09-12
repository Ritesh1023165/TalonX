# Task 120A–C — corrected baseline and economic decision

## Objective and acceptance criteria
Correct Task 120's factual/methodological/coverage/cost errors (A),
produce a reproducible chronological V2 baseline reusing the existing
replay engine (B), and close the Original/Experimental exact-contract
evidence question with one product decision (C) — computed evidence
prioritized over documentation.

## Timing
UTC start ~23:54 (2026-09-11, continuing the same overnight session); end
~03:00 (2026-09-12).

## Branch / SHA
Release: verified `f28986999eec5e313cfc89db24e4dbacfb378891` unchanged —
**no release-branch work this task** (research-only, per the task's own
authorization: "research fixes, isolated analyses... no dashboard...").
Research `8bfbaa8` → this entry.

## Requested vs. completed scope
- **A: DONE.** A1 corrected — the N=10/−2.93% figure is a historical
  chronological replay (2024-09-01→2026-03-31), not live trades; Friday's
  live ledger was confirmed zero trades (unchanged fact, now correctly
  attributed). A2 corrected — Task 120's own script used an episode-return
  study, not the chronological replay engine; relabelled
  `EPISODE_RETURN_STUDY_NOT_CHRONOLOGICAL_REPLAY`; "first properly
  powered"/"fully representative" claims withdrawn. A3 done — frozen
  `docs/research/SCOPE_MANIFEST_39NAME.json`, reused statically by both
  B2 and B3. A4 done — `docs/research/TASK120A_COVERAGE_RECONCILIATION.md`;
  verified directly (`ls` on both bar directories) that ABCL/ACHR/ADC/
  AGNC/MSTR all have coverage in `results/task107a_form4_feasibility/_prices`
  (Task 120 checked only `_daily`); only SHOP genuinely uncovered
  (unchanged from Task 118 Deliverable A). No data retrieval needed. A5
  done — cost math traced and published per-trade (gross/entry-cost/
  exit-cost/total-cost/net, 20bps round-trip, applied once — verified by
  the B2 exact-match reproduction below); 7 focused tests added
  (`tests/test_task120a_cost_reconciliation.py`, all pass).
- **B: DONE.** B1 — reused `talonx_research.replay_engine.run_chronological_replay`
  verbatim (unchanged); file hashes recorded for `service.py`/
  `form4_source.py`/`store.py`/`config.py` (byte-identical to release) and
  `calendar.py`/`paper.py` (hash differs, content diffed and confirmed
  identical — CRLF/LF only); no branch merge. B2 — re-ran Task 118
  Deliverable A's exact config fresh: **N=10, net@20bps=−2.9261%,
  PF≈0.3154 — EXACT MATCH** against the stored artifact (4+ significant
  figures on net expectancy; PF differs only in the 7th digit, floating-
  point summation order). B3 — ran the longest supported window
  (2019-01-01→2026-03-31) at $300,000 (primary, per this task's
  instruction) and $10,000,000 (capital-isolation comparison): **N=57
  both sizings (capital not binding)**, net@20bps=−0.8478%, PF=0.766, win
  rate=49.1%, 19 distinct issuers, ending equity $296,307.36. B4 —full
  episode-disposition/trade accounting published (57 ENTERED, 41
  SKIPPED_ENTRY_STALE, 4 liquidity-gate skips, 2 cooldown skips, 1
  insufficient-history, 1 no-prior-bars; 0 exit-unresolved, 0 open-at-end);
  equity = cash + marked open value (0 open at window end, so equity =
  ending cash exactly); daily mark-to-market explicitly NOT computed
  (labelled, not silently substituted) — a trade-event cash curve is
  published instead. B5 — predeclared issuer-block bootstrap (5,000 reps,
  seed 118120): **95% CI = [−4.571%, +1.109%], includes zero**; drop-
  top-1-issuer (ADC, 17/57) sensitivity computed (mean moves MORE
  negative without ADC, −1.384% — sign does not flip either way);
  effective-independent-groups (19) reported explicitly, distinct from N.
- **C: DONE.** C1 — Original: **Task 93 IS the exact current frozen
  contract** (`2ae6216bca70`, verified unchanged live this task via
  `talonx_ops.prospective.V1_FINGERPRINT_EXPECTED`), found 1 trade in
  ~18.7 months across 35–45 symbols — cited, not rerun (**ROUTE 1**).
  Experimental: no exact-contract backtest of the combined
  `EXPERIMENTAL_RELAXED_V1` gate set exists; Task 93's own volatility-only
  counterfactual is closely related but not exact (**ROUTE 3** — smallest
  next action named: reuse Task 93's already-built `task93_canonical_v1`
  dataset + harness with Experimental's exact gate combination; not
  performed tonight, per "do not build a new research framework
  overnight"). C3 — **`INSUFFICIENT_EVIDENCE_WITH_ONE_SPECIFIC_NEXT_ACTION`**,
  full reasoning in `docs/research/TASK120ABC_CORRECTED_BASELINE_AND_DECISION.md`.
- **Product status page**: `docs/research/PRODUCT_STATUS.md` (new, small,
  linked from `NEXT_SESSION_HANDOFF.md`, not a documentation-tree
  rewrite).

## Source / runtime / data manifest
New: `research/scripts/task120b_chronological_baseline.py` (reuses
`talonx_research.replay_engine.run_chronological_replay` and
`talonx_v2.form4_source` unmodified), `tests/test_task120a_cost_reconciliation.py`
(7 tests), `docs/research/{SCOPE_MANIFEST_39NAME.json,
TASK120A_COVERAGE_RECONCILIATION.md,TASK120ABC_CORRECTED_BASELINE_AND_DECISION.md,
PRODUCT_STATUS.md}`, `docs/research/evidence/task120b/` (4 small sanitized
JSON summaries, ~62KB total, committed). Reused unmodified:
`talonx_research/replay_engine.py`, `talonx_v2/{service.py,form4_source.py,
store.py,config.py,calendar.py,paper.py}` (already byte-copied from
release in Task 118). Source data: the same frozen, already-published free
artifacts Task 118 Deliverable A used (`results/task107a_form4_feasibility/_build/form4_open_market_txn.parquet`,
`results/task95g_broad_cross_sectional/_daily`,
`results/task107a_form4_feasibility/_prices`) — no new data collection.

## Tests / experiments / results / limitations
`pytest tests/test_task120a_cost_reconciliation.py -q` → 7 passed. Two
real replay runs executed (B2 overlap, B3 full-window ×2 sizings) —
fingerprint-gated (`11107198c5b81237`, matched both times). Limitations,
stated plainly per this task's own closing line ("a negative or
inconclusive result is an acceptable research outcome; an unreconciled
number presented as a definitive baseline is not"): B3's N=57/19-issuer
result is genuinely inconclusive (CI includes zero) — not hidden, not
reframed as a finding. Experimental's exact-contract question remains
open — its next action is named, not resolved tonight.

## User-visible outcome
See `outcome.md`.

## Verdicts (kept separate)
- A: `TASK120_CORRECTIONS_COMPLETE`.
- B: `CHRONOLOGICAL_BASELINE_COMPLETE_INCONCLUSIVE` (N=57, CI includes
  zero — a completed, properly-powered, bounded result, not a partial
  report).
- C: `INSUFFICIENT_EVIDENCE_WITH_ONE_SPECIFIC_NEXT_ACTION`.

## Production effects, external sends, protected-state checks
None — research-only task. Release branch untouched (verified `f289869`
unchanged at task end). No application process started. Redis/production
state re-verified clean (see outcome.md §9).

## Findings
- Fixed: Task 120's historical/live mislabelling, episode-study/
  chronological-replay conflation, 6-name coverage-check bug, and cost-
  path ambiguity (all A1–A5).
- New: Original's exact-contract evidence (Task 93) was already
  sufficient and had simply not been cited by name in this session's
  economic-decision docs until now.
- Open: Experimental's exact-contract economics (named next action, not
  resolved).
- Deferred: none within this task's own scope.

## Evidence links
`docs/research/{TASK120ABC_CORRECTED_BASELINE_AND_DECISION,
TASK120A_COVERAGE_RECONCILIATION,PRODUCT_STATUS,SCOPE_MANIFEST_39NAME}.{md,json}`,
`docs/research/evidence/task120b/*.json` (this commit);
`results/task120b_chronological_baseline/` (local, full artifacts incl.
raw replay JSON and isolated `.db` ledgers — never committed).

## Later corrections
None yet.
