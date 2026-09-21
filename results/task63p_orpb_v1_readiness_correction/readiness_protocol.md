# Task 63P — Frozen Per-Symbol-Session ORPB Data Readiness

## Correction boundary

This correction changes only the pre-signal data-readiness decision. It does not change ORPB_V1 alpha,
execution, risk, cost, universe, window, support, economic, robustness, or correctness semantics. The ORPB
implementation fingerprint must remain
`b1e283bd36eb0cb2ecc5303b104ec2bd8defc60f6eacef4879e7711d560d113f`.

Task 63 and Task 63R stopped before ORPB signal generation or outcome access. This correction is frozen
before the first ORPB replay on O1-O3.

## Production-compatible readiness rule

At 10:00 ET, independently for each symbol-session, inspect only raw Alpaca SIP timestamps from 09:30
through 09:59 ET. The session is `CLEAN` only when raw observations allow all six completed opening
five-minute components to exist: 09:30, 09:35, 09:40, 09:45, 09:50, and 09:55.

If any component is absent, classify only that symbol-session as `DATA_NOT_READY`. Feed none of that
symbol-session's bars to the ORPB controller, so it cannot publish a candidate, order, rejection, position,
control state, or trade for that date. Continue the unchanged 35-symbol universe on all clean sessions.

This is fail-closed eligibility, not symbol removal. No bar may be fabricated, interpolated, forward-filled,
back-filled, copied, or borrowed from another feed/symbol/session.

## Causality and isolation

The decision uses timestamp presence only through 09:59 ET. Prices, volume, post-10:00 bars, signals,
orders, trades, exits, and returns are unavailable to the readiness function and cannot affect it. A fresh
ORPB controller remains isolated per O1/O2/O3, and the filter only returns an unchanged subset of source rows.

## Frozen package and expected exceptions

Use the existing uniform Alpaca SIP package, exact 35-symbol universe, and O1/O2/O3 dates. There are 2,100
expected symbol-sessions (35 x 60). Exactly six are frozen `DATA_NOT_READY`:

- O1 BKNG: 2025-02-10, 2025-02-11
- O1 KLAC: 2025-02-07
- O2 BKNG: 2025-03-26
- O3 BKNG: 2025-04-25, 2025-04-30

Any additional `DATA_NOT_READY` case, missing session, critical corruption, feed/fingerprint drift, failed
proof, or other mandatory pre-replay gate is `VALIDATION_BLOCKED`.

If and only if every corrected gate passes, run the frozen Task 62 ORPB validation once on clean
symbol-sessions. All Task 62 support/economic/robustness/cost/correctness criteria and hard classification
rules remain unchanged.
