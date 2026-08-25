# Task70 Holdout Selection Lock

**Locked before any F6 outcome was computed.** See `historical_exposure_audit.{json,md}`
for the full evidence trail. This file is the human-readable companion to
`holdout_selection_lock.json` (the machine-readable source of truth).

## Selected windows

| Role | Start | End | Approx. trading days |
|---|---|---|---|
| VALIDATION | 2024-02-01 | 2024-03-15 | ~32 (calendar estimate) |
| REPLICATION | 2024-09-03 | 2024-10-18 | ~34 (calendar estimate) |

Both entirely within calendar year 2024 — the least-exposed window found in
this repo's full tracked history, and materially separated from each other
(~5.5 months) and from every prior research window (ORPB/FPRC: 2025-01-24
onward; F6's own development: 2026-05-15 onward).

## Why 2024, not the pre-existing 2026-08-25..2026-10-21 forward reservation

`results/task67a_phenomenon_discovery/data_split_contract.json` had already
reserved VALIDATION=2026-08-25..2026-09-22 / REPLICATION=2026-09-23..2026-10-21
as a forward-looking plan. As of this task's timestamp (2026-08-25, i.e.
*today*), none of that range has traded yet — there is no data to download.
Rather than wait, this task used 2024 instead, per the task's own explicit
instruction to check whether older history "especially 2024" is defensible.

## Why these specific 2024 dates

- **Cleanliness**: 2024 is EXPOSED_DATA_ONLY at worst (see audit) — no
  strategy outcome of any kind has ever been computed against it.
- **Historical-data availability**: confirmed live via read-only Alpaca API
  checks (feed=sip) — a 2-week micro-sample for AAPL, and a full-35-symbol
  single-day spot-check per window. 33/35 symbols returned full 1-minute
  coverage; BKNG and REGN showed sparser (but present, HTTP 200) prints on
  the specific spot-check days, consistent with their high share prices —
  not a data failure.
- **Symbol coverage / adequate sessions / temporal separation / calendar
  diversity**: all satisfied — see `holdout_selection_lock.json`'s
  `selection_reason` field for the exact reasoning.
- **NOT selected based on F6 performance.** `outcomes_inspected: false` is a
  literal fact as of this commit — no `evaluate()` call has touched real
  price data anywhere in this task before this lock.

## What happens next

Part 4 (data materialization) downloads real Alpaca 1-minute bars for both
windows and reports data quality. Part 6 runs F6_FADE_V1 against VALIDATION
exactly once. Replication only happens if validation passes.
