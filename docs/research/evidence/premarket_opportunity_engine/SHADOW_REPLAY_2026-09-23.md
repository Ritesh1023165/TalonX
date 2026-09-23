# Shadow replay: 2026-09-23 (causal, read-only)

**Command:** `python -m talonx_premarket replay --date 2026-09-23 --v2-scope-log results/prospective_2026-09-23/logs/v2_companion.log`

**Engine:** `f4bf44e`. **Config:** `PREMARKET_RESEARCH_V1`, fingerprint `62ba413daf85e674`, frozen and committed before the replay (`fb673f5`, 21:19Z). **Nothing was routed** (`routed=NOT_ROUTED_REPLAY`). **No V2 state was modified.**

**Extracts:**
- `extracts/shadow_replay_2026-09-23_alerts.json`: all 223 alert events, with rendered text.
- `extracts/shadow_replay_2026-09-23_comparison.json`: every candidate, its classification, outcomes and the per-scan funnels.

## Causality

At each scheduled scan instant T (the same 41-scan XNYS schedule the live canary uses: 08:15Z–13:25Z, 15 min in EARLY and 5 min in CORE/NEAR_OPEN), the engine used only:
- daily bars for sessions **before** 09-23;
- SIP 1-min bars **complete by T − 15 min**, the live subscription's delay (`complete_bars_as_of`, tested);
- SEC filings from the previous or same session whose **resolved acceptance ≤ T**. Same-day filings whose acceptance can't be resolved are excluded;
- insider-ledger purchases **received by TalonX ≤ T**.

Regular-session bars were fetched **only after** the last pre-open scan, for alerted candidates, and are used **only** in the columns marked `*` (hindsight/evaluation). **No threshold, weight or classification was changed after these outcomes were computed.**

The one code change made during the replay was a correction to the order in which the cap is applied (commit `f4bf44e`). It was found from the candidate list of a partial run, before any outcome existed, and it does not touch the config.

## C1: broad universe vs the current 39

| Metric | Value |
|---|---|
| BROAD UNIVERSE | 14,373 assets → **5,655 eligible** |
| DATA READY | 1,418 at the first data-bearing scan (08:30Z) → **3,151** at the last pre-open scan (13:25Z) |
| SCORED (last scan) | 1,528. The largest hard-reject reason is `STALE_PREMARKET_PRICE` (897 thin names); then 417 `INSUFFICIENT_LIQUIDITY`, 309 `PRICE_BELOW_MIN`. No elimination waterfall. |
| CANDIDATES (alert-worthy identities, whole session) | **141** (84 alert-worthy at the 13:25Z scan) |
| ALERT-WORTHY and **within the per-session cap** (what the engine would have sent) | **25** |
| Suppressed by the 25-candidate cap | 116 (112 WATCH, 4 BULLISH_SETUP), all recorded, none alertable |
| Alert events | 223: WATCH 129, BULLISH_SETUP 14, BEARISH_SETUP 4, MATERIAL_UPDATE 67, INVALIDATED 9 |
| INSIDE 39 | **0**. No V2-scope name reached WATCH (abs(gap) ≥ 2% and score ≥ 40) on 09-23. |
| OUTSIDE 39 | **141** (all 25 within-cap alerts) |
| Provider cost | Alpaca 59 requests (a full-window prefetch); SEC 595 submissions requests (≤ 5/s); 0 data errors; 0 SEC errors |

**FINDING R1 (bounded, not tuned tonight).** The frozen V1 cap, 25 new candidates per session applied highest score first, was **used up entirely by the first data-bearing scan (08:30Z, 04:30 ET)**. The 116 candidates first seen from 08:30Z to 13:25Z were suppressed:

| First-seen hour | Candidates |
|---|---|
| 08:xx | 13 |
| 09:xx | 8 |
| 10:xx | 15 |
| 11:xx | 36 |
| 12:xx | 34 |
| 13:xx | 10 |

For a delivering canary this front-loads alerts to the thinnest part of the pre-market. I did **not** change the cap after seeing this. A pre-registered V1.1 option, such as a per-phase allocation or a rule that sends WATCH only from CORE_PREMARKET, should be decided **before** it is evaluated and would get a new fingerprint. Tomorrow's default canary is record-only, so every candidate, including suppressed ones, is still recorded for evaluation.

## C2: comparison with existing TalonX (actual Session 03 evidence)

**Evidence read (read-only or scratch copies):**
- the V2 release outbox, which had **0 TRADE_EVENT** on 09-23;
- Intelligence `intelligence_delivery`: SENT on 09-23 were only ADC at 11:03:11Z and AFL at 13:03:08Z;
- Intelligence `text_events` filed ≥ 09-22 and ingested before the open;
- Experimental `directional_alerts` created before the open (all `DRY_RUN_HELD`);
- Original Quant: 0 published (see SESSION03_FINDINGS_FIXES A4).

