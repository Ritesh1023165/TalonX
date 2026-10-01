# TASK 93 — Phase 12: Baseline Comparators

Purpose: does TalonX add information beyond trivial behaviour? Machine-readable:
`_baseline_comparators.json`. All over Segment A (2025-01-24 → 2025-08-14, 35 symbols), 0 bps.

## 1. Buy-and-hold (context)

Equal-weight 35-name basket, first bar → last bar of Segment A: **+6.24%** (median symbol +4.09%;
22/35 symbols positive). Wide dispersion: PYPL −22.8% … AMD +47.1%. 2025 H1 was mildly up on average
despite the April tariff shock.

**Relevance:** TalonX is a long-only intraday R-multiple strategy that is flat ~99.99% of the time (one
349-minute position over 6.7 months). It captures essentially **none** of the +6.24% basket drift —
and it is not designed to (it is not a hold strategy). This comparator mainly establishes that the
period was *not* a bear market that would explain the lack of long setups — the market was up; the
strategy still found ~nothing.

## 2. Random eligible long entry, matched holding (the key comparator)

Rule: pick a random regular-session bar (from the 2.56M-row volatility telemetry), enter long at its
close, exit after **349 minutes** (the actual trade's holding time) or at data end, 0 bps.
n ≈ 16,000 valid draws.

| | mean | median | hit-rate | std |
|---|---:|---:|---:|---:|
| Random eligible long, 349-min hold | **+4.06 bps** | +0.52 bps | 50.2% | 203 bps |
| **The 1 actual TalonX trade** | **+245 bps** (+5.99 R) | — | — | — |

The random-entry distribution is a **coin flip** (hit-rate 50.2%, mean ≈ +4 bps ≈ 0). The single
TalonX trade sits **≈ +1.2 σ** above the random mean — a result that a *single* random entry beats
about **1 time in 9**. TalonX's one trade is **inside the noise band of one lucky random draw.**

With n = 1 there is no way to show TalonX's *selection* adds anything over random entry — you would
need a population to compare distributions. Segment B (Task 74S) produced 0 trades, so it cannot help
either.

## 3. Simple momentum / regime baselines (not overbuilt)

Not implemented as separate replays — with a 1-trade strategy population there is nothing to compare a
benchmark *against*. The Phase 7 counterfactual already provides the relevant signal-quality
comparison: bars passing the volatility gate drift ~+30 bps to EOD vs ~0 for rejected bars and ~+0.2
bps for random bars — i.e. the strategy's *gates* do carry mild selection information, but the strategy
as a whole converts that into ~zero trades.

## Conclusion

- The 2025 H1 market was **up** (+6.2% basket) — the near-total absence of long setups is a property of
  the strategy's gates, not a hostile tape.
- Random eligible long entry over this universe/period has **no edge** (50.2% hit, ~0 mean).
- TalonX's single trade is **not statistically distinguishable** from one lucky random entry.
- **TalonX cannot be shown to add information beyond trivial behaviour** at this sample size — not
  because it was beaten, but because it did not produce enough trades to be compared.
