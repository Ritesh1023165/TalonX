# Task 121 — Experimental exact-contract evaluation: frozen protocol

> **Correction (Task 121A, 2026-09-12):** §4's execution assumptions
> (next-bar-open entry, bearish-signal close, 15:50 ET EOD flatten) are
> now known to NOT match Experimental's real live lifecycle — see
> `docs/research/TASK121A_PROVENANCE_AND_CONTRACT.md` for the corrected
> contract (same-bar-close entry, stop/target-only exit, no EOD flatten,
> no bearish-close) and its root cause (a stale research-worktree copy of
> `talonx_signals/run.py`, not an import-precedence or search-scope
> error). This protocol's population/window/universe/cost sections
> remain otherwise accurate and were reused, corrected only where noted,
> by Task 121A's own frozen protocol.

Written and committed to the protocol file BEFORE any Experimental-relaxed
replay was executed against real outcomes. Predeclares the population,
metrics, uncertainty method, sensitivity checks and interpretation rule so
none of them can be chosen after seeing results.

## 1. Contract under test

`EXPERIMENTAL_RELAXED_V1` exactly as constructed by
`talonx_signals.relaxed_profile.build_experimental_quant_config` /
`talonx_signals.config.RELAXED_OVERRIDES` in the current repaired runtime:
a `dataclasses.replace()` of the frozen `QuantConfig()` changing exactly
three fields —

| field | frozen (Original) | relaxed (Experimental) |
|---|---:|---:|
| `min_atr_pct` | 0.25 | 0.10 |
| `confluence_score_min` | 2 | 1 |
| `min_risk_reward_ratio` | 1.5 | 1.0 |

— with `volatility_gate_mode=CURRENT_1M` and `confluence_contract=LEGACY`
hard-locked identical to Original (verified: `relaxed_profile.py` raises if
either flips). Every other gate — HTF trend, session/blackout, cooldown
(1200s), loss-lockout (75min), confluence-then-RR ordering — is the SAME
production code Original uses, because both profiles are the SAME
`QuantScanner`/`evaluate_signals()` classes with only the three fields
above substituted.

## 2. Primary historical window and eligible universe

Reuses Task 93's `task93_canonical_v1` dataset exactly as built (no new
download), all 35 symbols (`talonx_piv.DEFAULT_UNIVERSE` / FPRC-ORPB
validation set — configured product scope, NOT the 39-name V2 SEC
watchlist), Alpaca 1-minute OHLCV, restricted to the **first calendar
week of Segment A**: `2025-01-24 → 2025-01-31` (97,440 bars across all 35
symbols, measured directly from the loaded frame; ~5-6 trading sessions).

**Everything past this one week — the rest of Segment A (→ 2025-08-14,
2,565,682 bars total) and all of Segment B_deep (10 symbols, →
2026-08-14, 1,903,044 bars) — is NOT run in this task.**
`talonx_backtest.engine.BacktestEngine.run()` is per-bar compute-bound
(its own module docstring already warns of this). Window-selection
chronology, in order, with what was and wasn't observed at each step:

1. A timed, progress-logged smoke test measured a stable **~42-48
   bars/second**, single-threaded, on one symbol
   (`results/task121_experimental_replay/rate_smoke_test.log`) — no trade/
   candidate outcome inspected, only elapsed time per bar count.
2. A **full one-month run was actually launched** (393,624 bars, all 35
   symbols) and observed reaching 5.0% progress after ~8 minutes
   (confirming a ~2.5 hour total) — again, only the progress percentage
   and elapsed time were observed; zero trades, candidates, or
   rejections were inspected before this run was deliberately stopped.
3. The window was narrowed a second time, to **one calendar week**, to
   fit this task's session-interactive time budget (~35-40 minutes
   estimated) — a resource-availability decision, not a response to any
   Experimental economic outcome, since none had been seen at either
   larger window.

This is disclosed as a genuine, two-step scope reduction on statistical
power and seasonal coverage — not minimized or hidden. **A one-week
result is a small-sample first pass, not a full-segment-powered
estimate.** §7's interpretation rule is written accordingly: this window
can only ever support "extend the replay further" as its most positive
finding, never a stand-alone promotion recommendation.

**This is NOT an untouched holdout.** Task 93 already inspected this exact
price history for the Original contract. Running Experimental's relaxed
gates over the same bars is the first evaluation of THIS contract, but not
a blind/preregistered-holdout test in the classical sense — stated
plainly, not retrospectively reframed as one.

## 3. Data sources and adjustment basis

Alpaca 1-min OHLCV, **UNADJUSTED** (same basis Task 93 used; no
split/dividend back-adjustment). Extended hours are present in the file but
**this replay evaluates REGULAR SESSION candidates only** — see §6
(scope limitation, not a silent exclusion).

## 4. Execution and cost assumptions

Reuses `talonx_backtest.engine.BacktestEngine` (the same production-code-
reusing historical replay engine used for Task 93/Original), with
`quant_config` = the relaxed config from §1, unmodified gate pipeline
(`talonx_quant.consumer`'s own free functions — `_fails_min_volatility`,
`_confluence_eligible`, `_trend_gate_applicable`, `_evaluate_active_volatility_gate`,
`_partition`), unmodified `evaluate_signals`/`compute_indicators`/
`compute_htf_trend`/`compute_daily_pivots`/`get_session`/`get_entry_blackout`.

- Entry: next bar's OPEN after a published signal (never same-bar close;
  causal by construction — `talonx_backtest.execution` docstring).
- Stop/target: intrabar high/low against the fixed bracket, same-bar
  ambiguity resolved `stop_first` (conservative default) — this is a
  **execution-realism sensitivity**, not the exact live tick-by-tick
  observation model (live samples the latest tick's close price only via
  `check_stop_take`, not a continuous intrabar wick) — flagged explicitly,
  not claimed identical to live (Part 4 requirement).