**Classification precedence** (first match wins):
1. `ALERTED_IT_ALREADY`: a V2 Signal trade event for the symbol.
2. `DETECTED_BY_DIFFERENT_LANE`: an Intelligence card delivered before the open.
3. `CORRECTLY_REJECTED`: the engine itself withdrew the candidate before the open (`INVALIDATED` on pre-open data), and TalonX delivered nothing.
4. `DETECTED_BUT_NOT_DELIVERED`: a TalonX lane recorded a pre-open detection that the user did not receive.
5. `NOT_DETECTED_CURRENT_SCOPE`: none of the above.

`MISSED_OPPORTUNITY_CANDIDATE` means the engine would causally have alerted (within the cap), the data existed at that time, no equivalent useful TalonX alert was given (class 4 or 5), and the outcome is measurable. **It does not mean TalonX should have traded it.**

| Classification | Within cap (25) | All candidates (141) |
|---|---|---|
| ALERTED_IT_ALREADY | 0 | 0 |
| DETECTED_BY_DIFFERENT_LANE | 0 | 0 |
| DETECTED_BUT_NOT_DELIVERED | 1: BABA. The Experimental lane recorded pre-open BEARISH `ma_death_cross` / `macd_bearish_cross` (`WOULD_REJECT`, dry-run held). | 2 (adds SKHY, from the Experimental lane) |
| NOT_DETECTED_CURRENT_SCOPE | 15 | 130 |
| CORRECTLY_REJECTED | 9 | 9 |
| DATA_NOT_AVAILABLE | 0 | 0 |
| CANNOT_DETERMINE | 0 | 0 |
| **MISSED_OPPORTUNITY_CANDIDATE** | **16** | 16 (suppressed candidates are not counted: the engine would not have sent them) |

## C3: ADC

| Source | Result |
|---|---|
| Existing TalonX | Intelligence `[INFO]` card **delivered 11:03:11Z** (3 distinct insiders bought, ~$4.14M). V2 correctly formed no new episode (Session 03 evidence). |
| New engine (causal) | Pre-market prints first visible at the 11:30Z scan (2 bars). **Gap +0.64%**; catalyst **STRONG** from 11:15Z (3 distinct open-market buyers; the 11:00:20Z Form 4 was received at 11:01:43Z, before the decision time); score **26.0**, class `SCORED`. Never WATCH or SETUP; `STALE_PREMARKET_PRICE` from 13:00Z. |
| **Classification** | **DETECTED_BY_DIFFERENT_LANE** (existing Intelligence lane only). The results are *materially different*: the pre-market engine flags price and activity dislocations, and ADC's insider news produced none. Not double-counted; not a shadow alert. |

AFL (the other Intelligence card, 13:03Z) had no pre-market prints on 09-23, so it was not data-ready and not a shadow alert.

## C4: legacy Quant signals (Session 03)

| Symbol | Time (UTC) | Signal | Published to | Subscriber | User received? | New engine |
|---|---|---|---|---|---|---|
| MSTR | 14:21:50 | rsi_oversold_volume_surge | `talonx:exp:signals:quant` (Experimental lane Quant) | 1: the Experimental lane's own consumer | **No**: `DRY_RUN_HELD` by the Experimental external-send boundary (by design) | not a pre-market candidate |
| AMD | 14:21:50 | rsi_oversold_volume_surge | same | 1 | No | not a candidate |
| AMAT | 15:18:18 | rsi_overbought_volume_surge | same | 1 | No | not a candidate |
| BLSH | 16:09:26 | macd_bullish_cross | same | 1 | No | not a candidate |

These were **detections with deliberately no delivery**, not a delivery failure. All four are regular-session signals, which the pre-market engine does not cover.
- Original Quant (→ Brain/Core) published 0 on 09-23: no detection and no delivery failure.
- On 09-22 the Experimental lane lost 13 signals to zero subscribers. That is a delivery failure inside the Experimental lane, with root cause `INSUFFICIENT_EVIDENCE` (see A4).

## C5: shadow alerts (within cap), sorted by score

`*` = **OUTCOME DATA: HINDSIGHT / EVALUATION ONLY, NOT AVAILABLE TO THE ALERT DECISION.**
- Returns are relative to the reference price (the last pre-market price at first alert).
- Returns are **direction-adjusted**: for BEARISH/GAP_DOWN, a price fall is positive.
- OPEN = first regular-session bar open; +30M/+1H = close of the bar ending at open + 30/60 min; CLOSE = last regular-session bar; MFE/MAE = session extremes.

