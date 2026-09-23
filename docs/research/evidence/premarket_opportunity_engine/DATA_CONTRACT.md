# Pre-market data contract

Every item below was **verified empirically on 2026-09-23** against this account's Alpaca data subscription. Keys were loaded from `.env` and never printed. No paid provider was added.

## Provider: Alpaca Market Data v2, `feed=sip`

| Item | Verified value |
|---|---|
| Endpoint | `GET https://data.alpaca.markets/v2/stocks/bars` (multi-symbol `symbols=A,B,…`) |
| Timeframes used | `1Min` for pre-market and post-open; `1Day` for previous close, range, ATR and ADV |
| Feed | **`sip`**. `iex` is real-time but has **no extended-hours bars**: AAPL returned 5 bars on 09-23, all in regular hours. |
| Extended hours | **YES.** SIP returns bars from 04:00 ET (08:00Z in EDT). 09-23 examples: AAPL 217 1-minute bars 08:00Z–13:30Z; TSLA 296; ADC 4, with the first at 11:00Z, the minute its Form 4 was accepted. |
| Timestamps | Bar `t` is the bar **start**, in RFC 3339 UTC. A 1-minute bar is complete at `t + 1 min`. |
| Price | `o/h/l/c` plus `vw` (VWAP), split-adjusted with `adjustment=split`. That is the same basis for daily and minute bars, so the gap is internally consistent. |
| Volume | `v` shares; `n` trade count. |
| **Recency limit** | **SIP data newer than 15 minutes is refused.** `end` values of now, now−5 and now−14 min returned `HTTP 403 {"message":"subscription does not permit querying recent SIP data"}`; now−15 min and older returned data. With no `end`, the API returns data up to now−15 min. The SIP `snapshots` endpoint also returns 403. |
| Rate limit | Response header `X-Ratelimit-Limit: 200` (per minute). The engine budgets 180 per minute, and a client-side limiter blocks rather than exceeding it. A 429 is retried with back-off. |
| Pagination | `limit` caps bars per page **across all symbols in the request** (10,000 max). `next_page_token` continues. The engine batches 200 symbols per request and follows tokens. |
| Missing bars | A minute with no trades has no bar. That is normal, not an error. Thin names print sporadically, so a symbol with no pre-market bar is `NO_PREMARKET_PRINTS` (not data-ready), not a failure. |
| Daily bars | `1Day` bars are stamped `YYYY-MM-DDT04:00:00Z` (00:00 New York), and the session date is the New York date. |
| Split adjustment | `adjustment=split` on both timeframes. A gap above 300% is treated as an implausible print or an unadjusted corporate action and hard-rejected (`IMPLAUSIBLE_GAP`). |

## Stale-data semantics

| Concept | Rule |
|---|---|
| `data_as_of` | `now − 15 min`, truncated to the minute. That is the newest instant this subscription may read. Every live alert states "Alpaca SIP 1-min, 15-min delayed, as of HH:MM UTC". |
| Causal bar filter | A bar is used only if `t + 1 min <= data_as_of` (`complete_bars_as_of`). |
| Stale price | If the last pre-market print ended more than **45 min** before `data_as_of`, the symbol is hard-rejected `STALE_PREMARKET_PRICE`. |
| Invalid timestamp | A last print later than `data_as_of` (more than 1 min of skew) is hard-rejected `INVALID_TIMESTAMP`. |
| NaN / missing fields | Bars with non-finite OHLCV, or `c <= 0`, are dropped before features are computed. |
| Missing previous session | If the last daily bar is not the XNYS previous session, the result is `MISSING_PREVIOUS_SESSION_BAR` (not data-ready). |

**Limitation:** the live canary sees pre-market prices **15 minutes late**. That is inherent to this free entitlement. The only real-time free feed (IEX) has no extended-hours data. The research value is still intact: pre-market gaps develop over hours (04:00–09:30 ET). But alerts are explicitly labelled as delayed, and the replay simulates the same delay so its results are faithful to live behaviour.

## Catalyst sources (free, causal)

| Source | Use | Causality |
|---|---|---|
| SEC `data.sec.gov/submissions/CIK##########.json` | Forms filed on the previous session or the scan day, fetched **only for gap candidates** (|gap| >= 2%), cached for 10 min live, at ≤ ~5 requests/s with the declared `TALONX_SEC_USER_AGENT` | A filing counts only if its true acceptance is at or before the decision time. Acceptance comes from `talonx_ingest.intelligence.sec_time.resolve_acceptance` (see SESSION03_FINDINGS_FIXES A2). If a same-day filing's acceptance can't be resolved, replay excludes it (conservative), counted in `excluded_unverified`. In live mode its presence in the feed at decision time is itself proof of availability. |
| TalonX insider ledger `~/.talonx/ingestion_ledger.db` (read-only URI) | Distinct code-P open-market buyers over 30 days, for symbols TalonX already ingests | `filing_date` before the scan day, or the same day with resolved acceptance **and** TalonX receipt (`insider_filings.ingested_at_utc`) at or before the decision time |

## Scan cadence vs provider limits

| Phase (XNYS calendar, New York time) | Window | Scan interval |
|---|---|---|
| EARLY_PREMARKET | 04:00–07:00 | 15 min |
| CORE_PREMARKET | 07:00–09:00 | 5 min |
| NEAR_OPEN | 09:00–09:30 | 5 min |

- **Scan window.** The first scan is at 04:15 ET, because nothing is visible before the 15-minute delay. The last scan is before 09:30 ET. The schedule is 41 scans on a normal EDT day (11 in EARLY, 24 in CORE, 6 in NEAR_OPEN), derived from `exchange_calendars` XNYS, never from a UK clock. Half-days and holidays follow the calendar, and the process exits on a non-session day.
- **Request cost.** Each live scan fetches only the new interval `[last fetch, data_as_of)` for about 5,655 symbols: about 29 batched requests, plus pages. That is well inside 180 per minute. Measured scan cost is in TEST_EVIDENCE.md.
