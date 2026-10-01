# TASK 95G — Survivorship Control (Current vs Removed Constituents)

For every feature, the top-decile `top_decile_excess` at k=3 was decomposed by whether the selected
name was **still an S&P 500 member at the end of the membership window** ("current") or **later
removed** ("removed"). This is the core survivorship check: does the signal exist only in eventual
survivors?

| feature | current-member excess (bps) | removed-member excess (bps) |
|---|---:|---:|
| A-rel_1d | −12.7 | **−29.8** |
| A-rel_3d | −20.7 | **−49.1** |
| A-rel_10d | −14.6 | **−36.2** |
| A-rel_20d | −16.2 | −25.4 |
| C-voladj_20 | −16.4 | **−33.9** |
| B-pull_20_5 | +1.9 | +13.2 |
| D-relvol_20 | −1.1 | −23.4 |

## Reading

- For the momentum / vol-adjusted families the reversal is **markedly stronger among later-removed
  constituents** (roughly 2× more negative). Chasing recent relative strength in a name that would
  later be dropped from the index is the worst version of the trade.
- **Implication for Task 95E:** the 35-name survivor-selected universe was *masking* the true
  (negative) cross-sectional momentum effect — restricting to eventual survivors removed exactly the
  names where the reversal bites hardest, and the tiny 7-name bucket then over-weighted a few
  survivors that kept running. Removing survivorship bias makes the signal **more** negative, not
  positive.
- Family B's mild positive is also slightly larger among removed names (+13.2 vs +1.9) — a
  reversal/stress flavour, not a survivor effect. It still fails every economic gate.

## Verdict

`SURVIVORSHIP_CONTROL` = **strong and confirmed**: the broad-universe result is not survivorship-
biased, and the direction of the bias in Task 95E's universe was to *hide* a negative effect. No
family shows a signal that exists only in survivors.
