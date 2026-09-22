# Audit universe: the 39 enforced V2 execution-scope symbols

**Source (PROVEN):** the live V2 companion's own startup log line, identical in both RC1 sessions:
- `results/prospective_2026-09-21/logs/v2_companion.log` at 2026-09-21 19:42:31 (UK)
- `results/prospective_2026-09-22/logs/v2_companion.log` at 2026-09-22 07:51:40 (UK)

The line reads `V2 execution scope ENFORCED -- 39 allowed issuers: AAPL, ABCL, ABT, ACHR, ADC, ADP, AFL, AGNC, AMAT, AMD, AVGO, BAC, BLK, C, CSCO, CVX, DELL, GOOGL, IBM, INTC, JNJ, JPM, KO, MA, MCD, MSFT, MSTR, NUE, NVDA, ORCL, PG, PYPL, SHOP, STX, TSLA, UNH, V, VRT, WMT`.

The scope is resolved by `talonx_v2/run.py:205-209` (`--execution-scope resolved-active-watchlist` gives the `POLLED` tickers of `talonx_ops.watchlist_coverage.build_coverage_map()`). Broad discovery was **not** enabled: `broad_discovery_included: false` in every Session 02 checkpoint. No newer or broader universe was substituted.

Issuer names and CIKs come from the insider store (`insider_transactions.issuer_cik` / `company_name`), falling back to SEC `company_tickers.json` for symbols with no stored transaction.

Column notes:
- **Form 4 (45d lookback):** distinct accessions accepted since 2026-08-08, the live companion's `--live-lookback-days 45` window.
- **09-16..09-22 (store):** accessions accepted on or after 2026-09-16.
- **at SEC:** the same count read from SEC EDGAR submissions JSON at 2026-09-22 ~21:05Z. The only difference (+6) is filings accepted after the stack stopped; see README §4.
- Acceptance-date counts use the stored `accepted_at_utc` date. *Correction:* that field has mixed ET/UTC semantics (README F1, superseded), which can move an evening-ET filing by one calendar day in these per-window counts. The SEC `filingDate` backfill (`../v2_sec_filing_date_release_fix/`) is authoritative.

