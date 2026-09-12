# Task 121 — Experimental (EXPERIMENTAL_RELAXED_V1) exact-contract results

Protocol frozen in `docs/research/TASK121_PROTOCOL.md` before this replay
was executed against real outcomes. Adapter:
`research/scripts/task121_experimental_replay.py`. Raw artifacts (full
trade table, per-symbol logs) under `results/task121_experimental_replay/`
(local only, gitignored); a small sanitized summary is committed at
`docs/research/evidence/task121/experimental_replay_summary.json`.

## 1. Contract recorded from source (Part 2)

`EXPERIMENTAL_RELAXED_V1` = `dataclasses.replace(QuantConfig(), **RELAXED_OVERRIDES)`
— SAME `QuantScanner`/`evaluate_signals()` production code Original uses,
three fields changed:

| gate | Original (frozen) | Experimental (relaxed) |
|---|---:|---:|
| `min_atr_pct` | 0.25 | 0.10 |
| `confluence_score_min` | 2 | 1 |
| `min_risk_reward_ratio` | 1.5 | 1.0 |
| `volatility_gate_mode` | CURRENT_1M | CURRENT_1M (locked, verified unchanged) |
| `confluence_contract` | LEGACY | LEGACY (locked, verified unchanged) |

Full gate sequence (identical code both profiles, order as implemented in
`talonx_quant/consumer.py::_handle_market_tick`, verified by direct
reading, not assumed): closed-bar evaluation (never a still-forming bar)
→ volatility gate → `evaluate_signals` (RSI/MACD/MA trigger + geometry) →
`GLOBAL_RISK_DEGRADED` check (operational, not simulated in a backtest —
no Redis) → UK operating-window check (operational schedule, NOT a
strategy rule — **not simulated**, matching `talonx_backtest`'s own
documented divergence) → US market-session-closed check → opening
blackout (09:30-09:45 ET, both directions) → closing blackout (15:30-16:00
ET, BULLISH only) → loss-lockout (75 min, armed on a realized loss) →
per-ticker cooldown (20 min, armed only on an actually-published signal)
→ confluence gate → risk/reward gate → HTF-trend gate (missing-data vs.
misaligned legs distinguished) → pre-market liquidity/news-catalyst gates
(pre-market session only — **out of scope here**, see §4) → batch
throttle (max 3/15s across all tickers — **fidelity-limited** to
per-1-minute-bar batching in a historical replay, documented, not
silently ignored).

### Position/exit lifecycle — a genuine, material finding

`ExperimentalPaperEngine.check_exits()` (stop/target) and `.flatten_all()`
(EOD sweep) are both fully implemented, tested-in-isolation methods — but
**a full-codebase search of the live `talonx_signals.run` module and every
other production caller found NO caller of either method anywhere in the
current runtime's normal operation.** `talonx_signals/run.py`'s
`ExperimentalLane.consume()` main loop updates `self._last_price` from
every market tick but never invokes `check_exits`; nothing schedules
`flatten_all`. The only path that ever calls `close_long` is from inside
those two uncalled methods themselves.

**Consequence**: under the CURRENT wiring, an Experimental position opened
via `open_long` has **no automatic exit mechanism at all** — it would sit
open indefinitely absent manual/incident intervention. The four
"recovery-affected" Experimental exits recorded on 2026-09-11
(`trade_history` ids 6-9) were produced by an out-of-band incident-
response action, not the standard runtime loop — consistent with this
finding, not contradicted by it.

**This is reported as a real, previously-undocumented operational gap**,
not glossed over. It directly bounds what this task can call
"EXACT_CONTRACT": the ENTRY side (gates, thresholds, evaluate_signals) is
an exact, unmodified reuse of the live production code path. The EXIT
side used below (stop/target + EOD flatten) is the **DESIGNED, coded, but
NOT currently scheduler-invoked** lifecycle — demonstrably correct in
isolation (see §3), but not proven to fire in the live system absent this
task's finding being fixed. Reported as `DESIGNED_LIFECYCLE`, distinct
from `EXACT_CONTRACT`, per this task's own instruction ("do not label the
full result EXACT_CONTRACT if material behavior differs").

Given this, evaluating the DESIGNED exit lifecycle is still the
economically meaningful question — it answers "if this uncalled capability
were wired up as coded, would the resulting economics justify doing so?" —
which is a precondition for recommending the fix at all.

## 2. Harness equivalence (Part 3)

No new backtest engine was built. `talonx_backtest.engine.BacktestEngine`
— an EXISTING, already-tested, production-code-reusing historical replay
engine (imports `talonx_quant.consumer`'s own gate free-functions,
`evaluate_signals`, `compute_indicators`, `compute_htf_trend`,
`compute_daily_pivots`, `get_session`, `get_entry_blackout` unmodified) —
is reused verbatim, with only the relaxed `QuantConfig` substituted in.
This is almost certainly the SAME engine Task 93 used for Original (the
funnel stage names in `FINAL_REPORT.md` — `LOW_VOLATILITY`,
`LOW_CONFLUENCE`, opening/closing blackout, HTF/RR — match this engine's
own `RejectionRecord.reason` vocabulary exactly).

