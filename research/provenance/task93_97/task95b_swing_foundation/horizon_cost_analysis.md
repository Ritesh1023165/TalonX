# TASK 95B — Phase 3 — Cost-to-Move Baseline & Early-Stop Decision

**First-principle question:** does increasing the holding horizon produce moves large enough that a
one-off round-trip cost becomes economically small relative to the opportunity?

Data: `horizon_cost_baseline.csv` (327 rows), `_horizon_cost.json`. **Unconditional** long forward
returns — no signal. Round-trip cost modelled as `2 × c` bps of notional (`c` ∈ {0,2,5,10,20}).
`drift_to_cost_5bps` = mean forward drift ÷ 10 bps (the 5-bps round trip).

## Headline — unconditional long, full 35-symbol sample, 2020–2026

| Horizon | abs median move | mean drift | pos-hit | net mean @5 bps | net @10 bps | drift ÷ cost(5 bps) |
|---|---:|---:|---:|---:|---:|---:|
| *(Task 95A ref: 30 min opening drift)* | *~35 bps* | *+5 bps* | *~53 %* | *~0* | *neg* | ***~0.5*** |
| 60 min | 45 bps | −0.3 bps | 50.1 % | −10.3 | −20.3 | −0.03 |
| 120 min | 56 bps | +1.9 bps | 51.1 % | −8.1 | −18.1 | 0.19 |
| 240 min | 68 bps | +2.5 bps | 51.2 % | −7.5 | −17.5 | 0.25 |
| overnight | 55 bps | +5.0 bps | 53.4 % | −5.1 | −15.1 | 0.50 |
| **1 day** | 116 bps | +9.6 bps | 52.2 % | −0.4 | −10.4 | **0.96** |
| **2 day** | 169 bps | +18.8 bps | 53.3 % | **+8.8** | −1.2 | **1.88** |
| **3 day** | 209 bps | +28.3 bps | 53.6 % | **+18.3** | **+8.3** | **2.83** |
| **5 day** | 277 bps | +46.6 bps | 54.3 % | **+36.6** | **+26.6** | **4.66** |
| **10 day** | 404 bps | +91.8 bps | 55.6 % | **+81.8** | **+71.8** | **9.18** |

## Reading

1. **Bridge horizons stay cost-blocked.** 60–240 min: drift ÷ cost < 0.25, net-negative at 5 bps.
   This *confirms* the Task 95A wall and the instruction not to reopen intraday mining.
2. **Swing horizons cross the cost line.** From 2 days out, unconditional long has **net-positive
   expectancy after a 5-bps round trip** (+8.8 → +81.8 bps); from 3 days out it survives 10 bps. The
   typical absolute move grows ~8–11× (35 bps → 277–404 bps) while the round-trip cost is fixed, so
   the move-to-cost ratio rises from ~0.5 (intraday, blocked) to **1.9–9.2** (2–10 day).
3. **But this is mostly market beta, not alpha.** `pos_hit` is only 52–56 %. The positive drift is
   what a bull-heavy 2020–2026 basket of 35 mega-cap tech names produces mechanically:
   - **2022 (bear year): 5-day drift = −51 bps, net @5 bps = −61 bps, pos-hit 46.7 %.**
   - Every other year positive (+45 to +96 bps / 5 day).
   - 5 of 35 symbols (CMCSA, INTC, MDLZ, PEP, PYPL) have negative net @5 bps at 5 day.
4. **Regime skew — a genuine lead.** At the 5-day horizon the unconditional drift is markedly
   higher after weakness / in stress:
   | Regime | 5-day mean drift | net @10 bps |
   |---|---:|---:|
   | `rv60` high (top quintile) | **+118 bps** | +98 |
   | `rv60` low (bottom quintile) | +17 bps | −3 |
   | trend bear (below 50-day SMA) | +60 bps | +40 |
   | trend bull | +36 bps | +16 |
   | drawdown > 20 % from high | +65 bps | +45 |
   This is the *opposite* of the intraday finding (where high vol did not help) and points Families
   B (pullback) and D (oversold rebound) at the high-vol / drawdown regime — with the caveat that
   these slices overlap the 2020 crash-recovery and 2022→2023 turn, so concentration/outlier tests
   (Phase 13) and overlapping-sample CIs (Phase 12) are decisive.

## EARLY-STOP DECISION

> *"If no longer horizon provides materially better move-to-cost economics than intraday → return
> `SWING_HORIZON_ECONOMICS_NOT_PROMISING` and STOP."*

**Do NOT stop.** Swing horizons (2–10 trading days) provide **materially better** move-to-cost
economics than intraday: drift ÷ cost rises from ~0.5 to 1.9–9.2, the absolute move is ~8–11× larger
against a fixed cost, and net expectancy is positive after 5 bps (and after 10 bps from 3 days out).
Proceed to Phases 4–17.

## Constraints this analysis places on the rest of Task 95B

- **The bar is excess return, not net-positive return.** Unconditional long already clears cost at
  swing horizons in this sample. Every candidate must beat the **unconditional-long / benchmark**
  comparator (Phase 15), by a margin, in discovery — a positive net expectancy alone is not a pass.
- **Regime dependence is expected.** 2022 shows the unconditional swing long is negative in a bear;
  candidates must be evaluated by regime (Phase 10) and a regime-specific candidate is acceptable
  only if the regime is causally observable before entry.
- **Overlap correction is mandatory** for every k-day CI (Phase 12).
- Bridge horizons are dropped from Phases 5–17 (confirmed cost-blocked).
