# Task75A Summary -- Freeze CROSS_SECTIONAL_EXTREME_WINNER_SHORT_REVERSION_V1

## Pre-freeze audits (all DEVELOPMENT-only / public-knowledge-only, zero 2024 price reads)

1. **Effective search-count audit:** the honest provenance denominator is
   40 direction-level comparisons, not 20 hypothesis-cells -- not a
   prohibited promotion, but an under-specified gap, disclosed and
   carried into the validation protocol rather than hidden.
2. **Canonical calendar correction:** built and frozen. Zero symbol/day
   mismatches vs SPY's calendar in any DEVELOPMENT slice; the corrected
   evaluator reproduces Task74B's anchor cell EXACTLY. Development
   population unchanged.
3. **Corporate-action policy:** CONFIRMED raw/unadjusted data, zero
   split handling anywhere in the repo. Two known public 10:1 splits
   (NVDA, AVGO) fall inside the reserved validation window.
   **Task75B is BLOCKED pending a corporate-action-safe dataset.**

## Frozen candidate

**CROSS_SECTIONAL_EXTREME_WINNER_SHORT_REVERSION_V1** -- SHORT_ONLY,
MULTI_DAY. Top-20% market-adjusted 3-day cross-sectional rank vs SPY;
Day1 canonical-calendar open entry; exit at the 3rd canonical day's
close. 15% catastrophic stop (a conservative buffer above the anchor
cell's 95th-percentile MAE). 25bps primary all-in cost (short-specific,
not just the generic 10bps). Fingerprint
`08930fb2bbbd1f8acbf2071be2e7bf6b2ead784a94e38837d05f4e8937eebff3`.

## Validation protocol (pre-registered, not yet run)

17 mandatory criteria, holding Task74B's own bar (net@10bps>=+0.15%) as
a floor while adding a stricter 25bps primary gate and NEW overlapping-
dependence checks (entry-day cluster bootstrap, calendar moving-block
bootstrap with block length 5). Validation runs exactly once, and is
currently gated BLOCKED pending the corporate-action fix.

## Tests

19 new focused tests (canonical-calendar causality, missing-session
rejection, tie/percentile semantics, fingerprint determinism) plus a
217-test broader regression across the full Task67A/68/71/72/74/74B/75
lineage -- all pass.

## Live-session safety

Runtime untouched, no PIV/Redis/Telegram/Alpaca-feed service touched, no
large replay started, completed well before the 12:30 BST cutoff.

## Next

Task75B is explicitly BLOCKED until a corporate-action-safe dataset is
available for the validation/replication windows. See
`claude_handoff_next.md`.
