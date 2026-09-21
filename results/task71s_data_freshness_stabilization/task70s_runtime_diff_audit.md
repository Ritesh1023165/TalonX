# Phase A -- Task 70S Runtime Integration Audit (mandatory, before any new edits)

## 1-2. Branch/HEAD/clean status; complete diff reviewed

- Branch: `research/talonx-strategy-validation`
- Starting HEAD: `54ae8ff` (confirmed via `git rev-parse HEAD` before any
  edit; working tree confirmed clean via `git status --short`).
- Full diff `636fa9c..54ae8ff` reviewed (`git diff 636fa9c..54ae8ff --stat`):
  14 files changed, all either evidence/results artifacts, the new Task 70S
  test file, or exactly the 4 `talonx_piv` files this task's own spec
  named for review. No file outside `talonx_piv/` and the results/tests
  directories was touched by Task 70S.

## 3. What changed in each of the 4 named files

**`talonx_piv/cli.py`** -- exactly one line:
`DecisionEngine(redis_client, bus, lifecycle)` became
`DecisionEngine(redis_client, bus, lifecycle, piv_config=config)`. Pure
dependency-injection wiring; no control flow changed.

**`talonx_piv/decision_engine.py`** -- `DecisionEngine` gained one new
optional dataclass field (`piv_config: PivConfig | None = None`, default
preserves old behavior for every caller that omits it) and `start()`
gained one new optional parameter (`now: datetime | None = None`,
test-only, threaded through to `preseed_and_verify`). The `on_bars`
method -- the ONLY method that touches candidate generation, signal
publication, or order submission -- has ZERO lines changed in this diff
(confirmed by grep: no `+`/`-` line inside `on_bars`'s body appears in the
diff at all).

**`talonx_piv/warmup.py`** -- `preseed_and_verify` gained new OPTIONAL
keyword-only parameters (`piv_config`, `now`, `alpaca_transport`,
`alpaca_sleep_fn`), all defaulted so the function's behavior is BYTE-FOR-BYTE
identical for any caller that omits them (verified: `git diff` shows the
readiness-computation block itself -- `ready_1m`, `ready_htf`, `ready =`,
`reason =`, `bar_count_1m =`, `htf_sma_200 =` -- has ZERO added or removed
lines; only pure additions surround it). `WarmupCheck` gained 5 new
default-valued fields (evidence only: `alpaca_attempted`, `alpaca_status`,
`alpaca_bar_count`, `alpaca_reason`, `bar_count_1m_source`) -- none of
these feed back into `ready`/`reason`, which remain computed exactly as
before.

**`talonx_piv/alpaca_historical_warmup.py`** -- the original Task 69Q
`fetch_1m_bars` prototype was, by its own module docstring, "NOT wired
into the live warmup path" before Task 70S -- i.e. dead code in production,
reachable only from its own test file. Every new function added
(`run_alpaca_1m_warmup`, `_sanitize`, `_get_with_retry`, etc.) was
UNREACHABLE from any live code path until `warmup.py` started importing
and calling `run_alpaca_1m_warmup` -- so this file's own diff, however
large, could not by itself have changed any previously-live behavior.

## 4. Proof that the changes affect ONLY historical warmup / provider selection

- **Candidate generation / alpha decisions / strategy thresholds:**
  `talonx_quant/strategy.py`, `indicators.py`, `consumer.py`, `config.py`
  do not appear anywhere in the `636fa9c..54ae8ff` diff (confirmed:
  `git diff 636fa9c..54ae8ff --stat` lists only `talonx_piv/*` and
  results/tests files).
- **Signal publication / order submission / position lifecycle:**
  `talonx_piv/decision_engine.py`'s `on_bars` (the method that drives
  QuantScanner's live tick path and reaches signal publication) is
  untouched (see above). `talonx_piv/broker.py` and `talonx_piv/lifecycle.py`
  do not appear in the diff at all.
- **EOD behaviour:** `talonx_piv/cli.py`'s `eod` branch, and
  `session_runner.py`'s `flatten_all`/`_write_funnel_report` calls, are
  untouched by the Task 70S diff.
- **Warmup-only surface:** every changed line is reachable only from
  `preseed_and_verify`'s NEW, opt-in Alpaca-fetch branch (gated on
  `piv_config is not None and key_id and secret_key`) or from evidence
  fields that are read, never used for control flow.

**Verdict: Task 70S's integration is confined to historical warmup /
1-minute-buffer provider selection, exactly as its own spec required.
NOT BLOCKED -- proceeding to Phase B.**

## 5. Confirmation that the live 35/35 result used bars strictly before the causal cutoff

Re-inspected `results/task70s_piv_stabilization_phase1/readiness_by_symbol.csv`:
every one of the 35 rows has `requested_end` equal to
`2026-08-26T08:19:00Z` (the exact causal cutoff) and `future_bars_dropped`
equal to `0`. `causal_boundary_evidence.json` (same directory) documents
both the `end`-parameter mechanism and the independent post-fetch
`_sanitize()` defense-in-depth re-check. No re-verification issue found;
this task's own new `gap_forensics.py` module (built for a different,
retrospective purpose) independently re-confirms the underlying historical
archive's minute-level correctness by construction (its classification
logic depends on correctly timezone-converting and comparing real
historical bar timestamps, and produced internally consistent, expected
results across all 72+121 gap observations -- see
`stale_event_timeline.csv` / `missing_opening_minutes.csv`).

## 6. Unrelated runtime behaviour changed?

None found. Proceeding with Task 71S's Phase B/C/D work.
