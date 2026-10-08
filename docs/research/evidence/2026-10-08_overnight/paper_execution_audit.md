# Paper-execution realism audit (2026-10-08 overnight)

This audit covers code and stored configuration only. It recomputes no profitability, changes no accounting and tunes
no costs. The behaviours below are pinned by `tests/test_paper_execution_realism_audit.py` (7 characterisation tests on
synthetic bars).

Classification used throughout: **DEFECT** = behaviour that contradicts its own stated contract or can silently
produce a better-than-achievable result. **LIMITATION** = a declared modelling simplification.

## Per lane

### 1. Opportunity promotion `paper_outcomes`

Code: `talonx_opportunity/promotion.py::Promoter._outcomes`, `measure_long`.

| Item | Actual behaviour |
|---|---|
| Output type | **Markout**: long, gross, +15m / +30m / +1h / session close, MFE / MAE. Not a simulated trade |
| Decision time vs data time | Reference = the candidate's `data_as_of_utc` and `last_price`. That is roughly 15–20 min **before** the promotion decision and any Telegram send (SIP 15-min delay plus scan cadence) |
| Entry price available after the decision? | **No.** The reference price predates the decision, so a move between data time and alert time is credited (test: +10% at minute 16 shows as `ret_30m = +10%`, `CONFIRMED`) |
| Delay / finality | +h uses the last 1-min bar *completed* by ref + h (causal); close = last bar before the session close |
| Costs / spread / size / liquidity | None: gross percentages, no size |
| Missing bars | The horizon stays `None` / `OUTCOME_PENDING`; no fill is invented (test). A thinly traded name uses the last traded bar (possibly stale) |
| Halts / gaps / stops | No stop. Gaps are captured in markouts |
| Corporate actions | Intraday only; not applicable within a session |

**Finding (LIMITATION, high misreading risk).** These markouts measure the *signal's* information from data time. They
are **not** an achievable alert-follower's P&L. Any report quoting `ret_*_pct` as alert performance overstates
actionability; the VR ACTIONABLE arm exists to measure that. Labelling is the fix, not a code change.

### 2. VR_PAPER_V1 (VIRTUAL_REALTIME and ACTIONABLE)

Code: `talonx_paperperf/vr_live.py`, `vr_paper.py` (`open_trade`, `run_exit`, `VirtualClock`, `POLICY`). Existing tests:
`tests/test_vr_live.py`, `tests/test_vr_paper.py`, `tests/test_vr_entry_control_and_review_alerts.py`.

| Item | VIRTUAL_REALTIME | ACTIONABLE |
|---|---|---|
| Output type | Simulated trade + per-arm $100k portfolio ($10k per position, max 10 open) | Same |
| Decision / entry time | Data time (`data_as_of`): a *counterfactual* "if the data had been real-time" | `ceil_minute(Telegram sent_at_utc)`: real delivery time; SENT_AFTER_FLATTEN since 2026-10-07 |
| Entry price | Open of the first 1-min bar starting at or after decision/send, within 10 min (else `NO_ENTRY_BAR`); never a bar that ended before the send | Same |
| Virtual clock | Only bars closed by T = wall − 16 min are visible (causal) | Same |
| Stop / target | First touch wins, **stop before target in the same bar**. Gap-through fills at the **open** (worse), never at the trigger (test). An intrabar touch fills exactly at the level (no slippage beyond the level) | Same |
| Costs | `max(20 bps, measured entry spread)` subtracted once from gross; spread from a historical quote at entry | Same |
| Liquidity / partial fills | Fixed $10k notional, **no volume cap, no partial fills**, no market impact | Same |
| Missing bars | `NO_BARS` → no exit and stays OPEN; no entry → skipped with reason. Session exit = last bar before the 15:50 ET flatten (could be stale for illiquid names) | Same |
| Halts | No halt data; a halt appears as missing bars, and re-open gaps fill at the open | Same |
| Corporate actions | Intraday only; not applicable |

**Findings.**
- VIRTUAL_REALTIME is explicitly counterfactual (declared). The ACTIONABLE arm is the realistic one.
- Exact level fills on intrabar touches, and no size or volume limit, are LIMITATIONS. Both are optimistic for
  illiquid names.
- Entry collection is now interrupted by owner decision (`entry_control.json`).

### 3. Original paper accounting (`talonx_paper`, `~/.talonx/paper_trading.db`)

Code: `talonx_paper/consumer.py` (`_execute_buy`, `_handle_market_tick`, `_run_eod_flatten_once`), `talonx_paper/engine.py`
(`check_stop_take`, `apply_spread`), `talonx_paper/config.py`.

