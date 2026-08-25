# Task69P Deep Review (Task69Q Part 1)

Reviewed: `results/task69p_full_runtime_piv/` in full, cross-checked against raw
`piv_events.jsonl`, `lifecycle_state.json`, and the raw Alpaca snapshot ground
truth file, per the instructions in this task. Full machine-readable version:
`task69p_deep_review.json`.

## Checklist reconfirmation (13 claims)

All 13 previously-reported findings are **CONFIRMED** against raw evidence,
not just re-stated from the summary docs:

| # | Claim | Verdict |
|---|---|---|
| 1 | 35 configured symbols | CONFIRMED |
| 2 | 17 warmup-ready | CONFIRMED (17+18=35 reconciles) |
| 3 | 15 session-ready | CONFIRMED (15+20=35 reconciles) |
| 4 | 14 warmup∩session-ready | CONFIRMED |
| 5 | transient stale symbols | CONFIRMED (cross-checked vs raw snapshot) |
| 6 | 1 Quant candidate metric | CONFIRMED, but **unaudited** (see U01) |
| 7 | 0 published natural signals | CONFIRMED |
| 8 | no natural broker lifecycle | CONFIRMED |
| 9 | approved PIV probe only | CONFIRMED |
| 10 | 0 residual orders/positions | CONFIRMED |
| 11 | reconciliation clean | CONFIRMED |
| 12 | F6_FADE_V1 not integrated | CONFIRMED independently (git ancestry + grep) |
| 13 | zero alpha evidence | CONFIRMED |

## Previously-missed issues found by this review

1. **U01 — No candidate rejection accounting trail.** `signal_lifecycle_summary.json`
   admits the rejection breakdown was never queried; PIV had no way to prove
   `candidates = published + rejected + pending + errored`. **Fixed** — see
   `quant_funnel_contract.json`.
2. **U02 — Exit fill mislabeled as a new `POSITION_OPENED`.** Confirmed in raw
   data: `POSITION_OPENED` count=4, `POSITION_CLOSED` count=0 across the whole
   event log. Broker exposure was correct throughout (flat at EOD) — this was
   a state/event-naming defect, not a financial one. **Fixed** — see
   `production_readiness_gaps.json` and `talonx_piv/lifecycle.py`.
3. **U03 — `piv_events.jsonl` mixes multiple trading dates in one file** with
   no `session_id`/`trading_date` field. Confirmed spanning 2026-08-23/24/25.
   **Fixed** — every event now carries `session_id`/`trading_date_et`, and
   `reporting.build_session_report` accepts a `trading_date_et` filter.
4. **U04 — `/ping`'s headline Pipeline status read an unrelated subsystem.**
   `talonx_dispatch/telegram_listener.py` derived the top-line verdict from
   `talonx_ingest`'s WS heartbeat even for a PIV caller, which never writes to
   it. **Fixed** — the headline is now PIV-aware via a live-updated
   `feed_health` field.
5. **U05 — yfinance/Alpaca provider split is a real, only partially resolved
   data-availability limitation.** See `warmup_provider_assessment.json`.

## Bottom line

Task69P's core operational claims hold. The gaps this review found are real
but narrow, and four of five are fixed in this task; the fifth (warmup
provider) has a concrete, documented remediation path rather than a fix,
since it depends on verifying live Alpaca historical-data entitlement.
