# Task 120 — economic/product decision (Workstream B)

Companion entry: `../2026-09-12_task119a_corrections_integration/` (Workstream A + C).

## Objective and acceptance criteria
Produce ONE concrete economic/product decision from a single bounded,
predeclared analysis using existing free data — not a menu, not a repeat,
not a call to wait indefinitely for more live V2 trades.

## Timing
UTC ~01:00–02:00 (2026-09-12), within the same continuous session as the
companion Workstream A/C entry.

## Branch / SHA
Research `aef24c7` → this entry. No release-branch code change (research-
only; read-only against the frozen release worktree's already-published
data).

## Requested vs. completed scope
- B1: **DONE** — restated (not re-litigated) the product gap, citing
  Task 118H's own requirement-to-capability table.
- B2: **DONE** — protocol written and frozen BEFORE running
  (`docs/research/TASK120_PROTOCOL_39NAME_SCOPE_REPLAY.md`), then executed
  (`research/scripts/task120_39name_scope_replay.py`). Question: does the
  39-name LIVE execution scope (not the 620-name broad panel Task 115/116
  used) show a net edge at properly-powered history under the unchanged
  frozen contract? Reused tested primitives (`t112rp.runtime_episodes`,
  `t107b.build_returns`/`evaluate`) rather than writing new metric code.
  Not a repeat: different universe than Task 116 (39 vs. 620 names);
  different power than Task 118 Deliverable A (full history vs. N=10);
  different hypothesis than Task 118E/F (scope economics, not
  volatility-return association). No threshold touched, no new signal
  family, nothing filtered from this result.
- B3: **DONE** — reported N=27 (14 distinct issuers), issuer-block
  bootstrap CI, drop-top-1 sensitivity (predeclared), and an unplanned but
  directly relevant finding: 6 of the 39 live-scope names (including
  MSTR) have no local price coverage in the historical panel, so this
  N=27 (and every prior V2 backtest) is not fully representative of the
  live-traded population. Genuinely unused data checked: none beyond the
  coverage gap itself — the free-data alpha-space inventory (Task
  93–97/106A/95A–K) remains exhausted; what's new is a completeness gap in
  already-collected price data, not a new signal source.
- B4: **DONE** — **NO_SUPPORTED_STRATEGY_CHANGE**, with the smallest
  concrete evidence-acquisition task named (price-coverage backfill for 6
  names using the existing `composite-yf` adapter, then an unmodified
  re-run of this exact script) — not performed in this task, per "one
  recommended next task," effort estimated honestly as small.

## Source / runtime / data manifest
New: `docs/research/{TASK120_PROTOCOL_39NAME_SCOPE_REPLAY,TASK120_ECONOMIC_DECISION}.md`,
`research/scripts/task120_39name_scope_replay.py`. Reused unmodified:
`research/scripts/{task112r_parity.py,task107b_form4_cluster.py}` (loaded
as external modules via the same `_mod()` pattern Task 116 established,
`data_root` pointed at the frozen release worktree
`C:/workspace/TalonX`). Source data: `results/task107a_form4_feasibility/_build/form4_open_market_txn.parquet`
(Form 4 code-P transactions, already collected, free), `results/task95g_broad_cross_sectional/_daily`
(historical daily-bar price panel, already collected, free). Live 39-name
scope resolved dynamically via `talonx_ops.watchlist_coverage.build_coverage_map()`
(not hardcoded from memory) — confirmed 39 names, verified against the
real production resolver.

## Tests / experiments / results / limitations
One script run (no pytest suite — this is a research analysis, not
application code). Fingerprint gate checked first (`11107198c5b81237`,
matched — the script would have aborted `TASK120_SCOPE_REPLAY_FAIL`
otherwise). Result: N=27, net@20bps=−0.863%, PF=0.782, win=55.6%,
issuer-block bootstrap 95% CI=[−7.507%, +2.312%] (includes zero — genuinely
inconclusive), drop-top-1=+0.761% (sign does not flip on the single
largest-weight issuer). T116-comparable subwindow N=3 (too small on its
own, reported but not leaned on). Limitation, stated plainly: N=27 across
14 issuers is modest power; the coverage gap (6/39 names, including MSTR)
means even this result cannot be fully representative of the live-traded
population — this IS the finding, not a caveat to hide.

## User-visible outcome
See `outcome.md`.

## Verdicts (kept separate)
- Operational: N/A (research-only task, no application code touched).
- Economic verdict: **NO_SUPPORTED_STRATEGY_CHANGE** — inconclusive at
  current, properly-powered-as-far-as-coverage-allows evidence. No
  threshold/universe/sizing/holding-period change made or recommended. No
  win rate promised.

## Production effects, external sends, protected-state checks
None — read-only against already-collected free data in the release
worktree; no strategy code touched; no live session started; no external
send.

## Findings
- Fixed: n/a.
- Open: the 39-name-scope question itself remains genuinely inconclusive
  (CI includes zero) — not newly "open," simply not resolved by this
  task, exactly as its own protocol predeclared as one of four possible
  outcomes.
- New: the 6-name price-coverage gap (ABCL, ACHR, ADC, AGNC, MSTR, SHOP)
  in the historical panel used by every V2 backtest to date, MSTR
  specifically being materially relevant given its dominance of the live
  sample's composition (Task 118E/F).
- Deferred: the coverage backfill itself (named as the next task, not
  performed here).

## Evidence links
`docs/research/{TASK120_PROTOCOL_39NAME_SCOPE_REPLAY,TASK120_ECONOMIC_DECISION}.md`
(this commit); `results/task120_39name_scope_replay/{result.json,terminal_summary.txt}`
(local).

## Later corrections
None yet.
