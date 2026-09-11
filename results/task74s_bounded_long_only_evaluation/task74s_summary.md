# Task 74S — Bounded Multi-Symbol Long-Only Evaluation

**Label: DEVELOPMENT/ROBUSTNESS EVALUATION.**

## Stage 0 — Verify and inventory: PASS
Branch/HEAD/clean-tree/origin-sync confirmed at `848de0d`. No concurrent session. Scanner identity,
long-only lifecycle, and cost interpretation re-confirmed unchanged. **Universe resolved to the
10-symbol frozen research universe** (`data/historical_1m/task7b_alpaca_long_history`) from documented
ledger provenance alone -- continuously reused as the "canonical baseline" since Task 4/7B through
Task 63R, versus the 35-symbol operational universe whose one research trial (Task 37) concluded
`LIKELY_TOO_SPARSE`. Zero holdout overlap (holdouts contain only the other 25 symbols). See
`stage0_verification_and_inventory.md`.

## Stage 1 — Preregister before replay: PASS
Universe, full ~1-year window, 13 fixed calendar-month buckets (August from the 15th), primary cost
config (unchanged, 20bps round-trip), and an analytically-justified secondary cost-sensitivity grid
(zero/half/baseline/double, computed from the primary replay's raw trade prices rather than 3
additional ~4-hour replays -- justified directly from `talonx_backtest/execution.py`, where trade
identification is provably cost-independent) were all fixed and committed (`4a3fc3e`, pushed) **before**
any replay was run. No trade-count threshold invented. See `preregistration.json`,
`universe_manifest.csv`, `data_manifest.csv`, `evaluation_protocol.md`.

## Stage 2 — Full causal pre-roll and integrity checks: PASS
Task 73S's 3 control-fixture tests re-run and passing; all 10 symbols pass data-quality checks (zero
duplicate/out-of-order timestamps, zero critical corruption). No synthetic pre-roll manufactured; HTF
warmup confirmed immaterial for a ~1-year window. Replay launched as a single background process;
launch manifest committed (`f7ff865`, pushed) before any result existed. See
`stage2_integrity_and_preroll.md`, `stage2_data_quality_report.csv`, `stage3_replay_launch_manifest.json`.

## Stage 3 — One frozen replay: PASS
10 symbols, 1,903,044 bars, single chronological pass, completed cleanly (exit 0). **Result: zero
trades executed, every symbol, entire ~1-year window.** 93.63% of bars rejected `LOW_VOLATILITY`
before any candidate formed; of 5,021 raw candidates (near-even bullish/bearish), 72.5% rejected
`LOW_CONFLUENCE`; only 12 bullish candidates ever cleared the confluence threshold, only 4 in the
regular session, and every one of those 4 failed a further gate (HTF trend or R:R geometry). Zero
bullish signals ever published; the 3 published signals are all bearish, correctly rejected as
`NO_ACTIVE_POSITION`. This generalizes Task 73S's single-symbol finding to the full preregistered
scope. No correctness defect found. See `stage3_zero_trade_diagnosis.md`, `stage3_funnel.csv`,
`stage3_per_symbol_summary.csv`, `stage3_per_bucket_summary.csv`.

## Stage 4 — Economics and robustness: COMPLETE (N/A)
Zero trades → economics N/A, secondary cost-sensitivity grid N/A (nothing to recompute). Qualitative
robustness: the bottleneck is structural and consistent across all 10 symbols and all 13 calendar
buckets; concentration of raw-candidate volume in STX/AMD does not change the outcome. See
`stage4_economics_and_robustness.md`.

## Stage 5 — Conclusion
Separate verdicts: **data/replay correctness PASS**; **signal frequency LIKELY_TOO_SPARSE**; **net
economics N/A**; **evidence strength NONE** (no trade population exists to assess). **Overall outcome:
`NO_ELIGIBLE_LONG_SETUPS`. Profitability verdict: `INCONCLUSIVE`.** Not reframed as validated alpha in
either direction. No universe/date/parameter extension made based on this result. See
`stage5_conclusion.md`.

## Verification and git
- `tests/test_task73s_control_fixture.py`: 3 passed (before the replay).
- Full suite after the replay: **2168 passed, 1 skipped, 10 xfailed** -- identical to Task 73S's own
  final count; zero regressions introduced by this task (no strategy/harness/protected code was
  changed).
- **Known, pre-existing environment gap disclosed (not caused by this task)**: `tests/test_task61_validation_protocol.py`
  and `tests/test_task61r_temporal_freeze.py` fail to *collect* (not fail as tests) due to a missing
  optional dependency, `exchange-calendars` (declared only in `research/requirements-task61.txt`, not
  the main runtime/dev requirements). This dependency was present as of Task 73S's clean run two days
  ago and is absent now; this task touched no dependency file and ran no install/uninstall. Excluded
  from the full-suite run via `--ignore` and reported here rather than silently "fixed."
- Protected files (`talonx_quant/{strategy,indicators,consumer,config}.py`,
  `talonx_piv/{eod_lifecycle,session_runner,cli,events}.py`): zero diff since `848de0d`.
- Zero holdout access, zero broker/Telegram/Gemini calls, zero live session activity.
- Two raw telemetry files (163MB, 84MB) are excluded from git for repository-hygiene reasons (documented
  with SHA-256 hashes and row counts in `stage3_raw_output_manifest.md`); every number derived from
  them is captured in small, committed, derived artifacts.
- Commits: `4a3fc3e` (Stage 0/1, preregistration), `f7ff865` (Stage 2, launch manifest), plus this
  final commit (Stage 3/4/5 evidence). All pushed to `origin/research/talonx-strategy-validation`.

## Recommendation
See `next_research_recommendation.md`: do not extend universe/dates/parameters based on this result;
either run a non-tuning diagnostic into why `LOW_VOLATILITY`/`LOW_CONFLUENCE` bind this hard for this
universe/period, or pursue the separate validation-window track -- both out of scope for this task.
