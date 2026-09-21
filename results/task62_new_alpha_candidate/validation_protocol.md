# ORPB_V1 Preregistered Independent Validation Protocol

## Frozen boundary

Validate exactly one `OPENING_RANGE_PARTICIPATION_BREAKOUT_V1` candidate. All semantics, constants,
universe, provider, accounting, criteria, and artifacts are frozen in Task 62 before any historical replay.
Task 62 does not execute this protocol.

No baseline variant, parameter sweep, second attempt, alternative participation rule, threshold sensitivity,
symbol/time filter, alternative stop/exit, sample extension, or post-outcome exclusion is permitted.

## Outcome-blind temporal rule and contamination audit

Task 61R's earliest context access begins 2025-05-06 and its evaluation begins 2025-05-20. Every prior
Task37-61R evaluation/context package is on or after 2025-05-06. Using `XNYS` calendar version `4.13.2`:

1. take all complete XNYS sessions strictly before 2025-05-06;
2. select the chronologically latest 60 consecutive sessions, maximizing proximity/provider availability
   while remaining entirely before any Task37-61R or Task61R context/evaluation access;
3. split chronologically into three consecutive 20-session evaluation windows;
4. assign each its immediately preceding ten XNYS sessions as state-only causal warmup.

This resolves to:

| Window | Warmup | Evaluation |
|---|---|---|
| O1 | 2025-01-24 to 2025-02-06 | 2025-02-07 to 2025-03-07 |
| O2 | 2025-02-24 to 2025-03-07 | 2025-03-10 to 2025-04-04 |
| O3 | 2025-03-24 to 2025-04-04 | 2025-04-07 to 2025-05-05 |

Evaluation sessions never overlap. A warmup may overlap the immediately prior evaluation because it cannot
publish, reject, arm controls, open/close positions, or contribute returns. The entire package predates the
Task61R package and all documented Task37-61R evaluations. No ORPB signal or return was read when selecting it.

Use all 35 frozen symbols and Alpaca only. An availability-only provider audit may verify dates/status without
running ORPB. Missing complete 35/35 coverage is `VALIDATION_BLOCKED`; do not replace a date, symbol, provider,
or window and do not run a partial universe.

## Mandatory pre-replay gates

All must pass before signal generation:

- committed ORPB implementation fingerprint and all frozen source/config hashes match;
- current TalonX and FPRC_V1 files show zero drift from their frozen checkpoints;
- Alpaca-only 35/35 complete warmup/evaluation session coverage in O1/O2/O3;
- zero critical NaN/Inf/OHLC/timestamp/future/duplicate/out-of-order corruption;
- every symbol can form exactly six completed opening 5-minute bars on every evaluation session;
- state-only warmup produces no candidate, rejection, pending order, position, cooldown, lockout, or trade;
- code proofs remain green for completed-bar opening range, first-attempt consumption, strict participation,
  immediate confirmation, next-bar fill/recheck, stop-first ordering, next-open thesis exit, 15:50 flatten,
  telemetry isolation, capacity/ranking, and research/shadow parity;
- estimated runtime is recorded before replay.

Any failure is `VALIDATION_BLOCKED` and stops the run without partial or reduced replay.

## Single replay and reporting

If every gate passes, use a fresh controller per window and run ORPB_V1 exactly once. Compute 0bps and 5bps
per-side economics from identical trades. Report deterministic aggregate/window/symbol/time/geometry/cost/
exit diagnostics:

- trades, wins/losses/flats, total R, expectancy, PF, drawdown, holding duration;
- candidate vs. actual-fill cost feasibility, actual entry/exit cost-in-R, and rejection counts;
- MFE/MAE and realized/MFE ratio;
- 15m/30m/60m/120m/session-close forward excursion for diagnosis only;
- top-1/top-3/top-5 winner and worst-loss sensitivity;
- trade and positive-R concentration by window and symbol;
- opening-range completeness, breakout-to-confirmation, confirmation-to-fill, exit-path, stop-first, and EOD
  parity diagnostics.

## Mandatory support floor

Every item must pass:

- at least 90 total trades;
- at least 20 trades in each O1/O2/O3;
- trades across at least 15 symbols;
- at least 25 gross winners and at least 45 gross losses;
- no symbol contributes more than 20% of trades.

These fixed floors require interpretable breadth without extending the sample until a desired count appears.

## Mandatory economic, robustness, cost, and correctness criteria

Every item must pass:

1. gross expectancy is strictly positive;
2. mean gross expectancy exceeds observed mean 5bps cost-in-R by at least `0.10R/trade`;
3. mean 5bps net expectancy is at least `+0.10R/trade`;
4. 5bps profit factor is at least `1.20` (comfortably above one);
5. deterministic nonparametric trade bootstrap: 10,000 resamples with replacement, NumPy
   `default_rng(62)`, two-sided percentile 95% interval; lower bound must be `> 0`;
6. at least two of three windows have positive 5bps expectancy and no window is below `-0.10R/trade`;
7. removing the top three gross winners leaves aggregate 5bps expectancy `> 0`;
8. no window contributes more than 60% of positive 5bps R;
9. no symbol contributes more than 20% of positive 5bps R;
10. mean and every actual-fill feasibility estimate are `<= 0.20R`;
11. all technical correctness/parity invariants remain green.

Gross profitability alone, lower assumed costs, one strong window, one symbol, or a few winners cannot pass.

## Classification and hard rejection

Exactly one result is allowed:

- `ORPB_V1_REPLICATION_REQUIRED`: every mandatory gate and criterion passes. This authorizes only a second
  untouched preregistered validation, not capital or production.
- `ORPB_V1_REJECTED`: any support/economic/robustness/cost/correctness criterion fails after unblinding.
- `VALIDATION_BLOCKED`: a mandatory pre-replay gate prevents a complete run.

After `ORPB_V1_REJECTED`, retire this candidate. Do not tune or rerun ORPB on O1-O3, add observations, change
symbols, alter a threshold, or diagnose a replacement in the same task. Any successor requires a genuinely
new hypothesis and untouched data.

Deployment remains `MONDAY_DECISION_SHADOW_ONLY`; no capital or production behavior is authorized.
