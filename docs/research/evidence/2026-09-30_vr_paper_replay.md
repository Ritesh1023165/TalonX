# VR_PAPER_V1: virtual-realtime intraday paper lifecycle, replay of 2026-09-28 and 2026-09-29

- **Scope:** research and paper only. No broker, no live Signal change.
- **Version:** `VR_PAPER_V1`, policy fingerprint `0d09f1427cb2c965`.
- **Code:** `talonx_paperperf/vr_paper.py` (engine), `vr_replay.py`, `vr_live.py`.
- **Output:** `results/vr_paper/replay_2026-09-28_2026-09-29.json`.

## Contract

The Opportunity Engine has **no** stop, target or position lifecycle: its outcome model is a fixed +30-minute
CONFIRMED/FAILED check. The only intraday paper lifecycle in TalonX is the archived V1 Quant and paper engine, reused
here **unmodified** and labelled `RESEARCH_BASELINE`.

| Item | Rule |
|---|---|
| Entry (virtual realtime) | open of the first 1-minute bar starting at or after the Signal's `data_as_of`. The virtual clock sees only closed bars. |
| Entry (actionable) | open of the first bar at or after the Telegram send time |
| Stop | prior-session S1 pivot, or entry − 1.5 × ATR(14) (`talonx_quant.strategy.calculate_trade_geometry`) |
| Target | prior-session R1 pivot, or entry + 2 × ATR |
| Reward/risk | reported only. V1's ≥ 1.5 gate is a V1 Signal gate and is **not** applied, so CONTROL eligibility is unchanged. |
| Time exit | 15:50 ET flatten, reported as `SESSION_CLOSE`. There is no other authoritative time exit. |
| Fills | per 1-minute bar; stop is checked before target; fills at the level, or at the bar open if price gapped through it |
| Cost | max(20 bps, measured entry spread) |
| Capital | $100k, $10k per position, at most 10 open |

## Primary comparison (307 Signals)

| Strategy | Trades | Gross | Net | Win (net) | PF | Portfolio net P&L | Max DD | Exits (target / stop / close) |
|---|---|---|---|---|---|---|---|---|
| CONTROL_FIXED_30M (actionable, forensic) | 274 | −0.055% | −0.573% | 30.3% | 0.28 | — | — | — |
| CONTROL_FIXED_30M (virtual-realtime entry) | 297 | **−0.270%** | −0.785% | 23.6% | 0.26 | — | — | — |
| **CONTROL_VR_LIFECYCLE** | 297 | **−0.094%** | **−0.608%** | 48.8% | 0.29 | −$1,942 (64 taken) | −2.6% | 191 / 3 / 103 |
| **CONTROL_ACTIONABLE_LIFECYCLE** | 286 | −0.026% | −0.532% | 31.5% | 0.35 | −$2,311 (49 taken) | −3.4% | 164 / 4 / 118 |
| PULLBACK_CONFIRMATION_V1 0.5% reclaim of prior bar high | 277 | −0.095% | −0.626% | 51.3% | 0.28 | −$3,525 | −4.4% | |
| PULLBACK_CONFIRMATION_V1 0.5% close above SMA5 | 275 | −0.138% | −0.671% | 51.6% | 0.28 | −$2,479 | −3.7% | |
| PULLBACK_CONFIRMATION_V1 1.0% reclaim of prior bar high | 190 | −0.160% | −0.785% | 49.5% | 0.28 | −$4,347 | −5.2% | |
| PULLBACK_CONFIRMATION_V1 1.0% close above SMA5 | 191 | −0.226% | −0.856% | 49.7% | 0.27 | −$3,045 | −4.1% | |
| PULLBACK_CONFIRMATION_V1 1.5% reclaim of prior bar high | 124 | −0.216% | −0.867% | 57.3% | 0.32 | −$4,206 | −5.4% | |
| PULLBACK_CONFIRMATION_V1 1.5% close above SMA5 | 126 | −0.377% | −1.061% | 53.2% | 0.27 | −$5,510 | −6.7% | |
| MEAN_REVERSION_REFERENCE (research short reference, V1 bearish geometry) | 297 | +0.113% | −0.401% | 23.2% | 0.52 | −$5,208 | −6.5% | 4 / 214 / 79 |