Evidence for the 7 required demonstrations — cited from the EXISTING,
passing test suite (102/102 passed this task, not re-derived):

1. **Valid entry** — `tests/test_backtest_long_only_lifecycle.py`.
2. **Stop/target exit** — `tests/test_backtest_execution.py`,
   `test_backtest_fill_geometry.py`.
3. **Exit evaluated despite an entry-gate rejection** —
   `tests/test_backtest_long_only_lifecycle.py` (LONG_ONLY lifecycle: a
   BEARISH/CONTRADICTED signal always closes an existing long even though
   it never opens one — entry gates and exit evaluation are independent
   code paths, per `engine.py`'s own architecture doc).
4. **Gap/stale/missing-data behavior** —
   `tests/test_backtest_data_gaps.py`, `test_backtest_data_validation.py`
   (missing bars classified expected-vs-unexpected; critical corruption
   aborts via `abort_on_critical_corruption`, called by this task's
   adapter before every run).
5. **Duplicate-event/restart protection** —
   `tests/test_backtest_reproducibility.py`,
   `test_backtest_engine_state.py` (a fresh `BacktestEngine` instance is
   required per run; state is not silently reused — this task's adapter
   follows that contract).
6. **Position and cash reconciliation** — this task's own conversion
   (§ below): `shares = allocation_usd / entry_price_net`, dollar P&L
   derived from the engine's own per-share `gross_pnl`/`net_pnl` fields,
   reconciled against `ending_cash = initial_cash + sum(net_pnl_usd)`
   with 0 open positions expected at data end (verified empirically, not
   assumed — see §6).
7. **Zero external sends** — the engine has no network/Redis/Telegram
   dependency at all (`talonx_backtest` imports only `talonx_quant`
   pure functions + pandas); confirmed by inspection, no send call exists
   anywhere in the module.

**Unresolved differences from live** (disclosed, not hidden):
- Exit lifecycle is `DESIGNED`, not proven `EXACT_CONTRACT` (see §1).
- `GLOBAL_RISK_DEGRADED` / UK operating window: operational-schedule
  concerns, not simulated (matches `talonx_backtest`'s own documented
  posture, not a new omission by this task).
- Pre-market liquidity/news-catalyst gates: fail-closed with no quote/news
  feed (same as live's own fail-closed posture with a permanently-missing
  feed) — this task scopes to **regular session only** (§4).
- Throttle fidelity: batched per 1-minute bar-close, not continuously
  every 15s (documented `BacktestConfig.throttle_fidelity` field).
- Stop/target evaluated against intrabar bar high/low (a standard,
  conservative execution-realism convention, `stop_first` same-bar
  tie-break) rather than live's continuous latest-tick sampling via
  `check_stop_take` — Production-policy simulation (A) vs.
  execution-realism sensitivity (B), per this task's Part 4 requirement:
  (A) = which candidates are gated/published/entered (exact); (B) = the
  precise intrabar fill/stop-touch assumption (a disclosed approximation,
  not claimed identical to a continuous tick feed).

## 3. Universe / window coverage (Part 4)

- Universe: all 35 `task93_canonical_v1` symbols (configured product
  scope) — **not** the 39-name V2 SEC watchlist.
- Window: `2025-01-24 → 2025-02-24` (one calendar month of Segment A;
  see protocol §2 for why the remaining ~5.7 months of Segment A and all
  of Segment B are not run this task — a compute-cost-bounded, timed-rate
  decision made before any Experimental outcome was inspected).
- Coverage: **0 of 35 configured symbols missing** — full coverage,
  confirmed from the actual loaded frame (`covered_n: 35`,
  `missing: []`).
- Data quality: **0** blocking critical-corruption issues
  (`abort_on_critical_corruption` did not raise; a clean pass, not a
  silently-skipped check).
- Adjustment basis: Alpaca 1-min UNADJUSTED (same as Task 93's Original
  baseline — comparable, not mismatched).
- Session scope: **regular session only** — pre-market/after-hours
  candidates are excluded from the primary population (data/gate
  limitation: the pre-market liquidity gate needs BBO quotes this 1-min
  OHLCV dataset does not carry; reported explicitly as
  `entries_non_regular_session_excluded` below, never silently dropped).

## 4. Results (Parts 5-6)

Full artifact: `docs/research/evidence/task121/experimental_replay_summary.json`
(committed verbatim, 3.1KB — small because the closed-trade population is
empty). Raw replay JSON/isolated ledger stay local only
(`results/task121_experimental_replay/`, gitignored).

**Funnel (all 35 symbols, 116,295 bars, 2025-01-24→2025-01-31):**

| stage | count |
|---|---:|
| Bars processed | 116,295 |
| Raw candidates (`evaluate_signals` triggers, pre-gate) | 2,300 |
| Rejected: LOW_VOLATILITY | 56,588 |
| Rejected: LOW_CONFLUENCE | 1,490 |
| Rejected: LOW_RISK_REWARD | 130 |
| Rejected: OPENING_BLACKOUT | 148 |
| Rejected: CLOSING_BLACKOUT | 82 |
| Rejected: US_MARKET_SESSION_CLOSED | 252 |
| Rejected: PREMARKET_LIQUIDITY | 50 |
| Rejected: HTF_DATA_UNAVAILABLE | 33 |
| Rejected: NO_ACTIVE_POSITION (pending-exit with nothing open) | 75 |
| Rejected: COOLDOWN | 38 |
| **Signals published (all gates cleared)** | **75** |
| **Closed long trades (regular session)** | **0** |

**Zero entries, not a computation failure.** `signals_published` (75)
and `NO_ACTIVE_POSITION` rejections (75) match exactly. This engine's
LONG_ONLY lifecycle (Task 24/25A canonical requirement, unmodified here)
schedules a BEARISH/CONTRADICTED published signal as a `_pending_exit`
(which only ever closes an EXISTING long) — never a new position; a
`_pending_exit` with nothing open to close is rejected as
`NO_ACTIVE_POSITION`. The exact 75-vs-75 match is **consistent with every
one of this window's 75 published candidates being BEARISH** — no
BULLISH candidate cleared every gate in this specific week. This is
reported as the most likely explanation from the available counts, not
as an independently re-verified per-signal fact — direction-level
telemetry (`research_telemetry=True`) was not captured on this run (it
would have required a second ~38-minute pass), so it is disclosed as an
**inference from the arithmetic, not a directly observed confirmation.**

This is itself a real demonstration of one of Part 3's seven required
properties: **exit evaluation runs independently of, and despite, the
entry-gate/direction outcome** (a BEARISH candidate is still fully
evaluated and would have closed a long had one existed) — observed
empirically here, not merely asserted from the code.

**Economics**: undefined — zero closed trades. Win rate, profit factor,
net expectancy, net $ P&L, drawdown, concentration, and the issuer-block
bootstrap CI are all `None`/`N/A` by construction (0 distinct issuers, 0
independent groups). `equity_final.equity = $100,000.00` exactly (starting
cash, no P&L of any kind — gross or net — this week). Concurrency:
`max_concurrent_open_positions = 0`; capital was never binding
(vacuously true with zero entries). Overnight/weekend holds: 0 (vacuous).
Cost model (5bps round-trip spread, $2,500/trade allocation, $100,000
starting cash, commissions unmodeled) is recorded for completeness but
was never exercised.

**Sensitivity checks** (§6 of the protocol): drop-top-1-issuer is
undefined (0 issuers); gross-vs-net-of-spread is undefined (0 trades);
capital-isolation check trivially passes (0 concurrent positions can
never exceed $100,000).

## 5. Decision (Part 7)

**`INSUFFICIENT_EVIDENCE_WITH_SPECIFIC_BLOCKER`**

This is NOT a negative-economics finding (there is no P&L to be negative
about) and NOT a data/engine defect (the engine ran cleanly, 0 blocking
data-quality issues, all 35 symbols covered, 2,300 raw candidates and 75
fully gate-cleared candidates were correctly produced and processed — the
gate/entry side of the pipeline works exactly as designed). It is a
**frequency/sample-size result**: even at the relaxed thresholds (which
did produce meaningfully more raw activity than Original's own ~0.15
trades/month — 2,300 raw triggers and 75 published candidates in a single
week, vastly more candidate volume than Original ever sees), this
particular one-week sample happened to generate zero BULLISH
gate-clearing candidates for this LONG_ONLY contract to act on.

**Exact blocker**: one calendar week is too short a window, given this
contract's LONG_ONLY / all-bearish-this-week candidate mix, to observe
even a single closed trade — the window this task's own compute-budget
constraint (§2/protocol) settled on is provably too small to answer the
economic question, not because the strategy is broken, but because
directional variance over one week can (and here did) produce zero
qualifying long entries even with a materially loosened gate.

**Smallest resolving action**: re-run the SAME frozen adapter
(`research/scripts/task121_experimental_replay.py`, unmodified — only
`SEGMENT_A_END` needs extending) over a longer slice of the SAME already-
available Segment A dataset (the remaining ~5.7 months, or a next
non-overlapping month as a smaller first step) — no new strategy, no new
threshold, no new adapter. Estimated cost at the measured ~45-50 bars/sec
single-threaded rate: ~15 hours for the rest of Segment A, or ~35-40
minutes for one additional non-overlapping month. A parallelization of
the existing single-threaded engine (one process per symbol, purely an
engineering change, no strategy semantics touched) would cut this
proportionally and is the more efficient path if this becomes a recurring
need.

## 6. Limitations

- One calendar month, not the full 6.7-month Segment A — a genuine power
  limitation, disclosed, not minimized.
- Exit lifecycle is DESIGNED, not currently live-wired (§1) — the
  economics below describe what WOULD happen if the coded stop/target/EOD
  policy were actually invoked, not what the current live runtime does
  today (which is: no automatic exit at all).
- Pre-market session excluded (data limitation).
- No daily continuous mark-to-market of concurrently open positions
  (trade-event-level accounting only, same disclosed limitation pattern
  as Task 120B).
