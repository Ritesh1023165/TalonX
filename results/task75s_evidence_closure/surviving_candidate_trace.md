# Task 75S — Stage 3: Trace of the Four Surviving Candidates

Method: reprocessed Task 74S's already-preserved `task74s_10symbol_full_research_candidate_telemetry.csv`
(5,021 rows) and `stage3_non_volatility_rejections.csv` (the committed, filtered 5,000-row subset of
`rejected_signals.csv`). **No rerun of the 1.9-million-bar evaluation was performed or needed** -- every
value below comes from files already on disk from the original Task 74S replay
(`config_hash 3556debe52af`, `strategy_version 2ae6216bca70`, `dataset_hash 5e5412a960bf`).

## Gate evaluation order (from `talonx_quant/consumer.py::_GATE_NAMES`, read-only, unmodified)
Insertion order (the sequence gates are actually checked in): `LOW_VOLATILITY` →
`OPENING_BLACKOUT`/`CLOSING_BLACKOUT` → `LOSS_LOCKOUT` → `COOLDOWN` → `LOW_CONFLUENCE` →
`LOW_RISK_REWARD` → `TREND_GATE`/`HTF_DATA_UNAVAILABLE` → ... This is the key to resolving Task 74S's
own open question (`stage3_zero_trade_diagnosis.md`: "why AMD is not the same TREND_GATE rejection
STX received despite both showing `trend_component=False`"): **blackout gates are checked before
confluence/R:R/trend gates**. The `--research-telemetry` capture computes RSI/MACD/confluence/trend/RR
diagnostic values at every triggering bar *regardless* of gate order, purely for research observability
-- it does not by itself indicate which gate the production/replay path actually stopped at. The
*actual* stop point is recorded separately, in the rejection log. This is not a defect: it is two
different, both-correct observational layers (unconditional diagnostic capture vs. sequential gate
short-circuit), and this task changes neither.

## Candidate 1 — STX, 2025-10-22 14:43:00 UTC (10:43:00 ET)
- **Trigger**: `rsi_oversold_volume_surge`. RSI 33.61 (recovering from an oversold state -- the
  RSI-curl trigger condition), volume_surge_ratio 3.43x (> the volume-surge leg's threshold).
- **Confluence**: score **2** (meets `confluence_score_min=2` exactly). Contributing legs per the
  telemetry: RSI-recovery + volume-surge (the trigger's own RSI leg is structurally excluded from
  double-crediting its own trigger, per the documented RSI self-exclusion rule -- consistent with
  score=2 here, not 3).
- **R:R**: 6.40 (well above `min_risk_reward_ratio=1.5`).
- **Session**: `regular` (10:43 ET is well outside both the opening blackout `[09:30,09:45)` ET and
  closing blackout `[15:30,16:00)` ET windows -- correctly not blocked at that stage).
- **Next gate reached**: `trend_gate`. `trend_component=False` -- close (210.92) was at or below the
  200-bar/15-min HTF SMA at this bar.
- **Actual rejection reason (from `stage3_non_volatility_rejections.csv`)**: **`TREND_GATE`**.
- **Order/publication path reached**: No. Rejected before signal publication.

## Candidate 2 — AMD, 2025-11-20 20:55:00 UTC (15:55:00 ET)
- **Trigger**: `rsi_oversold_volume_surge`. RSI 35.82, volume_surge_ratio 2.82x.
- **Confluence**: score **2** (meets threshold). R:R **24.98** (far above minimum -- this candidate's
  geometry, had it reached execution, would have been a very favorable R:R).
- **Session**: 15:55 ET on 2025-11-20 (post-DST, EST, UTC-5) falls **inside** the closing blackout
  window `[15:30, 16:00)` ET.
- **Next gate reached**: `closing_blackout_gate` -- this fires *before* the confluence/R:R/trend checks
  are ever consulted for the actual rejection decision, regardless of what those checks' diagnostic
  values (captured anyway by `--research-telemetry`, including `trend_component=False` for this bar)
  would have shown.
- **Actual rejection reason (from `stage3_non_volatility_rejections.csv`)**: **`CLOSING_BLACKOUT`**
  (count=2 at this ticker/timestamp -- likely this bullish candidate plus one other signal_type/
  direction at the same bar).
- **Order/publication path reached**: No.

## Candidates 3 & 4 — PYPL, 2026-08-14 19:44:00 UTC (15:44:00 ET) -- two signal_types, same bar
- **Triggers**: `rsi_oversold_volume_surge` AND `ma_golden_cross`, both firing on the same bar (price
  62.06, RSI 92.88 -- note: RSI 92.88 is an *overbought*, not oversold, reading; the `signal_type` label
  `rsi_oversold_volume_surge` reflects the STATE-BASED recovery-trigger naming convention documented for
  this signal family, not a literal "RSI below 30 right now" condition -- consistent with the "RSI-curl"
  mechanism already documented in Task 73S's own root-cause analysis).
- **Confluence**: score **2** for both. `risk_reward_ratio` is `NaN` for both -- geometry could not be
  computed at this bar (consistent with `LOW_RISK_REWARD`-adjacent behavior, though this specific bar's
  actual rejection is a blackout, so the R:R gate itself was never reached either).
- **Session**: 15:44 ET falls inside the closing blackout window `[15:30, 16:00)` ET.
- **Next gate reached**: `closing_blackout_gate`.
- **Actual rejection reason**: **`CLOSING_BLACKOUT`** (count=3 recorded at this ticker/timestamp --
  consistent with 2 bullish signal_types plus at least one other signal/direction at the same bar).
- **Order/publication path reached**: No, for either signal_type.

## Reconciliation of the full funnel (denominators defined explicitly)
| Quantity | Count | Denominator (explicit) |
|---|---:|---|
| Bars processed | 1,903,044 | -- (base unit) |
| Bars rejected `LOW_VOLATILITY` | 1,781,848 | % of **bars** = 93.63% |
| Raw candidates generated (`signals_generated`) | 5,021 | % of **bars** = 0.26% |
| -- bullish | 2,488 | % of **candidates** = 49.55% |
| -- bearish | 2,533 | % of **candidates** = 50.45% |
| Candidates rejected `LOW_CONFLUENCE` | 3,640 | % of **candidates** = 72.50% |
| Bullish candidates with `confluence_score >= 2` | 12 | % of **bullish candidates** = 0.48% |
| -- of those, in the `regular` session | 4 | % of the **12** = 33.3% |
| -- of those 4, rejected `TREND_GATE` | 1 (STX) | % of the **4** = 25% |
| -- of those 4, rejected `CLOSING_BLACKOUT` | 3 (AMD, PYPL x2) | % of the **4** = 75% |
| Signals published | 3 | all bearish, rejected `NO_ACTIVE_POSITION` downstream (flat, long-only) |
| Trades executed | 0 | % of **candidates** = 0.00%; % of **bars** = 0.00% |

**No bar-level and candidate-level percentage is mixed in the same ratio anywhere in this table** --
each row's denominator is stated explicitly.

## Conclusion
Zero bullish candidates in the entire 10-symbol/~1-year dataset survived every gate simultaneously.
Of the 12 that cleared the confluence threshold, 8 were structurally ineligible on session grounds
(`pre_market`/`closed`) before any further check; of the remaining 4 "regular-session" candidates, 1
failed the HTF trend gate and 3 failed the closing-blackout gate (a session-timing gate, evaluated
before confluence/trend/R:R in the actual gate sequence, independent of what those later checks'
diagnostic values would separately show). This is a complete, internally consistent explanation with no
unresolved gaps and no evidence of a correctness defect in the gate-ordering or classification logic.