| Item | Actual behaviour |
|---|---|
| Output type | Simulated trade ledger. **0 trades ever** in the current ledger (`trade_history` empty) |
| Entry | Alert's decision price ± half the simulated spread (`TALONX_PAPER_SIMULATED_SPREAD_BPS`, default 5 bps). It is the price *in the alert*, not a quote observed after the alert was processed |
| Exit | On each market tick, `check_stop_take` evaluates the tick **close** only. An intrabar touch that closes back inside is not an exit; a gap-through close fills at that close minus half the spread (test). EOD flatten at `latest_prices` |
| Size / fees / liquidity | $2,500 default allocation; no fees; no volume cap |
| Corporate actions | Intraday only; not applicable |

**Finding (LIMITATION).** Entry at the alert's own price is optimistic when processing is delayed. This is moot in
practice: the lane has never traded.

### 4. V2 paper companion (`talonx_v2`, `v2_release_rc1.db`)

Code: `talonx_v2/paper.py`, `sizing.py` (`zero_fee`, `size_whole_shares_fee_inclusive`), `pricing.py`, `sip_adapter.py`,
`provider_contract.py`.

| Item | Actual behaviour |
|---|---|
| Output type | Simulated trade + campaign portfolio ($100k, $10k per position, max 20) |
| Decision / entry | Episode fires at the 2nd distinct insider's filing date (causal = end of that day). Entry = **SIP daily open** of the first session strictly after the fire (Alpaca `o` = first eligible trade, **not** the opening-auction print; declared in the release config). A durable intent must exist before that session's OPEN phase (cold start rejected) |
| Exit | SIP daily close (official closing cross) of entry + 10 sessions. A missing bar falls forward up to 5 sessions, else `EXIT_UNRESOLVED` (never a favourable fill) |
| Finality | Bars are usable only after close + 4h + 15 min + 1 min (V2_RELEASE_PRICE_CONTRACT@1) |
| Costs | **Zero fee, no spread, no slippage** (`sizing.zero_fee`, "frozen, approved"). Research used 20 bps round trip |
| Liquidity | Eligibility uses median $vol ≥ $5M and close ≥ $5; **no fill-size cap** (1,000 shares at $10 regardless of volume, test) |
| Corporate actions | Alpaca corporate-actions guard (splits; dividends accrued/credited), split-adjusted prices |

**Finding (credibility gap).** Live V2 paper P&L is frictionless, while its research expectancy is net of 20 bps.
Comparing the two without adjustment overstates live paper results by about 20 bps per trade. This is a declared
frozen assumption (S10-22 / OPS-014 unresolved), not a code defect.

## Risk data inventory

| Risk input | Available? | Where |
|---|---|---|
| Volatility | **Observed**: `atr20_pct`, `range_position`, `trend5_pct`, premarket high/low/volume | `opportunity.db candidate_events.features_json` |
| Spread | **Partial**: historical quote at VR entry (research), DTU shadow sampled NBBO per snapshot. **Not** in OE candidate features or alerts | `talonx_paperperf`, `talonx_shadow/dtu.py` |
| Liquidity | **Observed**: ADV20 (shares, $), live floors | features; `market.db dtu_snapshot` |
| Halts / LULD | **Missing visibility**: no halt or LULD feed anywhere in the codebase | — |
| Catalyst provenance | **Observed** for SEC 8-K (EDGAR accession, provenance) and gaps. No news feed in OE | `candidate_events.catalyst`, `sec_refresh.py` |
| Manipulation | **Cannot be established** from 1-min bars plus 8-K metadata. No order-book, venue, borrow or social data. No claim is made | — |

## Prioritised improvements (at most five, by effect on result credibility; none built tonight)

1. **Label promotion `paper_outcomes` as "markout from data time (pre-alert), gross"** on the dashboard and in
   reports. Report the ACTIONABLE-arm (send-time) measure beside it whenever alert performance is discussed.
2. **Show V2 live paper P&L both frictionless and at the research 20 bps** (display only; do not change the frozen
   ledger) so live and research numbers are comparable.
3. **Add a fill-capacity check to the simulators** (for example, flag trades whose $10k exceeds x% of the entry bar's
   dollar volume) as a *reported flag* first, for VR and V2.
4. **Make stale session-close and illiquid exits visible.** Record the age of the last bar used for VR session exits
   and promotion closes, and flag age above N minutes.
5. **Surface quote spread in OE review alerts and features** where a quote is available, and state explicitly that no
   halt/LULD data exists.
