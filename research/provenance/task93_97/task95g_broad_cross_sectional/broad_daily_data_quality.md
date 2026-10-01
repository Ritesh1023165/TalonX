# TASK 95G — Phase 2 — Daily Data Quality

`task95g_sp500_daily_v1` — Alpaca SIP `/v2/stocks/bars` 1Day, `adjustment=all`. `broad_daily_data_quality.json`.

| check | result |
|---|---|
| total daily rows | **1,059,207** |
| symbols requested / with data | 620 / **619** (99.8%) — 1 zero-data (window-edge legacy ticker) |
| dates | 1,811 (2019-06-03 → 2026-08-14) |
| duplicate (date,symbol) rows | **0** |
| impossible OHLC (`low>open/close`, `high<open/close`) | **0** |
| non-positive close | **0** |
| extreme daily moves > 50% | 35 (of 1.06M cells) — genuine (bank failures SIVB/FRC/SBNY, a few incompletely-adjusted micro-splits) |
| extreme daily moves > 80% | 11 |
| split-artifact cells masked (`|ret| > 45%`) for feature construction | **49** — single-day return dropped so a partial-adjustment step cannot pollute a trailing-return feature |
| zero-volume days | 65,553 cells (~0.06%) — thin trading near delistings; excluded naturally by the ≥200-day + close>0 eligibility |
| symbols with full-window history (> 1,800 rows) | 543 / 619 — the remainder are removed/acquired names with correct partial history |
| median symbol first bar | 2019-06-03 (the requested warm-up start) |

## Removed-constituent termination (survivorship correctness)

Spot-checked in Task 95F (`broad_universe_price_proof_report.md`) and inherited here: acquired /
delisted / failed names' series **terminate on the corporate-action date** — TWTR 2022-10-27,
ATVI 2023-10-13, PXD 2024-05-02, SIVB 2023-03-09 — with **no zombie bars** past tradability and
no forward-fill from a successor ticker. `adjustment=all` supplies split+dividend-adjusted OHLC.
Ticker-rename pairs (WLTW/WTW, CDAY/DAY, and the renames handled implicitly via current-ticker
normalization) hand off cleanly.

## Verdict

No material systematic gaps. The panel is research-grade for equal-weight / rank-based
cross-sectional daily research. Not stopped.
