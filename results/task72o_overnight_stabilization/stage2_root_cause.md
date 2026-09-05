# Stage 2 -- Root Cause

## Classification: TEST_ISOLATION_DEFECT (stale fixture, not a product defect)

## Evidence chain

1. `examples/data/sample_AAPL_trade_1m.csv` was added in commit `e094336`
   (2026-08-16 19:35 +0100).
2. `talonx_quant.config.QuantConfig.confluence_score_min=2` already existed
   before that (commit `2477b1f`, 2026-08-12) -- so the fixture was created
   AFTER the confluence gate existed in principle.
3. However, commit `3c97d9d` ("test(quant): lock state-based RSI
   confluence contract", 2026-08-21 -- AFTER the fixture) CONFIRMED and
   locked (via its own dedicated regression suite,
   `tests/test_quant_strategy.py`'s "RSI-Curl / Confluence Contract"
   section) an intentional, documented strategy behaviour: an
   `RSI_OVERSOLD_VOLUME_SURGE`/`RSI_OVERBOUGHT_VOLUME_SURGE` signal fires
   on the RSI RECOVERY bar, and its RSI confluence component is
   INTENTIONALLY zero on that same trigger bar (see
   `talonx_quant/config.py`'s own `confluence_score_min` docstring: "Such
   a candidate's score is therefore volume(1) alone unless a same-bar
   MACD cross also coincides (-> 2, clearing this gate)").
4. The fixture's one intended target trade IS exactly this shape (an
   RSI-recovery/volume-surge candidate, per the rejected_signals.csv
   evidence: `LOW_CONFLUENCE` at `2026-01-06 15:21:00Z`, immediately
   after ~256 benign `LOW_VOLATILITY` rejections during the flat
   preceding period). It scores only 1 (volume), because it has no
   coincident same-bar MACD cross -- exactly the documented, INTENTIONAL
   exclusion rule from commit `3c97d9d`.
5. The fixture predates that confirmation commit by 5 days and was never
   recalibrated afterward to include a compensating confluence factor
   (e.g. a coincident MACD cross) that the NOW-confirmed-correct strategy
   rule requires.

## Why this is not a PRODUCT_CODE_DEFECT

`talonx_quant/strategy.py`'s RSI-curl/confluence behaviour is exactly as
designed and is independently protected by its own passing regression
suite (`tests/test_quant_strategy.py`). Nothing here suggests the
strategy logic itself is wrong -- the fixture data simply does not (and
was likely never verified to) satisfy the CURRENT, intentionally-tightened
gate.

## Why no fix was implemented this task

The correct fix is a targeted edit to
`examples/data/sample_AAPL_trade_1m.csv` (NOT a protected file) --
recalibrating the OHLCV pattern around the target bar so a same-bar MACD
cross (or another qualifying confluence factor) coincides with the
existing RSI-recovery/volume-surge trigger, restoring a genuine score>=2
candidate that also still clears every other unmodified gate (ATR/
volatility, structural R:R, blackout windows). This requires iterative,
verified reconstruction against the real (unmodified) indicator
functions to avoid producing a "fix" that merely LOOKS green without
being independently demonstrated correct -- explicitly the kind of risk
this task instructs against ("Do not weaken assertions... implement a fix
only if correctness is independently demonstrable"). Given this overnight
task's remaining stage count and token budget, this was judged unsafe to
attempt casually within the remaining time and is deferred, evidence
preserved, rather than risk an unverified data edit.

## Verdict: Stage 2 BLOCKED (not a protected-file blocker -- a scope/time
deferral of a fixture-data recalibration, with full root-cause evidence
preserved for a dedicated follow-up task). No code was modified. Working
tree remains clean aside from this task's own journal/status files.