| # | Symbol | Issuer | Issuer CIK | In enforced scope 09-21 & 09-22 | Form 4 filings (45d lookback) | Form 4 filings 09-16..09-22 (store) | Form 4 at SEC 09-16..now | Code-P filings (45d) | Code-P 09-16..09-22 | Distinct code-P owners (45d) |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | AAPL | Apple Inc. | 0000320193 | YES | 7 | 1 | 1 | 0 | 0 | 0 |
| 2 | ABCL | AbCellera Biologics Inc. | 0001703057 | YES | 5 | 0 | 0 | 4 | 0 | 3 |
| 3 | ABT | ABBOTT LABORATORIES | 0000001800 | YES | 4 | 0 | 0 | 0 | 0 | 0 |
| 4 | ACHR | Archer Aviation Inc. | 0001824502 | YES | 5 | 0 | 0 | 0 | 0 | 0 |
| 5 | ADC | AGREE REALTY CORP | 0000917251 | YES | 5 | 2 | 2 | 4 | 2 | 2 |
| 6 | ADP | AUTOMATIC DATA PROCESSING INC | 0000008670 | YES | 18 | 0 | 0 | 0 | 0 | 0 |
| 7 | AFL | AFLAC INC | 0000004977 | YES | 29 | 6 | 7 | 0 | 0 | 0 |
| 8 | AGNC | AGNC Investment Corp. | 0001423689 | YES | 1 | 0 | 0 | 0 | 0 | 0 |
| 9 | AMAT | APPLIED MATERIALS INC /DE | 0000006951 | YES | 3 | 0 | 0 | 0 | 0 | 0 |
| 10 | AMD | ADVANCED MICRO DEVICES INC | 0000002488 | YES | 27 | 1 | 1 | 0 | 0 | 0 |
| 11 | AVGO | Broadcom Inc. | 0001730168 | YES | 2 | 2 | 2 | 0 | 0 | 0 |
| 12 | BAC | BANK OF AMERICA CORP /DE/ | 0000070858 | YES | 3 | 1 | 1 | 0 | 0 | 0 |
| 13 | BLK | BlackRock, Inc. | 0002012383 | YES | 0 | 0 | 0 | 0 | 0 | 0 |
| 14 | C | CITIGROUP INC | 0000831001 | YES | 0 | 0 | 0 | 0 | 0 | 0 |
| 15 | CSCO | CISCO SYSTEMS, INC. | 0000858877 | YES | 27 | 10 | 10 | 0 | 0 | 0 |
| 16 | CVX | CHEVRON CORP | 0000093410 | YES | 7 | 0 | 0 | 0 | 0 | 0 |
| 17 | DELL | Dell Technologies Inc. | 0001571996 | YES | 59 | 23 | 26 | 0 | 0 | 0 |
| 18 | GOOGL | Alphabet Inc. | 0001652044 | YES | 23 | 13 | 13 | 0 | 0 | 0 |
| 19 | IBM | INTERNATIONAL BUSINESS MACHINES CORP | 0000051143 | YES | 2 | 0 | 0 | 0 | 0 | 0 |
| 20 | INTC | INTEL CORP | 0000050863 | YES | 1 | 0 | 0 | 1 | 0 | 1 |
| 21 | JNJ | JOHNSON & JOHNSON | 0000200406 | YES | 6 | 0 | 0 | 0 | 0 | 0 |
| 22 | JPM | JPMORGAN CHASE & CO | 0000019617 | YES | 2 | 0 | 0 | 0 | 0 | 0 |
| 23 | KO | COCA COLA CO | 0000021344 | YES | 3 | 0 | 0 | 0 | 0 | 0 |
| 24 | MA | Mastercard Inc | 0001141391 | YES | 4 | 0 | 0 | 0 | 0 | 0 |
| 25 | MCD | MCDONALDS CORP | 0000063908 | YES | 1 | 0 | 0 | 0 | 0 | 0 |
| 26 | MSFT | MICROSOFT CORP | 0000789019 | YES | 40 | 5 | 5 | 0 | 0 | 0 |
| 27 | MSTR | Strategy Inc | 0001050446 | YES | 4 | 0 | 0 | 0 | 0 | 0 |
| 28 | NUE | NUCOR CORP | 0000073309 | YES | 2 | 0 | 0 | 0 | 0 | 0 |
| 29 | NVDA | NVIDIA CORP | 0001045810 | YES | 11 | 5 | 6 | 0 | 0 | 0 |
| 30 | ORCL | ORACLE CORP | 0001341439 | YES | 6 | 6 | 6 | 0 | 0 | 0 |
| 31 | PG | PROCTER & GAMBLE Co | 0000080424 | YES | 50 | 5 | 5 | 0 | 0 | 0 |
| 32 | PYPL | PayPal Holdings, Inc. | 0001633917 | YES | 11 | 1 | 1 | 0 | 0 | 0 |
| 33 | SHOP | SHOPIFY INC. | 0001594805 | YES | 0 | 0 | 0 | 0 | 0 | 0 |
| 34 | STX | Seagate Technology Holdings plc | 0001137789 | YES | 30 | 5 | 6 | 0 | 0 | 0 |
| 35 | TSLA | Tesla, Inc. | 0001318605 | YES | 1 | 0 | 0 | 0 | 0 | 0 |
| 36 | UNH | UNITEDHEALTH GROUP INC | 0000731766 | YES | 3 | 0 | 0 | 0 | 0 | 0 |
| 37 | V | VISA INC. | 0001403161 | YES | 7 | 0 | 0 | 0 | 0 | 0 |
| 38 | VRT | Vertiv Holdings Co | 0001674101 | YES | 3 | 1 | 1 | 0 | 0 | 0 |
| 39 | WMT | Walmart Inc. | 0000104169 | YES | 13 | 2 | 2 | 0 | 0 | 0 |
| | **Total** | | | 39/39 | 425 | 89 | 95 | 9 | 2 | |


All 39 were execution-eligible throughout both sessions. The 39-symbol scope held in every Session 02 checkpoint (`execution_scope_count: 39`, `qualification: FRESH_VALID`).

Symbols with **no** Form 4 in the 45-day lookback: BLK, C, SHOP. Symbols with **any** code-P purchase in the lookback: ABCL, ADC, INTC (3 of 39).
