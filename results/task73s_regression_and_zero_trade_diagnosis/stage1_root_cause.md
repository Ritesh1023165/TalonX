# Stage 1 -- Root Cause (Independently Verified, with a Correction)

## Overall classification confirmed: TEST_ISOLATION_DEFECT (stale fixture, not a product defect)

Task 72O's classification (`TEST_ISOLATION_DEFECT`) is **confirmed correct**.
However, its specific mechanism was **misidentified** -- corrected below with
direct code/telemetry evidence.

## What Task 72O's Stage 2 claimed

That the rejected candidate was an `RSI_OVERSOLD_VOLUME_SURGE` (bullish)
signal, blocked by the 2026-08-21 commit `3c97d9d` ("lock state-based RSI
confluence contract").

## What the evidence actually shows

Running the original 462-row fixture through `talonx_backtest --research-telemetry`
and reading `*_research_candidate_telemetry.csv` directly:

```
timestamp,symbol,direction,signal_type,...,confluence_score,...
2026-01-06 15:21:00+00:00,AAPL,bearish,macd_bearish_cross,...,confluence_score=1,...
```

**The rejected candidate is `macd_bearish_cross` (BEARISH), not an RSI-recovery
signal.** Tracing `_confluence_score` (`talonx_quant/strategy.py`) for this
exact candidate: `rsi=76.43 > rsi_overbought(70)` -> the RSI leg SHOULD score
for a bearish candidate (+1) -- and it does. The MACD leg is EXCLUDED because
`own_trigger_is_macd=True` (its own trigger IS the MACD cross) -- this is the
**"No-Self-Credit" rule (Task 47/49)**, introduced in commit `83aee8b`
("fix(quant): require independent confirmation for MACD candidates",
**2026-08-22**), NOT the RSI-curl rule (`3c97d9d`, 2026-08-21). Volume
(1.22x) is below `volume_surge_ratio_threshold` (2.0x), so the volume leg
doesn't score either. Total: `0(macd, self-excluded) + 1(rsi) + 0(volume) = 1`,
below `confluence_score_min=2`.

`git merge-base --is-ancestor` confirms: `83aee8b` (2026-08-22) is a
descendant of `e094336` (the fixture's own creation commit, 2026-08-16) --
i.e. it postdates the fixture, same as `3c97d9d` does. Both rules are
legitimate, both postdate the fixture; **the specific rule that broke this
specific candidate is the MACD self-credit exclusion, not the RSI-curl
rule.**

## An even deeper, previously-undocumented layer

Even after computing a bullish candidate that clears `confluence_score_min`,
attempting to construct one revealed a **second, independent blocker**:
`talonx_quant/consumer.py`'s HTF trend gate (`trend_gate_applicable`,
BULLISH-only, requires 200 real 15-minute regular-session bars before
`htf_sma_200` is anything but `None`) rejects EVERY bullish candidate in
this 2-day fixture as `HTF_DATA_UNAVAILABLE` -- there is no way for a
~460-row, 2-day file to ever accumulate 200 RTH 15-minute bars (needs
~7.7 trading days minimum). This is independently corroborated by a
**pre-existing code comment already in this repository**
(`tests/test_backtest_sample_data.py`'s `_XFAIL_PENDING_SAMPLE_DATA_REGENERATION`
marker, written at Task 25A, 2026-08-20): "Regenerating these CSVs as
genuine BULLISH long demonstrations... requires real 200-bar/15-min HTF
trend-gate warmup... not a small data tweak" -- exactly what this task's
independent investigation found from scratch.

## Documented rule confirmation + existing tests located (Stage 1 item 3)

- MACD self-credit exclusion: `talonx_quant/strategy.py::_confluence_score`
  (docstring: "No-Self-Credit (2026-08-22 requirement-alignment fix, Task
  47/49)"), commit `83aee8b`.
- Existing, ALREADY-COMPREHENSIVE boundary-coverage tests:
  `tests/test_quant_strategy.py` lines ~339-437, section "No-Self-Credit
  Contract (Task 49...)": `test_case_a_macd_trigger_alone_does_not_satisfy_confluence`
  (score=0), `test_case_b_.../test_case_d_...` (score=1, below threshold,
  RSI-only and volume-only respectively), `test_case_macd_trigger_plus_rsi_and_volume_reaches_threshold`
  (score=2, AT threshold, both bullish and bearish). **These already
  satisfy Stage 1's boundary-coverage requirement (below/at threshold) for
  the exact rule that broke this fixture** -- no new unit test was needed
  to duplicate this existing, precise coverage.
- RSI-curl structural exclusion (the ADJACENT, correctly-cited-but-not-
  actually-applicable-here rule): `talonx_quant/strategy.py::evaluate_independent_confirmations`'s
  docstring + the RSI trigger function itself (`recovered_from_oversold =
  rsi_prev < 30 and rsi >= 30`, mathematically disjoint from the confluence
  leg's own `rsi < 30` requirement) + `tests/test_quant_strategy.py`'s
  "RSI-Curl / Confluence Contract" section (~line 518-599).
- HTF trend-gate-vs-bullish-fixture-size conflict: `talonx_quant/consumer.py::_trend_gate_applicable`,
  `talonx_quant/config.py`'s `htf_sma_period=200`/`rth_only_htf_sma=True`
  docstrings, and the pre-existing `_XFAIL_PENDING_SAMPLE_DATA_REGENERATION`
  marker in `tests/test_backtest_sample_data.py`.

## Why this remains TEST_ISOLATION_DEFECT, not PRODUCT_CODE_DEFECT

Both the MACD self-credit rule and the HTF trend gate are exactly as
designed and independently protected by their own passing regression
suites. The fixture is simply older than both rules and was never
recalibrated. No protected strategy file needed to change to fix this --
see `stage1_fixture_diff_explanation.md` for the actual repair (pure
fixture-data construction).
