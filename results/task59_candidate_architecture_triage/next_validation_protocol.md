# FPRC_V1 Preregistered Validation Protocol

## Purpose

Test exactly one frozen `FAILED_PULLBACK_RECLAIM_CONTINUATION_V1` candidate. This protocol forbids use of
Tasks 53–58 as an optimization or evaluation dataset. Task 59 performs no implementation, download, replay,
or outcome inspection.

## Freeze before data access

Before downloading or reading evaluation outcomes, commit:

- the complete implementation and tests;
- a machine-readable configuration and strategy fingerprint;
- the exact 35-symbol universe;
- this signal/confirmation/geometry/exit contract;
- cost assumptions of 0bps and 5bps per side;
- the exchange calendar version and resolved evaluation dates;
- the artifact schema and all pass/fail criteria below.

No parameter, family, symbol, stop, exit, cost, or window alteration is permitted after the freeze.

## Outcome-blind windows

Use the first 60 complete XNYS trading days strictly after 2026-07-09, resolved mechanically by the frozen
exchange calendar and divided chronologically into three consecutive 20-trading-day evaluation windows
`N1`, `N2`, and `N3`. Each evaluation window receives the immediately preceding 10 XNYS trading days as
state-only causal pre-roll. Warmup dates may overlap an earlier evaluation window because warmup generates
no signals or trades; evaluation dates may not overlap.

Use all 35 frozen symbols and Alpaca only. Missing complete coverage is `VALIDATION_BLOCKED`; do not replace
dates, symbols, provider, or windows and do not run a partial universe.

## Mandatory pre-replay gates

- 35/35 symbols with complete warmup and evaluation coverage in every window;
- no critical NaN/Inf/OHLC/timestamp/future/duplicate/out-of-order corruption;
- 35/35 readiness for 1m indicators, regular-session VWAP, 15m SMA200, and all FPRC_V1 state at the first
  evaluation bar;
- frozen strategy/config fingerprints match;
- code-level proofs for closed-bar trigger, immediate-next-bar confirmation, next-bar fill, setup reset,
  cost-in-R fill recheck, setup-local stop, 5m VWAP-failure exit, stop-first ambiguity, and 15:50 flatten;
- no shared state or behavior change in the existing Monday shadow candidate.

Failure of any gate blocks replay and records the exact blocker.

## Replay and reporting

Run the one frozen candidate once at 0bps and once at 5bps accounting on the identical trades. No baseline
variant, parameter sweep, alternative exit, or threshold sensitivity is allowed. Report by aggregate, window,
symbol, time bucket, geometry/cost bucket, and exit path:

- trade count, wins/losses/flats, total R, expectancy, PF, drawdown, holding duration;
- mean/median cost-in-R and actual-fill feasibility rejects;
- MFE/MAE and realized/MFE ratio;
- 15m/30m/60m/120m/session-close forward excursion for diagnosis only;
- top-1/top-3/top-5 winner and worst-loss sensitivity;
- symbol and window concentration;
- trigger-to-confirmation and confirmation-to-fill parity diagnostics.

## Interpretability floor

All must pass:

- at least 60 total trades;
- at least 15 trades in each of N1/N2/N3;
- trades across at least 10 symbols;
- at least 15 winners and 30 losses overall;
- no single symbol contributes more than 25% of trades.

Failure is a hard architecture rejection, not permission to loosen semantics or extend the same evaluation
until significance appears.

## Economic and robustness pass criteria

Every criterion is mandatory:

1. mean gross expectancy exceeds observed mean 5bps cost-in-R by at least `0.15R/trade`;
2. mean 5bps net expectancy is at least `+0.15R/trade`;
3. 5bps profit factor is at least `1.25`;
4. a deterministic nonparametric trade-level bootstrap (10,000 resamples with replacement, NumPy
   `default_rng(59)`, two-sided percentile 95% interval) for 5bps expectancy has lower bound `> 0`;
5. at least two of three windows have positive 5bps expectancy and no window is below `-0.15R/trade`;
6. removing the top three gross winners leaves aggregate 5bps expectancy `> 0`;
7. no single window contributes more than 60% of positive 5bps R;
8. no single symbol contributes more than 25% of positive 5bps R;
9. mean and every-trade actual-fill cost burden respect the frozen `0.20R` feasibility ceiling;
10. all technical correctness invariants remain green.

Gross profitability alone, a lower-cost scenario, one strong window, or one high-payoff symbol cannot pass.

## Replication and production boundary

Passing N1–N3 yields only `FPRC_V1_REPLICATION_REQUIRED`. It does not authorize capital or production. A
second preregistered replication must use the next 60 complete XNYS trading days, the identical candidate,
and identical criteria. Only two clean passes may support a later owner decision; Task 59 authorizes neither
that replication nor deployment.

## Hard rejection and anti-iteration rule

If FPRC_V1 fails any interpretability, economic, robustness, cost-feasibility, or correctness criterion after
outcomes are unblinded, classify it `FPRC_V1_REJECTED` and stop. Do not adjust a threshold, add/remove a gate,
change a symbol, alter exits, extend the sample, or rerun a variant on N1–N3. Any later research must begin
with a genuinely different economic hypothesis, a new specification, and untouched future data.

Deployment remains `MONDAY_DECISION_SHADOW_ONLY`; no capital and no production behavior change.
