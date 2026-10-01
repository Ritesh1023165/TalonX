# TASK 95B — Phase 4 — Partition Rationale

`research_partitions.json`. Chronological, non-overlapping, **purged by 10 trading days** (the maximum
forward horizon) so no discovery forward-return window reaches into validation and none of validation
reaches into holdout. Frozen at `4b0e5dfa2415afe1dbf423c63c9cc479264106fa`; **boundaries do not move
regardless of results.**

| Partition | Dates | Entry-eligible end | Rows | Trading days | Regime content |
|---|---|---|---:|---:|---|
| **Discovery** | 2020-01-02 → 2023-06-30 | 2023-06-15 | 30,798 | 880 | COVID crash + V-recovery (2020), retail/mega-cap bull (2021), **sustained bear / high-rate (2022)**, early disinflation recovery (2023 H1). 13,291 trend-bear rows · 17,472 trend-bull · 10,282 drawdown > 20 % · 6,839 high-`rv60`. |
| **Validation** | 2023-07-17 → 2025-02-14 | 2025-01-31 | 13,961 | 399 | 2023 H2 rally, 2024 AI-led momentum bull, early-2025. Genuinely independent regime mix (trend-bull-heavy but with 5,555 bear rows). |
| **Holdout** | 2025-03-03 → 2026-08-14 | 2026-07-31 | 6,533 | 366 | 2025 tariff-shock volatility (incl. April 2025), 2025 H2, 2026 to Aug. **UNTOUCHED during discovery.** |

## Why this split

- **Discovery gets the regime diversity.** The primary risk in Tasks 93–95A was single-regime
  coverage. Putting 2020–2023 H1 in discovery guarantees a crash, a full bull, a full bear, and a
  recovery are all available for hypothesis generation and for the mandatory by-regime checks
  (Phase 10). Holding a swing hypothesis to "works in discovery" therefore already means "worked
  across four regimes."
- **Validation is a different market.** 2023 H2 – 2024 was a distinct low-volatility momentum regime;
  a discovery candidate that only worked in 2020–2022 stress will visibly fail here.
- **Holdout is the most recent, most decision-relevant period** and is the one that will matter to
  the gatekeeper. It is not inspected in Task 95B.
- **Purge = max horizon (10 trading days).** A discovery event dated ≤ 2023-06-15 has its entire
  10-day forward window complete by ~2023-06-30, before validation's 2023-07-17 start. No forward
  return is shared across partitions, so there is no look-ahead leakage through the label.

## Known limitation

Validation and holdout lose the 25 non-deep symbols after 2025-08-14 (they end there in
`task95a_expanded_v1`). Holdout is therefore ~35 symbols for its first ~5 months then the 10 deep
names. Reported alongside a COMMON_UNIVERSE (10 deep names) view wherever it matters, exactly as in
Tasks 93/95A. Discovery and the bulk of validation are full 35-symbol.
