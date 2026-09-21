# Task 71S-R1 -- Complete Live IEX Sparsity Semantics

**Mode:** PAPER / NO REAL CAPITAL. No order was submitted, no
broker-trading endpoint was called, and no live PIV trading session was
started at any point in this task. All Alpaca calls made by this task
were read-only historical-bars GETs (`feed=iex`).

## Phase A -- Evidence-quality audit: verdict NOT BLOCKED

Full detail in `evidence_quality_audit.md` and `stale_guard_path_audit.md`.

**Was Task 71S's "confirmed no trade" label justified? No.** The
classifier (`talonx_piv/gap_forensics.py`) only ever queried Alpaca's
**aggregate 1-minute bar** endpoint (`/v2/stocks/{symbol}/bars`); it never
queried the separate trade-level `/v2/stocks/{symbol}/trades` endpoint and
never cited any Alpaca-documented aggregation semantics. `CONFIRMED_NO_IEX_TRADE`
therefore overclaimed trade-level verification that was never performed.
**Correction applied:** renamed to `NO_IEX_BAR_OBSERVED` throughout
`gap_forensics.py`/`freshness.py`/the Task 71S test file -- the underlying
classification LOGIC is unchanged (it was never incorrect, only
overstated); only the name now says exactly what the evidence supports.

The stale-exclusion guard and `DATA_RECOVERED` were independently
re-verified: the guard is a pure subtractive filter with no import of, or
influence over, `talonx_quant/strategy.py`; recovery clears only the
freshness-layer exclusion and cannot bypass the two pre-existing,
unmodified readiness/warmup gates. No unrelated decision or order
behaviour was found in the `54ae8ff..d1764a8` diff.

## Phase B -- IEX suitability quantified for all 35 symbols

See `iex_coverage_by_symbol.csv` (full table), `iex_gap_distribution.csv`
(every individual regular-session gap >=2 minutes), and
`warmup_vs_live_suitability.csv` (Task 70S warmup readiness vs. this
task's live coverage, side by side).

**Headline findings:**

- **Premarket (04:00-09:29 ET) IEX-bar coverage is near-zero for
  essentially the entire universe** -- 0.0% to 2.7% (AAPL, the best case,
  had bars in only 9 of 330 premarket minutes). This is a market/venue
  characteristic (IEX carries very little premarket volume for these
  names), not a defect -- see `remaining_stabilization_issues.md` item 5
  for the honest limits of how far this task independently verified the
  mechanism.
- **Regular-session (09:30-15:59 ET) coverage varies enormously**: from
  17.9% (REGN) to 100.0% (7 symbols, including AAPL/NVDA/META/TSLA).
  476 individual gaps of >=2 consecutive missing minutes were found across
  the 35-symbol universe that single day.
- **17 of 35 symbols (49%) were historically warmup-READY (Task 70S: 120+
  bars from a 10-day lookback) yet had under 90% live regular-session
  coverage that same day** -- REGN (17.9%), VRTX (44.4%), COST (43.1%),
  HON (52.3%), GILD (53.1%) among the most extreme. This is the concrete,
  quantified proof that historical warmup readiness and live,
  minute-driven decision suitability are genuinely separate questions.
- **No suitability threshold was invented.** Per this task's own
  instruction, these are reported as measured coverage metrics; no new
  pass/fail cutoff was added anywhere in the runtime.

## REGN explanation

REGN can be (and was) historically warmup-READY while having only 70 of
390 live regular-session minutes with a bar (17.9% coverage, the worst in
the universe, with 40 individual gaps >=2 minutes and a longest single gap
of 33 minutes) because these are answers to two **different questions**:

- **Warmup readiness** (Task 70S, `talonx_piv/warmup.py` +
  `alpaca_historical_warmup.py`) asks: "does Alpaca's historical archive
  have >=120 1-minute bars for this symbol somewhere in the last ~10
  calendar days?" REGN's answer was yes (726 historical bars found at the
  causal cutoff) -- a genuinely thin-printing name can still easily
  accumulate 120 bars over 10 days.
- **Live, current-session decision suitability** asks a completely
  different, much narrower question: "is THIS symbol producing a NEW bar
  frequently enough, TODAY, for a 60-second-poll/120-second-threshold
  decision loop to trust it right now?" REGN's answer, for 2026-08-26, was
  clearly no for large stretches of the day -- it is simply a
  lower-IEX-print-frequency name on this specific venue, and that
  characteristic has nothing to do with how much HISTORY exists for it.

