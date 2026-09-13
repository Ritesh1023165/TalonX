# Record

## Baseline verification (start of task)

- Research branch HEAD: `7afcb0d5ccd630434c44655bb2b6a5133ab58cfc`
  (matches expected exactly).
- Release worktree HEAD: `f28986999eec5e313cfc89db24e4dbacfb378891`
  (matches expected exactly), clean throughout. Neither branch reset.

## Actions taken, in order

1. Wrote and committed `docs/research/TASK130A_REPAIR_PROTOCOL.md`
   (commit `9d1d795`, pushed) — the review-hold correction blockquote
   was also appended to `TASK130_OPTION_A_ECONOMIC_DECISION.md` at the
   same commit, original content preserved unchanged below it. BEFORE
   any corrected return was computed.
2. Wrote `research/scripts/task130a_prospective_replay.py` — a new,
   isolated, session-by-session driver (real `exchange_calendars`
   XNYS sessions; production-adjacent primitives reused unmodified:
   `cluster_engine.detect_episodes`, `liquidity.evaluate_liquidity`,
   `quant_bridge.build_signal`, `brain_bridge.contextualize`,
   `calendar.add_sessions`/`next_session_strictly_after`) implementing
   the entry gate IN-LINE: cash/slot RESERVATION on intent creation,
   consumption only on actual admitted entry, deterministic
   `(eligible_entry_session, issuer_cik, symbol)` ordering,
   entry-before-same-session-exit-crediting, hard
   `SKIPPED_INSUFFICIENT_CAPITAL` (no partial fills), and a
   `OpenPosition`-dict-based position model that structurally cannot
   phantom-settle an exit for a never-opened episode.
3. Wrote `tests/test_task130a_prospective_replay.py` (9 tests) using
   REAL XNYS session dates with small synthetic bars/records injected
   via new `bars_override`/`records_override` parameters added to
   `run_replay` for testability. Two bugs found and fixed BEFORE any
   result was trusted: (a) the synthetic bar fixture and — critically —
   the main script's own `load_bars()` were both missing the `volume`
   column `evaluate_liquidity` requires (would have crashed the real
   run too, caught by the test suite first); (b) an initial cold-start
   test used activation dates outside the 45-day causal lookback,
   silently producing zero episodes rather than testing the intended
   scenario — fixed to place the activation date within the lookback
   but still before the window's own first session. **9/9 pass.**
4. Ran the real evaluation (~10s) over the full frozen window
   (2024-09-01 → 2026-03-31), 626-name Discovery Universe v1 — hit one
   real-data issue not present in tests (an empty placeholder CSV for
   an uncovered symbol, `task107a_prices.py`'s own "EMPTY\n" convention)
   — fixed `load_bars` to skip empty/undersized files gracefully, then
   re-ran successfully.
5. Wrote `research/scripts/task130a_identity_and_stats.py` — Part 7
   (issuer-CIK ambiguity classification from accession-level
   `issuer_name`/date-range evidence, scoped to the SAME 626-name
   Discovery Universe v1 Task 130's own manifest used — an initial run
   incorrectly scanned the full, unscoped Form 4 parquet [229
   ambiguous symbols] before being corrected to the frozen 626-name
   scope [35, matching Task 130's manifest exactly]) and Part 8 (full
   corrected stats: both bootstraps, the ORIGINAL trade-count-ranked
   sensitivity preserved unchanged, plus a NEW supplemental P&L-ranked
   sensitivity, clearly labelled as such).
6. Computed the per-episode comparison (Part 9) directly: the
   corrected, in-line-gated replay's 153 closed trades are IDENTICAL
   (same `episode_id`s, same entry/exit sessions, same P&L to full
   precision) to Task 130's original post-hoc-filtered Track B — 0
   newly excluded, 0 newly admitted, 0 changed. Explained (not just
   observed): Task 130's own funnel already showed capacity was never
   binding in this window, so an in-line gate and a post-hoc filter
   converge on the same admitted set here — disclosed as a
   window-specific finding, not a general equivalence claim.
7. Computed drawdown peak/trough/recovery from the real daily-marked
   equity series: peak 2026-03-04 → trough 2026-03-20, −2.7478%, not
   recovered within the window (an honest window-boundary effect, the
   trough is only 11 sessions before the window's own end).
8. Wrote `docs/research/TASK130A_PROSPECTIVE_REPLAY_ACCEPTANCE.md`
   (Parts 2-6, 9) and `TASK130A_CORRECTED_ECONOMIC_DECISION.md`
   (Parts 7, 8, 9's comparison, 10's separate-gate verdict table).
9. Copied compact evidence (`closed_trades.json` 58KB,
   `corrected_stats.json` 2.2KB, `dispositions.json` 16.8KB,
   `identity_reconciliation.json` 29.6KB, `summary.json` 1KB,
   `episode_comparison.json` 0.2KB — the 129KB `daily_marks.json`
   stays local only, over this program's evidence-size convention) to
   `docs/research/evidence/task130a/`.
10. Re-verified production/Redis/process preservation (same result as
    baseline).

## Production preservation (end of task)

Unchanged from baseline — no process started, no port opened, Redis
`talonx:*` key count still 0, release worktree still clean at
`f28986999eec5e313cfc89db24e4dbacfb378891`. No SQLite ledger of any
kind was written by this task's driver (in-memory state only, by
design — see the acceptance document's disclosed scope limitation);
nothing resembling `v2_lane.db` was created or touched.