**DELAY_EFFECT (actionable − virtual realtime, lifecycle):**

| Measure | Difference |
|---|---|
| Gross | **+0.07pp** |
| Net | +0.08pp |
| Win rate | −17pp |
| P&L | −$369 |

At a fixed +30 minutes, the virtual-realtime entry is **worse** than the actionable one (−0.27% vs −0.06% gross). The
Signals fire after the move, and the 16 minutes of feed delay mostly let the price settle. **Free-feed delay is not what
destroys the edge; there is no edge to destroy.**

## Why the lifecycle looks the way it does: exit geometry

- **Stops and targets:**
  - Every trade uses the structural pivot geometry.
  - Because the Signals are gappers, the prior-day **S1 sits far below** the price and **R1 sits just above** it.
  - The median stop is **5.4%** below entry and the median target **0.53%** above.
  - The median reward/risk is **0.16**.
- **Timing:**
  - The target is hit first in 191 trades and the stop first in 3; the median time to target is 9 minutes.
  - Wins are small, costs are about 0.5%, and the losers are held to the flatten.
- **Path, virtual-realtime entry:**

  | Event | Median time | Share of trades |
  |---|---|---|
  | Maximum favourable excursion | 29 min | — |
  | Maximum adverse excursion | 52 min | — |
  | 0.5% pullback | 7 min | 96% |
  | 1% pullback | 19 min | 83% |
  | Recovery after a 0.5% pullback | 22 min | 59% |

  The best price came before the worst in 170 of 297 trades.
- **Conclusion:** the V1 exit geometry is mismatched to gap candidates. But fixed-horizon returns, with no geometry at
  all, are also ≤ 0, so **geometry is not the root cause**.

## DTU and liquidity (CONTROL_VR_LIFECYCLE)

- **DTU state:**

  | State | n | Gross | Net | PF |
  |---|---|---|---|---|
  | Core | 72 | −0.03% | −0.29% | 0.43 |
  | Event-promoted | 220 | −0.12% | −0.72% | 0.27 |

  The event tier adds cost and slightly worse gross; it adds no alpha.
- **Spread:**

  | Spread | ≤ 25 bps | 25–50 bps | 50–100 bps | > 100 bps |
  |---|---|---|---|---|
  | Net | −0.31% | −0.49% | −0.95% | −2.09% |

  Gross is ≤ 0 in every band except > 100 bps (+0.08%, n = 30).
- **ADV and price:** no band has positive net; every gross is within ±0.35%.

## Mean-reversion reference (research short reference, never actionable)

The table shows the forward **long** return from the virtual-realtime entry, by gap size.

| Gap | n | 15m | 30m | 60m | Short-reference lifecycle net |
|---|---|---|---|---|---|
| 3–5% | 243 | −0.05% (t −1.0) | −0.08% (t −0.8) | −0.12% (t −1.5) | −0.33% |
| 5–10% | 39 | +0.04% | −0.50% (t −1.0) | −0.56% (t −1.1) | −0.42% |
| **10–20%** | **15** | **−2.17% (t −2.1)** | **−2.78% (t −1.9)** | −2.95% (t −1.8) | −1.56% (V1 short stop too tight) |
| 20%+ | 0 | — | — | — | — |

- Large gaps (10–20%) keep showing reversion, but on **n = 15**, from the same two sessions as the earlier alpha study.
  They are not independent evidence.

## Interpretation

- **`INTRADAY_PREMISE_FAILURE_SUPPORTED` / `NO_EDGE_OBSERVED`.** CONTROL_VR_LIFECYCLE gross is ≤ 0, so free-feed delay
  is definitively not the main problem.
- Pullback confirmation is worse at every depth.
- The exit geometry is mismatched (reward/risk 0.16), but no exit rule creates gross that isn't there at fixed
  horizons.
- **Only remaining lead:** reversion after 10%+ gaps. It is a candidate for a separately pre-registered **shadow** test,
  never a live short.
