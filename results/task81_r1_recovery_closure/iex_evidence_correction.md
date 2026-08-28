# Task 81-R1 §6 — Correction to the Task 81 §5 IEX finding

This corrects the emphasis of `results/task81_safety_baseline_closure/iex_findings.md`.
That report is **preserved unchanged**; this note is the authoritative
qualifier.

## What the Task 81 evidence actually establishes

The Task 80 (2026-08-28) readiness-event counts **reconcile exactly** and
are **internally consistent**:

- `532 DATA_NOT_READY = 515` (one `INSUFFICIENT_RECENT_IEX_PRINTS` per
  stale episode, from `_check_stale`) `+ 17` (one
  `MISSING_REQUIRED_OPENING_MINUTES` per non-READY symbol at 10:00 ET).
- `514 DATA_RECOVERED = 515 STALE_DATA − 1` (COST never recovered →
  `DATA_GAP` at session end).
- `Σ stale_episode_count` in the independently-written
  `freshness_report.json` `= 515`, matching the runner's `_stale_flagged`
  event count symbol-by-symbol.

This proves the **runtime bookkeeping is not double-counting, dropping, or
mis-routing** readiness events, and that infra exclusions are kept
separate from the 5,721 strategy rejections. The Task 81-R1 regression
tests in `tests/test_task81_iex_readiness_bookkeeping.py` lock those
invariants.

## What it does NOT establish (the correction)

Count reconciliation **alone does not explain why the bars were missing**,
and **does not exclude a source-time freshness problem**:

1. **Cause of the gaps is inferred, not measured.** The bimodal coverage
   (mega-caps ~1.0; REGN/VRTX/COST/HON 0.58–0.65) and inter-bar spacing
   (~2.5 min for the churny names, vs. a 120 s `stale_seconds`) are
   *consistent with* genuine Alpaca-IEX 1-minute print sparsity, but the
   preserved evidence contains no per-bar record proving that each
   "missing" minute genuinely had **no IEX print** (as the Task 71S
   `gap_forensics.py` check did establish for the 2026-08-26 session
   against Alpaca's historical archive). IEX sparsity is the **plausible**
   explanation; it is not a **verified** one for this session.

2. **Receipt-time vs source-time is unresolved.** Freshness is measured
   from `_last_seen_wall` (wall-clock at the tick that first *received* a
   bar new-to-us). A bar delivered late but with a market timestamp
   already older than `stale_seconds` would still reset the staleness
   clock, so the current mechanism could under-report genuinely stale
   *market* data during a backfill / delivery-lag episode. The preserved
   evidence has **no per-bar source `t` alongside receipt wall-time**, so
   whether this occurred on 2026-08-28 **cannot be confirmed or excluded**.

## Minimum evidence needed to close this later

- A session run (or a captured raw `GET /v2/stocks/bars/latest` response
  log) recording, per bar: symbol, source bar timestamp `t`, and the
  receipt wall-clock time — for at least the mid-liquidity subset
  (REGN, VRTX, COST, HON, GILD, ISRG) across a full regular session.
- A read-only cross-check of those source timestamps against Alpaca's
  historical IEX 1-minute archive via the existing
  `talonx_piv/gap_forensics.py`, to classify each gap minute as
  `NO_IEX_BAR_OBSERVED` vs `DELIVERY_LAG` vs `INGESTION_DEFECT`.

No new data acquisition, live session, threshold relaxation, or fabricated
bars were performed for this correction.

## Impact assessment

- **Does not block Original/PIV isolation engineering.** Reconciliation,
  recovery, session-identity, and reporting safety are independent of feed
  cadence and of the receipt-vs-source question.
- **Should be resolved before any market-session pilot** whose thesis
  relies on the mid-liquidity NASDAQ-100 names being decision-eligible for
  a meaningful fraction of the session, and before adding a
  market-age freshness gate to the decision path.
