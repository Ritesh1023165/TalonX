# Task 121A — source provenance and the corrected Experimental contract

## Part 1 — why Task 121 reported the wrong exit behavior

**Root cause: stale research-worktree source (confirmed by git ancestry and
byte-hash comparison, not by memory or assumption).**

The research branch (`research/talonx-profitability-2026-09`) and the
release branch (`research/talonx-strategy-validation`) diverged at commit
`9bec279` (Task 114's final SHA). Since that fork point:

- The release branch gained **38 commits**, including `72baca2`
  ("Task 118A P1/P2/P3 -- Experimental exit lifecycle wiring, ..."), which
  wired `ExperimentalLane._maybe_check_exit() -> self.paper.check_exits()`
  into `talonx_signals/run.py`'s live `consume()` loop.
- The research branch gained **18 different commits** (its own,
  independent research work) and **never received `72baca2`**.

Verified directly (`git merge-base`, `git rev-list --count` both
directions; see `docs/research/evidence/task121a/module_manifest.json`
for the reproducible hash record this task generates on every run):

```
git merge-base f28986999... 2f28922...  ->  9bec279...  (the fork point)
commits in release not in research: 38
commits in research not in release: 18
```

`talonx_signals/run.py` byte-hashes:
- release: `c86991fa2ed0f18e...`
- research (Task 121's own source at the time): `f8799bc276df7c1f...`
- **NOT identical** — confirmed with a full content diff (528 lines in the
  stale research copy vs. 605 in the release copy; the release copy alone
  contains `_maybe_check_exit`, `_EXIT_TICK_MAX_AGE_SECONDS`, and the
  `_record_experimental_exit` display-log reconciliation, none of which
  exist in the research copy).

**Candidate causes evaluated, per this task's own list:**
- *Stale worktree source* — **CONFIRMED** (above).
- *Incorrect search scope* — ruled out: Task 121's `grep -rn "flatten_all"`
  was correctly scoped to the (stale) worktree it was run from; the
  directory searched was right, the checkout underneath it was wrong.
- *Python import precedence* — a contributing risk, not the root cause of
  the ORIGINAL Task 121 finding (that used direct file reads, not an
  import), but a REAL risk for THIS task's own replay, since the research
  worktree also carries its own copies of `talonx_quant`/`talonx_backtest`/
  `talonx_paper` — see the fix below.
- *Cached imports or a different checkout* — not applicable (Task 121 used
  direct `Read`/`grep`, not a running interpreter with stale cached
  modules).

**Byte-hash comparison of every module Task 121's ADAPTER actually
imports** (as opposed to `run.py`, which no adapter code path ever
imports — it was read directly, for narrative purposes only):

| module | release vs. research |
|---|---|
| `talonx_quant/{consumer,strategy,config,session,indicators,schemas,buffer,aggregation}.py` | byte-identical |
| `talonx_paper/{engine,schemas}.py` | byte-identical |
| `talonx_backtest/{engine,execution,data,portfolio}.py` | byte-identical |
| `talonx_signals/{config,relaxed_profile,experimental_paper,directional}.py` | content-identical (CRLF-only diff) |
| `talonx_signals/run.py` | **DIFFERENT** (real content divergence, above) — **never imported by the adapter**, read directly as contract source only |

**Conclusion**: Task 121's computed ECONOMICS (2,300 raw candidates, 75
published, 0 entries on its one-week window) were NOT affected by the
staleness — none of the modules its `BacktestEngine`-based adapter
imported were stale. What was wrong was a SEPARATE narrative
investigation ("does live Experimental have an exit caller?") that read
`run.py` from the stale research worktree and drew the wrong conclusion.
That specific claim — "no automatic exit caller exists" / "Friday's four
exits were manual" — is **withdrawn**. `check_exits()` (stop/target) IS
wired into every live market tick (Task 118A P1). Whether Friday's four
"recovery-affected" exits used this path or a separate incident-response
action is **UNKNOWN and NOT reasserted either way** — Task 121's "manual
intervention" claim is also withdrawn as unsupported, not replaced with
an equally unsupported opposite claim.

**Fix, this task forward**: `research/scripts/task121a_experimental_replay.py`
inserts the RELEASE worktree at `sys.path[0]` (ahead of the research
worktree) before importing any `talonx_quant`/`talonx_backtest`/
`talonx_paper`/`talonx_signals` module, then calls `verify_provenance()`
— which re-imports every one of those modules, asserts each resolved
`__file__` sits inside the release worktree, hashes it, and **raises
before any replay runs** if an import ever resolved elsewhere. This is a
narrow, reproducible, programmatic gate — not a branch merge, not an
uncommitted manual copy. `module_manifest.json` (written on every run) is
the reproducible record.

## Part 2 — the corrected contract, read from the release source directly

### Candidate triggers and gates
Unchanged from Task 121's own (correct) description: `evaluate_signals()`
(RSI/MACD/MA trigger + geometry) behind the SAME gate sequence Original
uses, with exactly three fields relaxed
(`min_atr_pct` 0.25→0.10, `confluence_score_min` 2→1,
`min_risk_reward_ratio` 1.5→1.0); `volatility_gate_mode`/
`confluence_contract` locked identical (verified unchanged).

### Bar completion / indicator availability
Closed-bar evaluation only (never a still-forming bar) — unchanged,
confirmed again this task by direct re-reading of
`talonx_quant/consumer.py::_handle_market_tick`.

### Entry price and timing — CORRECTED
`talonx_quant/indicators.py::compute_indicators` sets
`IndicatorSnapshot.price = float(latest_row["close"])` — the JUST-CLOSED
bar's own close. `talonx_signals/run.py::_maybe_open_experimental` opens
at `sig.get("price")` — i.e. **the signal's own bar close, with NO
one-bar delay**. This is DIFFERENT from `talonx_backtest.engine`'s own
built-in convention (fills at the NEXT bar's open, a conservative
academic-backtest anti-lookahead convention Original/PIV's lifecycle
uses). Task 121's adapter used the next-bar-open convention throughout —
**incorrect for Experimental**. This task's `ExperimentalLifecycleShim`
fills at the signal's own bar close instead (verified by
`tests/test_task121a_parity_trace.py::test_1_...`).

