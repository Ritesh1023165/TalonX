# Task75A Part 4 -- Corporate-Action Policy

**Finding: all historical bars in this repo are RAW/unadjusted.**
`scripts/download_historical_1m.py::fetch_alpaca()` explicitly requests
`"adjustment": "raw"` from Alpaca. A repo-wide search found ZERO
split-detection, dividend-adjustment, or corporate-action handling
anywhere in the codebase.

**This is a real, concrete problem for this exact candidate.** At least
two well-known, publicly documented 10-for-1 stock splits fall inside
the reserved VALIDATION window (2024-06-01..2024-09-02) for this exact
35-symbol universe:

- **NVDA** -- 10:1 split, ~2024-06-10
- **AVGO** -- 10:1 split, ~2024-07-15

(General public knowledge only -- no 2024 price data was read to
produce this list, and it is not claimed exhaustive.) An unadjusted
price series shows an artificial ~90% single-bar drop at a split date;
any 3-day return feature or any position spanning that date would be
catastrophically corrupted.

Dividend ex-date liability for a SHORT-only strategy is also completely
unmodeled anywhere in this repo.

## Classification: TASK75B_BLOCKED_PENDING_CORPORATE_ACTION_SAFE_DATASET

Task75B must NOT run against the current raw dataset. Before Task75B
can validate:
1. Re-download the validation/replication windows with a non-raw
   Alpaca adjustment (`adjustment=split` or `all`), OR
2. Obtain a verified corporate-action event table and explicitly
   exclude/adjust affected symbol-date windows.

This does not block Task75A, which proceeds to freeze everything else
and records this as an explicit precondition for Task75B.
