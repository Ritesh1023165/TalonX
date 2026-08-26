# Task 70S -- Remaining Stabilisation Issues (NOT implemented in this task)

Per Task 70S's explicit scope ("stabilisation task... do not begin new
alpha, dashboard, Gemini, alert-contract, orchestration, or product feature
work"), the following items are retained for a later, separately-scoped
task and are **not** addressed here:

1. **Missing opening-minute semantics** -- the 09:30-09:59 session-readiness
   window (`talonx_piv/readiness.py`) and this task's pre-market historical
   warmup are two independent gates; their exact interaction at the
   09:29->09:30 boundary (e.g. whether a symbol's LAST warmup bar and its
   FIRST readiness-tracked bar can legitimately overlap or double-count)
   has not been re-audited as part of this task.

2. **Staleness isolation and recovery** -- this task's Alpaca warmup runs
   once, at session start, exactly like the existing yfinance path it
   supplements. A symbol whose Alpaca (or yfinance) history goes stale or
   degrades DURING the live session (as opposed to at cold-start) is out of
   scope; `SessionRunner._check_stale` already covers live-tick staleness
   separately and is unmodified.

3. **Alpaca provider-health reporting** -- no dashboard/alerting surface
   exists yet for "Alpaca historical warmup is degraded/unavailable across
   many symbols" as a distinct operational-health signal (as opposed to the
   per-symbol WarmupCheck evidence this task produces).

4. **Cross-date readiness persistence** -- this task deliberately does NOT
   add any new persisted Alpaca-warmup cache (see
   causal_boundary_evidence.json's "no_persisted_cache" section) -- this
   avoids introducing a NEW staleness risk, but it also means warmup always
   re-fetches from scratch every process start, even on a same-day restart.
   Whether a same-day, same-session warmup cache would be a worthwhile
   future optimization (distinct from the readiness.py session-readiness
   state, which already restores same-day) is not evaluated here.

5. **EOD/live-session identity linkage** -- unrelated to this task; still
   the same open item noted in Task69R's own evidence (the `eod` CLI
   subcommand constructs its own session identity, separate from the live
   `start` session's).

6. **Dashboard scope and counter reconciliation** -- explicitly out of
   scope per this task's "do not begin... dashboard... work" instruction.

7. **Unified Quant/Brain/Core/Dispatch/dashboard orchestration** --
   explicitly out of scope per this task's "do not begin...
   orchestration... work" instruction.

8. **Execution-independent alerts and shadow ledger** -- explicitly out of
   scope per this task's "do not begin... alert-contract... work"
   instruction.

9. **Long-only BUY/SELL_TO_CLOSE/NO_TRADE enforcement** -- unaffected by
   this task; `talonx_quant`'s LONG_ONLY lifecycle (Task 25A) is untouched
   (this task never imports or modifies `talonx_quant/consumer.py`,
   `strategy.py`, `indicators.py`, or `config.py`).

10. **Premarket WATCH versus validated-alpha separation** -- unaffected;
    `talonx_piv/premarket_radar.py` is untouched by this task, and every
    warmup event this task produces remains `alpha_evidence=false`
    (OPERATIONAL_PIV_TEST_TRAFFIC), same classification as before.

11. **Complete PAPER end-to-end verification** -- this task proves the
    warmup LEG in isolation (unit tests + a live read-only historical-data
    smoke test); it does not re-run or re-verify a full PAPER trading
    session end-to-end (that remains Task69R's own domain, and this task's
    mandatory safety constraints explicitly prohibit starting a live PIV
    session).

## Known limitations of THIS task's own implementation (disclosed, not blockers)

- `REQUIRED_1M_BARS` (talonx_piv/warmup.py, hardcoded 120) and
  `QuantConfig.min_bars_required` (talonx_quant/config.py, env-overridable,
  default 120) are two independently-configurable values that happen to
  share a default -- this decoupling predates this task and was not
  introduced or fixed here (fixing it would require touching
  `talonx_quant/config.py`, which this task's own safety constraints
  prohibit).
- The Alpaca fetch requests raw (unadjusted) 1-minute bars, same convention
  used everywhere else Alpaca is already called in this repo
  (`session_runner.fetch_bars_latest`, `broker.py`) -- a corporate-action
  split falling inside a symbol's ~10-calendar-day warmup lookback window
  could in principle show a large single-bar discontinuity. This is
  extremely unlikely to matter for a short (10-day) intraday-indicator
  warmup window in practice, and is a materially smaller-scope concern than
  the multi-day-return corporate-action issue already flagged and BLOCKED
  in the separate research worktree's Task75A
  (`corporate_action_policy.json`) -- but it has not been separately
  re-audited here.
- `lookback_days=10` (default) is a fixed calendar-day window, not a
  trading-calendar-aware one; it comfortably covers any single US market
  holiday adjacent to a weekend (verified empirically: the live 35-symbol
  smoke test in this task's own evidence returned far more than the
  required 120 bars per symbol using this same default), but has not been
  stress-tested against an unusually long multi-holiday closure.