### Stop/target triggers
`talonx_paper.engine.check_stop_take` — a SINGLE scalar sampled price per
tick (the position's `stop_price`/`target_price`, captured from the
signal's OWN geometry at open time), **never intrabar high/low**.
`talonx_signals/run.py::_maybe_check_exit` calls this on EVERY live
market tick for a symbol with an open position (Task 118A P1),
independent of whether that tick also carries a fresh candidate. This
task's shim mirrors this exactly, using each historical bar's own CLOSE
as the causal per-minute proxy for "the latest tick" (the finest
granularity this dataset offers) — a disclosed execution-realism
limitation (§ below), not claimed identical to a continuous tick feed.

### Gap / staleness / freshness
`_EXIT_TICK_MAX_AGE_SECONDS` (default 300s) — a tick older than this (or
with negative age) is treated as stale FOR EXIT PURPOSES, skipped, no
fill invented. This task's historical replay has no "stale tick" concept
(every bar is, by construction, exactly on-schedule) — the analogous
protection this adapter provides is: a bar with NO recorded close for
that exact (symbol, timestamp) is skipped, never fabricated (see
`ExperimentalLifecycleShim.check_exit`, verified by
`test_6_missing_bar_close_observation_never_invents_a_fill`).

### Whether bearish signals close positions — CORRECTED
**No.** `talonx_signals/run.py::handle_message` only ever calls
`_maybe_open_experimental` for a BULLISH candidate. Nothing in the live
runtime closes an Experimental position on a bearish/contradicted
signal. Task 121's adapter (via `talonx_backtest.engine`'s own
Original-shaped LONG_ONLY lifecycle) DID schedule a close on a bearish
signal — **incorrect for Experimental**. Verified corrected by
`test_5b_bearish_while_long_does_not_close_the_position`.