- EOD flatten: 15:50 ET (`BacktestConfig.eod_flatten_enabled=True`,
  matching `talonx_paper`'s real EOD sweep time) — Experimental IS
  genuinely intraday-only by construction (`ExperimentalPaperEngine.flatten_all`
  exists and `_EXIT_ACTION["eod_flatten"]` is a real exit path); no EOD
  flattening is being ADDED here to fit a label, it reproduces an existing
  behavior.
- Cost: spread only, **5bps round-trip** — `ExecutionConfig(spread_bps=5.0)`
  reproduces `talonx_paper.engine.apply_spread`'s real formula exactly
  (`price * spread_bps/2/10000` per side; BUY pays half, SELL pays half,
  5bps total) — this is Experimental's REAL, already-modeled cost, not an
  externally-imposed research convention (unlike V2's 20bps, which exists
  BECAUSE V2 models zero cost internally — see Task 120/121 accounting
  corrections). Commissions/fees remain **unmodeled**, same disclosure as
  the dashboard's `_TALONX_PAPER_COST_BREAKDOWN`.
- Position sizing: Experimental's real fixed `allocation_usd=$2,500` per
  trade, `initial_cash=$100,000`, one open position per symbol (no
  pyramiding — `BacktestConfig.allow_overlapping_trades=False`, matching
  `ExperimentalPaperEngine.open_long`'s own "already long -> None" check).
  Max 35 concurrent positions × $2,500 = $87,500 ≤ $100,000 — capital is
  not expected to bind; verified empirically, not assumed (§6).
- **Not simulated** (documented divergences from live, all pre-existing
  and disclosed by `talonx_backtest.engine`'s own module docstring, not
  introduced by this task): `GLOBAL_RISK_DEGRADED` and the UK 08:00-22:00
  operating window (deployment/Redis-health concerns, not strategy rules);
  pre-market liquidity/news-catalyst gates (fail-closed with no quote/news
  feed, same as live under a permanently-missing-data condition); sub-
  minute throttle fidelity (batched per closed 1-min bar, not continuously
  every 15s).

## 5. Primary metrics and uncertainty method

- Closed trades, distinct issuers, independent time groups (issuer ×
  month).
- Trades per session/month; zero-trade periods.
- Win rate, average win/loss, net expectancy (R and $).
- Profit factor.
- Net dollar P&L (allocation-weighted: `shares = allocation_usd / entry_price_net`
  per trade, no compounding across trades — a fixed $2,500 notional per
  entry, matching the real engine's fixed-allocation sizing, not a
  compounding equity curve).
- Daily marked equity and drawdown, where the data supports it (entries/
  exits only — a true continuous daily mark-to-market of concurrently open
  positions is out of this task's bound; if not computed, stated as NOT
  computed, never silently substituted with a cash-only curve).
- Exposure/concurrency, overnight/weekend holdings (expected: none, given
  EOD flatten — verified, not assumed).
- Issuer/time concentration.

**Uncertainty**: issuer-block bootstrap, 5,000 reps, **seed 121121**
(chosen now, before running; distinct from Task 120's 118120 so no seed
is ever reused across tasks to imply continuity it doesn't have), 95%
percentile CI on net expectancy. Effective independent-group count (
distinct issuers) reported explicitly, never implied equal to N.

## 6. Predeclared sensitivity checks (limited, listed now)

1. Drop-top-1-issuer (by trade count) — report both means, no silent
   substitution.
2. Gross-of-spread vs net-of-spread (both published; net is the primary
   figure).
3. Capital-isolation check: confirm empirically that the $100,000/$2,500
   sizing never rejects an entry purely on cash affordability (if it does,
   report the count explicitly, do not fold it into "signal-driven" trade
   counts).

No threshold grid, no new signal family, no post-hoc removal of losing
trades or symbols.

## 7. Advance / reject / inconclusive interpretation (fixed now)

- **ADVANCE_TO_FURTHER_VALIDATION**: net expectancy positive, 95% CI
  excludes zero, AND opportunity frequency materially exceeds Original's
  ~0.15 trades/month (i.e. genuinely serves the owner's stated
  "regular opportunities" intent) — all three required together. Given
  §2's one-month window, a result meeting this bar means "extend the
  replay to the full Segment A next" — it is NOT by itself sufficient
  power to recommend live/Telegram promotion.
- **REJECT_CURRENT_CONTRACT_FOR_PRODUCT_USE**: net expectancy negative
  with 95% CI excluding zero, OR frequency remains too sparse to serve the
  product's intent regardless of sign (frequency-reject is reported as
  distinct from economics-reject, never blended into one label).
- **INSUFFICIENT_EVIDENCE_WITH_SPECIFIC_BLOCKER**: 95% CI includes zero,
  or a data/engine gap prevents the computation described above — the
  exact blocker and smallest resolving action are named, not a generic
  "needs more research" deferral. Given one month is a small sample even
  at Experimental's higher trigger rate, this outcome is an EXPECTED,
  acceptable possibility, not a failure of the task — predeclared here
  before running, not invented afterward to excuse a null result.

## 8. Data already inspected vs. genuinely unused

100% of the price history used here (`task93_canonical_v1`) was already
inspected by Task 93 for the Original contract. Nothing in this dataset is
being claimed as an untouched holdout for Experimental. The Form-4/SEC
insider data (V2's domain) is untouched by this task and irrelevant here —
Experimental has no Form-4 dependency.

---
Frozen at 2026-09-12, before `research/scripts/task121_experimental_replay.py`
was run against real outcomes.
