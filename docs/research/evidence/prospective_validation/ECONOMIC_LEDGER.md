# V2-PAPER-RC1 prospective economic ledger

Campaign `V2-PAPER-RC1`, PAPER, starting cash $100,000, allocation $10,000 per position (fee-inclusive), frozen release `v2-paper-rc1`.

This record is observational only. No profitability threshold is defined here, and no profitability conclusion may be drawn from a small sample. **PROFITABILITY VALIDATION: NOT_COMPLETE.**

Update it after every session's EOD reconciliation, from the ledger (`v2_release_rc1.db`, opened read-only) and the session's `eod.json`. Never edit the ledger to match this file.

## A. Per-opportunity / per-trade record

Use one row per cluster that reached ≥2 distinct owners. The category column comes from the taxonomy in [README.md](README.md) §2.

SEC acceptance times are shown in New York time (ET), taken from SEC's raw filing header; the stored `accepted_at_utc` has mixed legacy semantics (corrected; see `../v2_sec_filing_date_release_fix/`). Receipt times are UTC. Only ACTUAL campaign outcomes go here; hypothetical outcomes for missed opportunities are kept separately in [v2_39_stock_missed_opportunity_audit/ECONOMIC_OUTCOMES.md](../v2_39_stock_missed_opportunity_audit/ECONOMIC_OUTCOMES.md).

| Cluster | Symbol | Activation (SEC-accepted, ET) | Durable receipt (UTC) | Entry session | Category | Admission result | Fill price | Shares | Capital used | Exit target session | Actual exit (session / price) | Realized price P&L | Dividends | Total return | R | Reason if not traded |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `07242bc857569f60` | ABCL | 2026-08-14 12:04:25 ET | 2026-09-04 10:18:49Z | 2026-08-17 | `MISSED_DUE_TO_INGESTION_DOWNTIME` (pre-campaign; ingestion not yet deployed) | `SKIPPED_ENTRY_STALE` | — | — | — | — | — | — | — | — | n/a | entry session predated the campaign and insider ingestion (first ran 09-04); stale |
| `19f814d1f3ec3250` | ADC | 2026-09-17 07:00:24 ET | 2026-09-21 18:42:40Z | 2026-09-18 | `MISSED_DUE_TO_INGESTION_DOWNTIME` (pre-campaign) | `SKIPPED_NO_PRIOR_INTENT` (intent path NOT_REACHED) | — | — | — | — | — | — | — | — | n/a | filing received after the entry session; ingester offline 09-16 to 09-20; campaign created 09-21 |

"R" is not supported: V2@1 has no stop (`stop_loss_enabled=False`), so no risk unit is defined. Report percentage return on capital used instead, and leave R as `n/a`.

For each fill, record `entry_price_provenance` / `exit_price_provenance` from `positions` (expected: `alpaca:sip:1Day:adjustment=split`).

## B. Per-session log

| Date | Session | Coverage | New ≥2-owner clusters | Category counts | Intents | Fills | Exits | Open at EOD | Cash at EOD | EOD verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-09-21 | 01 | partial day (started late session) | ABCL, ADC first seen (both pre-campaign) | pre-campaign 2 | 0 | 0 | 0 | 0 | $100,000.00 | see `v2_full_day_session_01/` |
| 2026-09-22 | 02 | full day, 07:51 UK to 21:05 UK, 0 restarts | none new | `NO_QUALIFYING_CLUSTER` | 0 | 0 | 0 | 0 | $100,000.00 | `FULL_DAY_PASS_WITH_FINDINGS` |

## C. Cumulative totals (as of 2026-09-22 EOD)

| Metric | Value |
|---|---|
| Prospective market days operated | 2 (1 partial, 1 full) |
| Qualifying clusters (in-campaign) | 0 |
| Qualifying clusters received on time | 0 |
| Opportunities missed due to ingestion downtime (in-campaign) | 0 (2 pre-campaign: ADC, ABCL; see the 39-stock audit) |
| Late source/receipt correctly rejected (in-campaign) | 0 |
| Admitted intents | 0 |
| Fills | 0 |
| Exits | 0 |
| Wins / losses | 0 / 0 |
| Open trades | 0 |
| Realized price P&L | $0.00 |
| Dividend return | $0.00 |
| Total return | $0.00 (0.00%) |
| Implementation defects | 0 |
