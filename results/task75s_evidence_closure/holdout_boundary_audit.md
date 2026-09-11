# Task 75S — Stage 2: Holdout Boundary Audit

## Question
Does holdout exclusion satisfy the actual reserved-data manifest, or only an assumed symbol-disjointness
rule?

## Method (metadata only -- no market data or outcomes opened)
Directly listed files and read `download_summary.json` metadata (symbol keys, requested date ranges --
never price/volume columns) for both reserved holdout directories:
`data/historical_1m/task56_holdout/{H1_early,H2_middle,H3_late}` and
`task56_independent_family_holdout/H1_early`.

## Findings
- Every holdout subdirectory's **file listing** contains only the 25 additional (non-core) symbols
  (ADBE, ADI, AMAT, AVGO, BKNG, CMCSA, COST, CSCO, GILD, HON, INTC, INTU, ISRG, KLAC, LRCX, MDLZ, MU,
  NFLX, PANW, PEP, QCOM, REGN, SBUX, TXN, VRTX) -- confirmed by direct directory listing, not assumed.
  **None of the 10 core symbols (AAPL, MSFT, NVDA, AMZN, META, AMD, TSLA, GOOGL, PYPL, STX) appear as a
  file in any holdout directory.**
- `task56_holdout/H1_early/download_summary.json`'s own `symbols` dict, however, only records **16 of
  the 25** present CSV files (missing ADBE, ADI, AMAT, AVGO, BKNG, CMCSA, COST, CSCO, GILD) --
  requested range `2025-12-11` to `2026-01-26`. **This is a pre-existing manifest/file-listing
  inconsistency in the repository's own holdout provenance, unrelated to and not caused by this or
  Task 74S's work.** It does not affect the disjointness conclusion below (the *files present*, whether
  or not each is individually catalogued in that specific JSON, are still all drawn from the
  25-additional-symbol set, confirmed by filename).
- Also relevant: `docs/research/TALONX_RESEARCH_LEDGER.md`'s own Task 56 entry records that this
  specific holdout acquisition was ultimately `VALIDATION_BLOCKED` (a proxy/network failure), and that
  the reserved scope was **specifically the 25 additional symbols' H1/H2/H3 windows** -- consistent with
  what the file listings show.

## Verdict
**Holdout exclusion is verified against the actual reserved-data manifest (file listings + recorded
symbol keys), not merely assumed.** The 10-symbol universe used by Task 74S has **zero symbol-level
overlap** with any holdout directory, at any date, for either holdout location. This conclusion does
not rely on date-range reasoning at all (a stronger property than "the dates don't overlap") --
disjointness holds by symbol set alone, which is a categorical guarantee robust to any window choice
Task 74S might have made (narrow or full-year).

**No corrective action needed for Task 74S's holdout claim** -- it was accurate as stated, and this
audit adds the manifest-level verification that was implicit but not separately documented before.