| # | SYMBOL | ALERT TIME (UTC) | TYPE (peak) | INSIDE 39? | GAP % | PREMARKET VOLUME | CATALYST | SCORE | EXISTING TALONX RESULT | MISSED_OPP_CAND | STATUS* | OPEN* | +30M* | +1H* | CLOSE* | MFE* | MAE* |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | TLSI | 08:30 | BULLISH_SETUP | no | +16.93% | 47,698 | 8-K items 8.01,9.01 filed 2026-09-22 | 87.1 | NOT_DETECTED_CURRENT_SCOPE | yes | FAILED_CONFIRMATION | +0.26% | -9.28% | -8.23% | -13.27% | +1.13% | -14.65% |
| 2 | BABA | 08:30 | BEARISH_SETUP | no | -3.47% | 465,228 | 6-K filed 2026-09-22; 1 other SEC filing(s): SCH | 84.8 | DETECTED_BUT_NOT_DELIVERED | yes | CONFIRMED | +0.24% | +0.88% | +1.05% | +1.32% | +1.50% | -0.01% |
| 3 | SQFT | 08:30 | BULLISH_SETUP | no | +21.60% | 428,111 | 1 other SEC filing(s): 4 | 84.0 | NOT_DETECTED_CURRENT_SCOPE | yes | INVALIDATED | -13.16% | -15.13% | -11.18% | -10.53% | -5.92% | -25.00% |
| 4 | IPDN | 08:30 | BULLISH_SETUP | no | +88.46% | 2,363,083 | none found | 83.8 | NOT_DETECTED_CURRENT_SCOPE | yes | FAILED_CONFIRMATION | -5.92% | -14.83% | -13.67% | -26.94% | +4.76% | -36.02% |
| 5 | WHLR | 08:30 | BULLISH_SETUP | no | +165.24% | 4,066,351 | none found | 83.8 | NOT_DETECTED_CURRENT_SCOPE | yes | CONFIRMED | +4.94% | +53.02% | +46.17% | +10.08% | +75.61% | -4.23% |
| 6 | JAGX | 08:30 | BEARISH_SETUP | no | -25.42% | 535,156 | none found | 73.8 | NOT_DETECTED_CURRENT_SCOPE | yes | CONFIRMED | +39.96% | +38.25% | +50.97% | +64.96% | +66.93% | +24.28% |
| 7 | IONQ | 08:30 | BULLISH_SETUP | no | +12.62% | 821,114 | none found | 69.6 | NOT_DETECTED_CURRENT_SCOPE | yes | FAILED_CONFIRMATION | -0.11% | -6.67% | -6.65% | -7.26% | +0.37% | -9.26% |
| 8 | DCOY | 08:30 | BULLISH_SETUP | no | +20.95% | 467,118 | none found | 68.0 | NOT_DETECTED_CURRENT_SCOPE | yes | CONFIRMED | +17.35% | +10.15% | +1.61% | +2.15% | +25.62% | +0.01% |
| 9 | QBTS | 08:30 | BULLISH_SETUP | no | +5.35% | 198,432 | 8-K items 5.02,9.01 filed 2026-09-22; 1 other SE | 63.5 | NOT_DETECTED_CURRENT_SCOPE | yes | INVALIDATED | +2.11% | -5.57% | -5.97% | -9.08% | +2.32% | -9.49% |
| 10 | BIDU | 08:30 | WATCH | no | -2.41% | 58,695 | 6-K filed 2026-09-23; 6-K filed 2026-09-22 | 63.2 | NOT_DETECTED_CURRENT_SCOPE | yes | CONFIRMED | -0.07% | +0.81% | +0.91% | +0.54% | +1.27% | -0.24% |
| 11 | BMEA | 08:30 | BEARISH_SETUP → INVALIDATED | no | -20.00% | 27,733 | offering-related 424B5 filed 2026-09-22; 8-K ite | 59.9 | CORRECTLY_REJECTED | no | INVALIDATED | -25.00% | -13.19% | -10.34% | -5.51% | +0.73% | -26.44% |
| 12 | GRML | 08:30 | BULLISH_SETUP | no | +15.66% | 553,918 | none found | 58.8 | NOT_DETECTED_CURRENT_SCOPE | yes | FAILED_CONFIRMATION | +5.92% | -2.39% | -17.33% | -31.60% | +9.92% | -37.12% |
| 13 | PSBD | 08:30 | WATCH → INVALIDATED | no | +6.03% | 997 | 8-K items 8.01,9.01 filed 2026-09-22 | 57.7 | CORRECTLY_REJECTED | no | INVALIDATED | -6.23% | -6.50% | -6.41% | -6.32% | -4.83% | -6.86% |
| 14 | WOR | 08:30 | WATCH → INVALIDATED | no | +15.93% | 1,169 | 8-K earnings (item 2.02) filed 2026-09-22 | 56.5 | CORRECTLY_REJECTED | no | INVALIDATED | -1.78% | -11.47% | -13.35% | -12.41% | -1.16% | -16.96% |
| 15 | NNBR | 08:30 | WATCH → INVALIDATED | no | +7.44% | 5,222 | 8-K items 7.01,9.01 filed 2026-09-22 | 56.2 | CORRECTLY_REJECTED | no | CONFIRMED | +3.29% | +7.05% | +6.10% | +6.33% | +11.03% | -1.95% |
| 16 | RGTI | 08:30 | BULLISH_SETUP | no | +6.72% | 215,421 | none found | 55.5 | NOT_DETECTED_CURRENT_SCOPE | yes | INVALIDATED | -0.06% | -6.47% | -7.52% | -9.22% | +0.17% | -9.42% |
| 17 | AU | 08:30 | BEARISH_SETUP | no | -3.68% | 26,378 | 1 other SEC filing(s): SD | 55.0 | NOT_DETECTED_CURRENT_SCOPE | yes | CONFIRMED | +0.33% | +2.30% | +2.06% | +2.00% | +2.68% | +0.20% |
| 18 | RDY | 08:30 | WATCH → INVALIDATED | no | +2.39% | 10,522 | 6-K filed 2026-09-22 | 54.1 | CORRECTLY_REJECTED | no | INVALIDATED | -2.72% | -2.91% | -3.03% | -3.69% | -2.25% | -4.00% |
| 19 | SMTK | 08:30 | WATCH → INVALIDATED | no | +16.57% | 146,321 | none found | 51.7 | CORRECTLY_REJECTED | no | FAILED_CONFIRMATION | -13.20% | -11.68% | -9.64% | -12.19% | -6.65% | -25.38% |
| 20 | BB | 08:30 | WATCH → INVALIDATED | no | +2.78% | 202,356 | 8-K items 8.01,9.01 filed 2026-09-22 | 50.1 | CORRECTLY_REJECTED | no | INVALIDATED | -2.94% | -2.99% | -4.91% | -5.25% | -2.03% | -6.09% |
| 21 | AGPU | 08:30 | WATCH → INVALIDATED | no | +10.41% | 10,813 | none found | 49.2 | CORRECTLY_REJECTED | no | INVALIDATED | -9.21% | -9.90% | -12.18% | -17.33% | -7.98% | -17.40% |
| 22 | IONS | 08:30 | WATCH | no | +3.83% | 10,129 | 8-K items 7.01,8.01,9.01 filed 2026-09-23 | 47.8 | NOT_DETECTED_CURRENT_SCOPE | yes | INVALIDATED | -2.67% | -6.71% | -6.28% | -7.58% | -2.29% | -9.46% |
| 23 | CYPH | 08:30 | BULLISH_SETUP | no | +6.70% | 138,341 | 8-K items 5.02,7.01,9.01 filed 2026-09-22 | 47.3 | NOT_DETECTED_CURRENT_SCOPE | yes | INVALIDATED | -4.02% | -5.54% | -8.01% | -8.67% | +0.00% | -12.31% |
| 24 | DOMO | 08:30 | WATCH → INVALIDATED | no | +4.05% | 1,200 | 8-K items 1.02,2.01,5.03,7.01,8.01,9.01 filed 20 | 46.1 | CORRECTLY_REJECTED | no | INVALIDATED | -4.67% | -8.70% | -7.53% | -7.27% | -4.67% | -10.34% |
| 25 | FLNA | 08:30 | WATCH | no | -8.25% | 64,805 | 8-K items 7.01,8.01,9.01 filed 2026-09-22 | 45.6 | NOT_DETECTED_CURRENT_SCOPE | yes | CONFIRMED | -5.82% | +12.31% | +9.21% | +5.07% | +15.19% | -5.82% |

**Outcome status (within cap, hindsight):** CONFIRMED 8 · FAILED_CONFIRMATION 5 · INVALIDATED (gap filled in the first 30 min) 12.

This is **one day and 25 alerts, mostly micro-caps**. It is descriptive and supports **no profitability claim**, and the classes are not predictions. Several names are extremely volatile, thin micro-caps (for example WHLR +165% gap, IPDN +88%, JAGX −25%). The engine surfaces them because they are the day's largest dislocations. Whether such names belong in a research feed is an operator decision for a future pre-registered config, not a tuning step taken from this replay.

## Verdict

The engine ran causally end-to-end on a real session, with a broad universe and a non-zero, explainable funnel:
- **data-ready 3,151** at the last pre-open scan;
- **84 alert-worthy** at the last scan;
- **141 candidates** over the session;
- **25 would-be alerts**, 16 of them missed-opportunity candidates that no existing TalonX lane delivered.

The findings are R1 (cap exhausted at the first scan; bounded, not tuned) and SEC request volume (595 requests over the day, within fair-access limits).