This task's fix (relaxing `_check_stale`'s ready-symbols gate) additionally
revealed that REGN's real problem was WORSE than Task 71S's own evidence
showed: only 5 of REGN's ~40 real regular-session gaps were ever observed
live, because the OLD code stopped monitoring REGN entirely the moment it
was excluded from `_ready_symbols` at 10:00 ET. See `runtime_state_transition_contract.md`.

## Runtime state contract before/after

See `runtime_state_transition_contract.md` for the full table. Summary:
added `NO_NEW_IEX_BAR` (never emitted, rolling-counter only), a paired
`DATA_NOT_READY reason=INSUFFICIENT_RECENT_IEX_PRINTS:{symbol}
status=EXCLUDED_FROM_DECISION_PATH` event alongside the existing
`STALE_DATA`, rolling per-symbol coverage tracking, session-identity
stamping on `freshness_report.json`, and (the core runtime fix)
observational monitoring that now continues for a symbol regardless of its
decision-readiness status.

## Files changed

- `talonx_piv/gap_forensics.py` -- `CONFIRMED_NO_IEX_TRADE` renamed to
  `NO_IEX_BAR_OBSERVED` (logic unchanged).
- `talonx_piv/freshness.py` -- `NO_IEX_BAR_OBSERVED`-referencing docstring
  updated; new `NO_NEW_IEX_BAR` constant; new `observe_quiet_tick`,
  `coverage_ratio` methods; rolling `_fresh_bar_count`/`_quiet_tick_count`/
  `_stale_episode_count` counters (session-scoped, reset with everything
  else); `snapshot()` extended with a `coverage` block.
- `talonx_piv/session_runner.py` -- `_check_stale` no longer skips
  symbols outside `_ready_symbols` (the core REGN-visibility fix); emits
  the new paired `DATA_NOT_READY` event at the stale transition; counts
  quiet ticks (never emits from them); `_write_freshness_report` now
  stamps `session_id`/`trading_date_et`/`runtime_sha`/`config_hash` (read
  back from `session_identity.json`, best-effort).
- `tests/test_task71s_data_freshness_stabilization.py` -- updated for the
  renamed constant (logic/assertions unchanged).
- `tests/test_task71s_r1_live_iex_semantics.py` (new) -- 18 tests.

No file in `talonx_quant/{strategy,indicators,consumer,config}.py` was
opened for editing. No order/broker-trading endpoint is reachable from any
new/changed code path.

## Tests and exact results

See `regression_test_results.txt`. Summary: 18/18 new Task 71S-R1 tests
pass; all directly-related pre-existing suites (198 tests across 12 files,
including Task 70S's 26 and Task 71S's own 29, all still passing) pass;
full-repository suite result compared honestly against the established
baseline (the one known `test_run_historical_regimes.py` failure).

## Proof of fail-closed behaviour

- `test_integration_no_candidate_from_repeatedly_monitored_not_ready_symbol`
  -- directly proves that widening observational monitoring to a
  not-ready symbol (this task's own fix) does NOT let it reach `on_bars`.
- `test_integration_data_not_ready_event_emitted_with_insufficient_prints_reason`
  -- proves the new decision-relevant event fires correctly at the
  transition.
- `stale_guard_path_audit.md` -- full static trace proving the exclusion
  guard cannot alter alpha, only prevent evaluation.
- Every existing Task 71S fail-closed test (no signal from stale data,
  recovery requires BOTH readiness gates, cross-date state not reused)
  re-verified passing unchanged.

## Limitations

See `remaining_stabilization_issues.md`. Most notably: no live suitability
threshold was invented (coverage is reported, not acted on); the
premarket near-zero-coverage explanation is plausible and
evidence-consistent but not independently reconstructed tick-by-tick;
trade-level (tick) data was never queried (a deliberate scope boundary,
now honestly disclosed rather than silently implied).

## Branch, starting/final SHA

- Branch: `research/talonx-strategy-validation`
- Starting HEAD: `d1764a8`
- Final HEAD: see the final chat report.

## Commit/push status; Final verdict

See the final chat-message report.
