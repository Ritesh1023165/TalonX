# Record

## Baseline verification (start of task)

- Research branch `research/talonx-profitability-2026-09` HEAD:
  `79c3591971d09064f8c44f8fed4dcc6ce7d8a71e` (matches expected exactly).
- Release worktree HEAD: `f28986999eec5e313cfc89db24e4dbacfb378891`
  (matches expected exactly), `git status --short` clean.
- No TalonX process running, no listening ports on 8787/8770/8760/
  8501. Redis reachable, 0 `talonx:*` keys.

## Actions taken, in order (all times UTC, 2026-09-13)

1. Read `task123_overnight_diagnostic.py`, `TASK123_FROZEN_PROTOCOL.md`,
   Task 124's acquisition spec, and `talonx_ops/watchlist_coverage.py`'s
   status field to confirm the exact contract and added-cohort
   candidates being extended.
2. Investigated the 5 Task-124-named candidate tickers'
   `talonx_ops.watchlist_coverage` metadata — discovered SKHY is listed
   as "SK Hynix Inc. (Korea Exchange)" in the watchlist's own exchange
   field, prompting a direct Alpaca daily-bar listing-window check for
   SKHY and BLSH BEFORE freezing the added cohort.
3. Ran `research/scripts/task125_feed_provenance_probe.py`:
   - Code-based finding: `task63_download_alpaca.py`,
     `task61r_download_alpaca.py`, and `task7b_alpaca_long_history/
     download_summary.json`'s schema all route through the shared
     `scripts/download_historical_1m.py::fetch_alpaca`, whose Alpaca
     request params never include a `feed` key.
   - Confirmatory probe (AAPL, 2025-02-05, ~08:18 UTC): the
     omitted-feed response is bar-for-bar identical to explicit
     `feed=sip` (841 bars, matching SHA-256 over every OHLCV tuple),
     differs from `feed=iex` (388 bars) — conclusion: `task93_canonical_v1`
     is SIP data.
   - Listing-window checks: SKHY's first Alpaca bar is 2026-07-10
     (entirely after the 2025-08-14 window end); BLSH's is 2025-08-13
     (one day before the window end, zero prior trailing history).
     BABA/SHOP/SPCX confirmed 656/656 daily bars across the full
     2023-01-03→2025-08-14 window.
4. Wrote and committed `docs/research/TASK125_FROZEN_EXTENSION_PROTOCOL.md`
   (commit `bfd1205`, pushed) — BEFORE any return was computed. Freezes
   the added cohort as BABA/SHOP/SPCX only, the acquisition range
   (2022-12-01→2025-08-14), feed=sip/adjustment=raw, decision criteria,
   and the 4-cohort evaluation design.
5. Wrote `research/scripts/task125_acquire_intraday.py` (resumable,
   per-symbol/calendar-year-chunk partitioned downloader). Ran
   `--pilot` (1 partition, 1.10s), then `--limit 4` (4 more partitions
   including one full-year partition, 29.1s total, revised estimate
   400s/6.7min for the remaining 55), then the full remaining
   acquisition: **60/60 partitions completed, 0 failures, 506.3s**.
6. Wrote and ran `research/scripts/task125_merge_and_validate.py` —
   merged all partitions per symbol, deduplicated/sorted, checked for
   non-positive prices/negative volume (none found), flagged 2
   single-bar >30% jumps (AVGO 2024-07-15, NVDA 2024-06-10 — confirmed
   these are the symbols' real, publicly documented 10-for-1 stock
   splits, not data defects).
7. Wrote `tests/test_task125_evaluation_fixture.py` (5 deterministic
   fixture tests) and ran them BEFORE the real evaluation — all
   passed.
8. Wrote `research/scripts/task125_overnight_evaluation.py`, reusing
   `task123_overnight_diagnostic.py`'s frozen constants and
   `_date_block_bootstrap` unchanged. First run used a naive per-date
   `raw[raw["session_date"]==d]` re-filter inside the per-symbol loop
   (the same pattern Task 123's original code used) — on the expanded
   ~700-date/~500k-row-per-symbol window this was too slow (killed
   after >3 minutes with no cohort complete). Rewrote to a single
   vectorized groupby/boolean-mask pass per symbol (open-bar lookup,
   entry-bar lookup, and cutoff-window cumulative volume each computed
   once over the whole frame, not re-filtered per date) — re-ran the
   fixture tests (still 5/5 pass) and the full evaluation completed in
   **2m1.7s**.
9. Ran the frozen evaluation once across all 4 cohorts (§Results
   below). Verified Cohort D reproduces Task 123's original Track B
   numbers bit-for-bit (579/31/-0.5504%/[-2.1445%,+1.2090%]) —
   confirms feed consistency and implementation fidelity.
10. Wrote `docs/research/TASK125_DATA_ACCEPTANCE.md` and
    `docs/research/TASK125_OVERNIGHT_ACTIONABLE_RESULTS.md`, applying
    the frozen decision criteria without modification.
11. Updated `docs/research/PRODUCT_STATUS.md` and
    `docs/research/TALONX_RESEARCH_LEDGER.md` with concise Task
    123/124/125 pointer entries (123/124 had not yet been added to the
    ledger).
12. Copied evidence (`feed_provenance_probe.json`,
    `acquisition_progress.json`, `data_acceptance.json`,
    `task125_evaluation_results.json` — 4.6KB/42KB/13KB/26KB, all well
    under the evidence-size convention) to
    `docs/research/evidence/task125/`.
13. Re-verified production/Redis/process preservation (same result as
    baseline).

## Results summary (see `TASK125_OVERNIGHT_ACTIONABLE_RESULTS.md` for full detail)

| cohort | eligible | triggers | incremental net | 95% CI |
|---|---:|---:|---:|---|
| A (primary): original 12, expanded 2023–2025-08-14 | 3,201 | 158 | −0.2284% | [−0.7946%,+0.3458%] |
| B: added (BABA/SHOP/SPCX) | 395 | 31 | +0.2746% | [−0.4970%,+1.0535%] |
| C: combined (secondary) | 3,596 | 189 | −0.1527% | [−0.6333%,+0.3531%] |
| D: original sub-window, verified SIP | 579 | 31 | −0.5504% | [−2.1445%,+1.2090%] (== Task 123 exactly) |

Statistical verdict (Cohort A): `INCONCLUSIVE` (CI includes zero).
Product verdict: `DO_NOT_ADVANCE` (negative on both incremental and
absolute basis; frozen criteria's "negative or economically inadequate
→ close this contract" applies).

## Production preservation (end of task)

Unchanged from baseline — no process started, no port opened, Redis
`talonx:*` key count still 0, release worktree still clean at
`f28986999eec5e313cfc89db24e4dbacfb378891`. No background tasks left
running (the initial slow-evaluation background run was explicitly
stopped via `TaskStop` before the vectorized rewrite was re-run in the
foreground).
