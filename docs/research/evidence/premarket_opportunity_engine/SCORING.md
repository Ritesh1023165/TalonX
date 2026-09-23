# Features, hard gates and score

**Config:** `talonx_premarket/config.py`, `PREMARKET_RESEARCH_V1`. It is immutable and has content fingerprint **`62ba413daf85e674`**.

The config was pinned in `talonx_premarket/frozen_config.json` and committed in `fb673f5` (21:19Z on 2026-09-23), **before** the 2026-09-23 shadow replay was run. A test fails if the config drifts from the pin. **No weight or threshold was changed after the replay.**

**The one post-freeze change.** Commit `f4bf44e` changed the *order* in which the per-session new-alert cap is applied: it was alphabetical, and is now highest score first. The defect showed in the replay's candidate list before any outcome had been computed. The config and its fingerprint did not change.

## Funnel

`UNIVERSE → ELIGIBLE → DATA_READY → HARD_REJECTED | SCORED → WATCH | BULLISH_SETUP | BEARISH_SETUP`

A symbol with no pre-market print is simply **not data-ready**: there is no pre-market price, so there is no gap to measure. That is absence of data, not a filter. Everything that is data-ready and valid is scored. Softer quality differences lower the score but **never reject**. This avoids another waterfall that eliminates nearly every symbol.

## Features

All features are causal, computed from bars complete as of `now − 15 min`.

| Group | Feature |
|---|---|
| Price | previous close (XNYS previous session); latest pre-market price (last complete 1-min bar); **gap %**; pre-market high/low |
| Activity | pre-market share volume; pre-market dollar volume (Σ v·vwap); 1-min bar count; trade count; **activity = pre-market volume / 20-session ADV** |
| Liquidity proxy | 20-session average dollar volume; pre-market dollar volume |
| Structure | previous-session range (high/low); range position (ABOVE_PREV_HIGH / BELOW_PREV_LOW / INSIDE); 5-session trend; 20-session ATR% |
| Catalyst | SEC filings on the previous session or the scan day with resolved acceptance at or before the decision time (8-K with items, 6-K, offering forms, 13D, …); TalonX insider-ledger open-market buyers over 30 days (received by the decision time) |

No AI and no ML.

## Hard gates (genuine invalidity only)

| Code | Rule |
|---|---|
| `INSUFFICIENT_DAILY_HISTORY` | fewer than 5 daily bars (not data-ready) |
| `MISSING_PREVIOUS_SESSION_BAR` | last daily bar is not the XNYS previous session (not data-ready) |
| `NO_PREMARKET_PRINTS` | no valid pre-market bar yet (not data-ready) |
| `INVALID_NUMERIC` | a non-finite price or ATR |
| `PRICE_BELOW_MIN` | previous close below $1.00 |
| `INSUFFICIENT_LIQUIDITY` | 20-session average dollar volume below $1,000,000 |
| `STALE_PREMARKET_PRICE` | last pre-market print more than 45 min before data as-of |
| `INVALID_TIMESTAMP` | last print later than data as-of |
| `IMPLAUSIBLE_GAP` | abs(gap) above 300% |

## Score (0–100, fixed weights)

Each component is a quality between 0 and 1, multiplied by its weight.

| Component | Weight | Quality = 1.0 at | Formula |
|---|---|---|---|
| gap | 30 | abs(gap) = 1.5 × own ATR20% | `min(abs(gap%) / ATR20% / 1.5, 1)` |
| activity | 25 | pre-market volume = 10% of ADV20 | `min(pmVol / ADV20 / 0.10, 1)` |
| liquidity | 15 | pre-market $ volume ≥ $10M ($100k → 0) | `clip((log10(pm$) − 5) / 2, 0, 1)` |
| catalyst | 15 | STRONG = 1.0, OTHER = 0.6, NONE = 0 | STRONG = 8-K/6-K/offering/13D/…, or 2+ insider open-market buyers |
| structure | 10 | beyond the previous-day range in the gap direction | 1.0 beyond range; 0.5 inside range but 5-day trend aligned; else 0 |
| data confidence | 5 | 20+ pre-market 1-min bars | `min(bars / 20, 1)` |

Every alert prints each component and a plain-language "Why:" line, for example `gap +6.00% = 3.2x its 20d ATR (1.87%)`.

## Classification

| Class | Rule |
|---|---|
| `BULLISH_SETUP` / `BEARISH_SETUP` | abs(gap) ≥ 3%, score ≥ 60 and pre-market $ volume ≥ $500k (the sign of the gap picks the side) |
| `WATCH` | abs(gap) ≥ 2% and score ≥ 40 |
| `SCORED` | everything else that passed the hard gates |

Catalyst lookups (SEC requests) run only for abs(gap) ≥ 2%, which keeps SEC traffic bounded.

**Meaning.** These classes are descriptive research labels about what the pre-market tape and filings show. They are **not** predictions and **not** trade instructions. Nothing in this lane places, sizes or simulates an order.
