# Task 75S — Stage 4: LOW_CONFLUENCE Gate Correctness Audit

**No threshold, formula, or code was changed. This is a read-only audit plus deterministic boundary
tests using the existing, unmodified functions.**

## Formula and documented intended rule (LEGACY contract -- the only one production/live may use)
`talonx_quant/strategy.py::_confluence_score` (0-3 point scale, read-only inspection):
- **MACD leg** (+1): `_macd_crossed_this_bar(s) and not own_trigger_is_macd` -- an independent
  MACD/signal-line cross on this bar, EXCLUDED if this candidate's own trigger IS that same cross
  (`signal_type in (MACD_BULLISH_CROSS, MACD_BEARISH_CROSS)`). This is the documented "No-Self-Credit"
  rule (2026-08-22, Task 47/49).
- **RSI leg** (+1): direction-aware -- `rsi < config.rsi_oversold` for BULLISH,
  `rsi > config.rsi_overbought` for BEARISH. No explicit `own_trigger_is_rsi` exclusion exists in this
  LEGACY function (unlike the separate, non-production `INDEPENDENT_CONFIRMATION_EXPERIMENTAL`
  contract's `evaluate_independent_confirmations`, which does have one) -- instead, self-exclusion is
  **structural**: the RSI-curl trigger (`RSI_OVERSOLD_VOLUME_SURGE`) fires when
  `rsi_prev < rsi_oversold and rsi >= rsi_oversold` (i.e. AT OR ABOVE the threshold on the trigger bar),
  while the confluence leg requires `rsi < rsi_oversold` (STRICTLY BELOW) -- mathematically disjoint at
  the same bar by construction, confirmed directly in code (`talonx_quant/strategy.py` lines 570-571 vs.
  230) and by a direct synthetic call at the exact boundary value (see below).
- **Volume leg** (+1): `volume_surge_ratio > volume_threshold` (session-appropriate threshold, not this
  gate's concern to define).
- Gate: `_confluence_eligible` (`talonx_quant/consumer.py:356-373`) --
  `(signal.confluence_score or 0) >= config.confluence_score_min` (default **2**) for the LEGACY
  contract used in production/replay.

## Threshold source
`config.confluence_score_min` = `_env_int("TALONX_QUANT_CONFLUENCE_SCORE_MIN", 2)`
(`talonx_quant/config.py:308`) -- unchanged by this or Task 74S's work (`git diff 848de0d..HEAD --
talonx_quant/config.py`, empty).

## Boundary comparison semantics
Inclusive at the boundary (`>=`): a candidate with `confluence_score` **exactly equal to** the minimum
**passes**. Confirmed directly from real Task 74S telemetry: all 307 bullish candidates with
`confluence_score == 1` are absent from the published/executed population (rejected `LOW_CONFLUENCE`,
part of the aggregate 3,640 count); all 12 with `confluence_score == 2` are **not** among the
`LOW_CONFLUENCE` rejections (they clear this specific gate, though 8 fail on session grounds and the
remaining 4 fail a later gate -- see `surviving_candidate_trace.md`). No bullish candidate in this
dataset ever reached `confluence_score == 3` (an empirical fact about this sample, not a gate defect).

## Self-credit / duplicate-credit check, using real production telemetry
2,332 `macd_bullish_cross` candidates exist in the dataset. Since their own trigger IS the MACD cross,
the MACD leg is excluded for all of them -- their maximum possible score, from RSI+volume alone, is 2.
**Observed distribution: `{0: 2,125, 1: 207}` -- zero ever reach 2 or 3.** This is real-data evidence
that the exclusion is operative (no `macd_bullish_cross` candidate is ever credited for its own
trigger), consistent with -- though not conclusive proof against a hypothetical compensating bug, hence
the direct function-level check below.

## Direct, labeled boundary/self-credit tests (`TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE`)
Calling the real, unmodified `_confluence_score` directly with identical inputs, varying only
`signal_type` (see `boundary_test_results.txt`):
- Same bar (RSI=25 oversold, genuine MACD cross, volume surge 3.0x), labeled `MACD_BULLISH_CROSS` (own
  trigger): **score = 2** (RSI + volume only, MACD leg correctly excluded).
- The identical bar/inputs, labeled `RSI_OVERSOLD_VOLUME_SURGE` (MACD cross is independent of this
  trigger): **score = 3** (MACD + RSI + volume, MACD leg correctly credited since it's genuinely
  independent here).
- RSI exactly at the oversold threshold (30.0), volume surge present: **score = 1** (volume leg only --
  the RSI leg's `<` comparison is False at exactly 30, confirming the structural self-exclusion holds
  at the precise boundary value the RSI-curl trigger itself produces).

All three results match the documented design exactly.

## NaN / missing-input handling
`if s.rsi is not None: ...` and `if s.volume_surge_ratio is not None: ...` -- both legs contribute 0
(not an exception, not a fail-closed reject) when their input is missing; `_confluence_eligible`'s
`(signal.confluence_score or 0)` additionally guards a `None` total score to 0, which correctly fails
the `>=` comparison (fail-closed at the eligibility check, not silently passing on missing data).

## Agreement between production and replay paths
`talonx_backtest/engine.py` imports `_confluence_eligible` **directly** from `talonx_quant.consumer`
(line 101) and `evaluate_signals` (which calls `_confluence_score` internally) directly from
`talonx_quant.strategy` (line 114) -- the same function objects, not reimplementations. Agreement is
guaranteed by construction.

## Verdict
**No implementation/specification mismatch found.** Both the MACD no-self-credit rule and the RSI
structural self-exclusion behave exactly as documented, confirmed by direct invocation of the real
functions at the exact boundary values plus corroborating real-data distributions. The 72.5%
candidate-level `LOW_CONFLUENCE` rejection rate is a correct consequence of a genuinely strict,
correctly-implemented threshold interacting with this sample's actual price/volume/indicator
co-occurrence patterns -- not evidence of a defect. This audit does not recommend lowering the
threshold or altering the self-credit rules to produce more trades.