### Whether EOD flatten is scheduled — CORRECTED
**No.** `ExperimentalPaperEngine.flatten_all()` exists, is fully
implemented and unit-tested in isolation, but **has no caller anywhere in
`talonx_signals/run.py`** (confirmed directly: `grep -n "flatten_all"`
against the RELEASE file returns only its own definition and one
docstring mention). Task 121's adapter set
`BacktestConfig.eod_flatten_enabled=True` — **incorrect for
Experimental; not merely re-asserted here because `flatten_all()`
exists, but because its absence of any caller was independently
verified.** This task uses `eod_flatten_enabled=False`, verified by
`test_7_position_survives_a_session_close_crossing_no_eod_flatten`.

### Overnight/weekend holding
**Genuinely possible in live production**, following directly from the
two corrections above: with no bearish-signal close and no EOD flatten,
an open Experimental position is held until its stop or target is
struck, or indefinitely if neither ever is — including across sessions,
weekends, and (structurally) indefinitely. This task's replay reports
any position still open at the dataset boundary as **open/unresolved
with an explicit marked valuation**, never force-closed (Part 5/6
requirement).

### Position sizing / re-entry
`ExperimentalPaperEngine`: fixed `$2,500` allocation per trade, one
position per symbol (no pyramiding — `open_long` returns `None` if
already long), `$100,000` starting cash. Unchanged from Task 121.

### Cost convention — verified, corrected labeling
`talonx_paper.engine.apply_spread(price, spread_bps, side)` moves the
price by `spread_bps / 2 / 10_000` on the ONE side given. A `5.0`
parameter (`ExperimentalPaperEngine`'s own default) is **~5bps
ROUND-TRIP at an unchanged reference price (2.5bps entry + 2.5bps
exit), NOT 5bps per side.** Verified directly, not merely asserted:
`tests/test_task121a_parity_trace.py::test_apply_spread_worked_example`
computes `apply_spread(100.0, 5.0, "BUY") == 100.025` and
`apply_spread(100.0, 5.0, "SELL") == 99.975`, a round-trip cost of
exactly 5.0bps. This matches Task 121's own prior label (which already
said "5bps total" / "5bps round trip") — the correction here is
confirming it with a worked test, not changing the number. Embedded
spread is the ONLY modeled cost; commissions/fees remain unmodeled
(unchanged from Task 121/the dashboard's own `_TALONX_PAPER_COST_BREAKDOWN`
finding).

## Universe mapping (Part 4)

`docs/research/evidence/task121a/universe_mapping.json` (committed,
generated fresh by this replay, not hand-typed): of the 35 historical
`task93_canonical_v1` symbols, only **12** (AAPL, AMAT, AMD, AVGO, CSCO,
GOOGL, INTC, MSFT, NVDA, PYPL, STX, TSLA) intersect the CURRENT
configured live watchlist (47 tickers). 23 historical symbols
(ADBE, ADI, AMZN, BKNG, CMCSA, COST, GILD, HON, INTU, ISRG, KLAC, LRCX,
MDLZ, META, MU, NFLX, PANW, PEP, QCOM, REGN, SBUX, TXN, VRTX) are **not**
part of today's configured scope at all; conversely 35 of the 47
currently-configured tickers have **zero** historical 1-min coverage in
this dataset. **The 35-symbol historical universe is NOT the complete
configured product scope** — it is Original's own validation universe
(`talonx_piv.DEFAULT_UNIVERSE`), reused here because it is the only
locally-available 1-minute historical panel, not because it was
independently verified to equal "the configured Experimental symbols."
Reported explicitly, not assumed.
