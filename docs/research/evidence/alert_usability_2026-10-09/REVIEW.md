# Telegram research-alert usability review (2026-10-09): proposed template, not deployed

**Scope.** This review covers presentation only. Alert generation, scores, thresholds, ranking, rate limits, delivery,
the 600-stock universe and all study locks are unchanged. Nothing was sent, resent or suppressed.

**What was read.** Rendered alert text, delivery and trace timestamps, and the generation-time `candidate_events` row
behind each promotion.

**Not read:**
- subsequent prices, returns, `paper_outcomes`, or the mutable `candidates.last_*` columns;
- blinded or protected research.

## Sample

| Item | Value |
|---|---|
| Rule | `RESEARCH_OPPORTUNITY` outbox rows in state `SENT` with `sent_at_utc` ≤ **2026-10-09 16:15:00Z**. The window must be ≥ 2026-10-09, when universe policy **DTU_V3_TOP600** took effect (`control/dtu_policy_schedule.json`). Ordered by `sent_at_utc` descending, then `event_id`; first 20. |
| Size | **20 alerts, 20 distinct symbols.** All are `ACTIVE_CORE` members of the 2026-10-09 universe. |
| Session | Window 2026-10-09 only. Acknowledged 14:32:47–16:10:31Z, so this is a **partial session** (close 20:00Z). |
| Repeats | OKTA, GME and PBR were also alerted on 2026-10-08, in a separate window. There were no repeats within the window. |
| Reproduce | `review_sample.py` → `sample.json` (sanitised: short hash refs, no chat or message IDs), then `render_proposed.py` → `rendered_examples.md`. |

**Uniform across the sample:**
- family `GAP_UP`, event `UPGRADE` from `WATCH` to `BULLISH_SETUP`;
- phase `REGULAR`;
- horizons `INTRADAY / SAME_DAY`;
- policy `OPPORTUNITY_PROMOTION_V1`.

## What each field actually means (traced to code)

| Field in today's message | Actual meaning | Source |
|---|---|---|
| "BULLISH setup" | Price ≥ 3% above the prior close, rule score ≥ 60, and ≥ $500k window-to-date dollar volume. This is a **measured upward move**, not a forecast. In this sample the move was 3.00–4.72% (10 of 20 below 3.10%, just over the threshold); 17 were above the prior-day high, 3 inside the prior range. | `talonx_premarket/scoring.classify`, `config` |
| "⭐ Score 61.0" | A **0–100 rule-points sum**: move vs 20-day ATR (30), volume vs ADV20 (25), dollar liquidity (15), SEC/insider filings (15), price structure (10), bar coverage (5). 60 is the setup threshold; the sample range is 60.42–93.74. It is **not** a probability or confidence. | `scoring.score`, `ScoreWeights` |
| "💵 Ref $X" | The **close of the last 1-minute bar** on the SIP feed, which is subject to a 15-minute provider delay. It is not a live quote. | `features.last_price`, `provenance.delay_minutes` |
| "🕒 Signal HH:MMZ … data HH:MMZ (age Nm)" | "Signal" is the **render time**, when the row leaves the delivery queue. It is **not** the detection time. The age is render time minus data as-of: 16–29 minutes in this sample, median 17. | `promotion.render_review`, called at outbox creation |
| (not shown) detection time | `candidate_event` time. For 6 of 20 alerts the message was written 67–767 s after detection, because of the existing 3-per-5-minute queue. Example: CF was detected at 10:20 ET and written at 10:32 ET. | `promotions.event_utc` vs `outbox.created_at_utc` |
| "⏱ Horizon INTRADAY / SAME_DAY" | Both labels come from the alert's phase: a REGULAR-phase alert always gets both. They name evaluator scopes that record no action. Neither defines an exit or holding period, and both end at **today's 16:00 ET close**. | `discovery._horizons`, `evaluators.PHASE_SCOPE`, `notifier.signal_open` |
| (not shown) catalyst | Only SEC filings since the prior session and 30-day insider open-market (code P) purchases were checked. **News was not checked.** Results: 17 "none found", 2 Form 144 (scored +9 as an "other filing"), 1 6-K (+15). | `discovery._catalyst`, `catalysts.evaluate` |
| (not shown) why flagged | Recorded per alert in `score_json.why`. Note that it says "**pre-market** volume", although the figure is window-to-date volume since 04:00 ET, including the regular session. The Lab notifier already calls it "Session-to-date". | `aggregates`, `ingestion` (bounds start 04:00 ET) |
| "📉 Research verdict: NEGATIVE…" | This is correct and correctly scoped to this policy. It is line 9 of 12, below the 🟢/⭐/💵 lines. | `REVIEW_VERDICT`; record `docs/research/evidence/2026-10-07_review_alert_restoration.md` |
| Telegram acknowledgement time | Known only **after** sending, so it can never appear in the message itself. It is shown below only as audit annotation. | outbox `sent_at_utc`, trace `response_utc` |

**Classification of the gaps:**
1. **Available but poorly displayed:**
   - reason flagged;
   - catalyst result and scope;
   - the score's meaning and threshold;
   - that the reference price is a delayed 1-minute close;
   - detection vs render time;
   - horizon meaning;
   - repeat history;
   - universe policy.
2. **Not collected:**
   - news or press-release catalysts;
   - a live quote at render or send time;
   - a structured "what changed" comparison against a previous-day alert. Only the earlier alert's existence and date are cheaply available.
3. **Claims the system cannot support:**
   - the score as probability or confidence;
   - BULLISH as a forecast;
   - any causal explanation of the move;
   - "pre-market" for window-to-date volume;
   - a Form 144, which is a notice of a *proposed insider sale*, read as bullish evidence. It only earns generic "other filing" points.

## Top findings (at most five)

| Issue | Example from sample | User impact | Available evidence | Proposed presentation fix |
|---|---|---|---|---|
| 1. A delayed price looks actionable | CF: "💵 Ref $117.00 … data 14:03Z (age 29m)". Data age at acknowledgement was 16.2–29.8 minutes. | "Ref" reads like a current entry price, but it is a 15-minute-delayed, 16–30-minute-old bar close. | `last_price`, `last_bar_utc`, `delay_minutes`, `data_as_of` | "Price $117.00 = last 1-min bar close at 10:03 ET, 15-min delayed feed. Not a live quote." Also state the data age when written, with detection and written times. |
| 2. The score is the only "why", shown as a star rating | APO: "⭐ Score 74.2". No reason or catalyst appears anywhere in the message. | The user cannot tell what was observed, and may read 74.2 as 74% likely. | `score_json` parts and `why`, threshold 60, catalyst label and scope | A "Why flagged" block: move vs prior close and ATR, volume since 04:00 ET vs ADV20, price vs prior-day range, catalyst with "news not checked". Then "Rule score 74.2/100 (alert threshold 60) … Not a probability." |
| 3. Two horizon labels with no meaning given | Every alert: "⏱ Horizon INTRADAY / SAME_DAY" | The two labels suggest two different holding periods, but no exit is defined. | `_horizons` (phase-derived); SAME_DAY open until the window close | "Horizon: today's session only, to the 16:00 ET close (INTRADAY and SAME_DAY both end then). No exit or holding period is defined." |
| 4. Repeats are not identified | PBR, OKTA and GME were alerted on 2026-10-08 and again on 2026-10-09 with identical framing. | The user cannot tell a new setup from an update, or what changed. | Earlier `PROMOTED_SIGNAL` review alerts for the symbol (count and window) | "Repeat: also alerted 2026-10-08 (earlier session). Today is a new move vs today's prior close, not an update of that alert", or "first research alert … since review alerts began". |
| 5. Negative research evidence sits below promotional formatting | The 🟢 "BULLISH setup", ⭐ score and 💵 ref lines come first; "📉 Research verdict: NEGATIVE…" is line 9. | The disclosure that matters most is read last, if at all. | `REVIEW_VERDICT` text and source record | Lead with "RESEARCH OPPORTUNITY — UNVALIDATED / For review only · no order placed". Drop 🟢 and ⭐. Keep the NEGATIVE line, with figures, as a ⚠️ block that also names what is unverified. |

## The proposed template (plain text, `parse_mode=None`; values from generation-time records only)

```
🔎 RESEARCH OPPORTUNITY — UNVALIDATED
For review only · no order placed · not a buy instruction

{SYMBOL} — up {|move|:.2f}% vs prior close {prev_close}
Setup: upward move, rule label BULLISH (describes the move, not a forecast); {event reason}

Why flagged (data as of {data_as_of ET} ET):
• Move {move:+.2f}% vs prior close = {move/ATR20:.1f}× its 20-day average range
• Volume since 04:00 ET {window volume} sh = {fraction of ADV20:.1f}% of 20-day average
• Price {above prior-day high {prev_high} by d% | still inside prior-day range (high {prev_high})}
• Catalyst: {none in SEC filings (since prior session) or insider purchases (30d) | <filing label> (SEC record; link to this move not assessed) | UNKNOWN: <lookup incomplete>}; news not checked

Price {ref} = last 1-min bar close at {last bar end ET} ET, {delay}-min delayed feed. Not a live quote.
Data age when written: {written − data_as_of} min (detected {event ET} ET, written {render ET} ET)
Horizon: today's session only, to the 16:00 ET close (INTRADAY and SAME_DAY both end then). No exit or holding period is defined.
Rule score {score:.1f}/100 (alert threshold 60): points for move, volume, liquidity, filings, price position and data coverage. Not a probability.
Repeat: {first research alert for SYMBOL since review alerts began (2026-10-07) | also alerted {date} (earlier session). Today is a new move vs today's prior close, not an update of that alert}

⚠️ Research to date: this alert policy's paper results were NEGATIVE after costs (replay −0.61%, forward −0.46%). Unverified: cause of the move, news, live price.
Policy OPPORTUNITY_PROMOTION_V1 · universe DTU_V3_TOP600 · ref {short hash}
```

**Design rules:**
- No targets, stops, expected returns, urgency, buy wording or manipulation claims.
- Every field exists at render time. Any field missing from the record renders as `UNKNOWN`.
- The Telegram acknowledgement belongs only to audit annotations.
- The NEGATIVE verdict keeps its figures; its source record is cited above.

## Side-by-side examples (local render; nothing sent)

These four cover a typical alert (APO), a stale-data or queue-delayed alert with the price inside the prior range
(CF), a repeat with a filing catalyst (PBR), and a Form 144 "catalyst" with the price inside the range (PANW). See
[`rendered_examples.md`](rendered_examples.md) for the side-by-side tables and audit annotations, generated from
`sample.json`.

- **Typical (APO):** move +3.00%, price above the prior high by 2.34%, catalyst none found. Data age 17 minutes.
- **Old data / queue delay (CF):** data as of 10:03 ET, detected 10:20, written 10:32, data age 29 minutes. Audit: queued→acknowledged 725.3 s.
- **Repeat + catalyst (PBR):** also alerted 2026-10-08; 6-K filed 2026-10-08, scored as a strong catalyst. This is a new move, not an update.
- **Missing or limited information (PANW):** the catalyst is "1 other SEC filing(s): 144". Its link to the move is not assessed, news was not checked, and the price was inside the prior-day range.

## What presentation alone can fix

All five findings can be fixed in presentation alone, using fields already recorded at render time:
- reason flagged and score meaning;
- catalyst status and scope;
- price definition and data age;
- detection vs written time;
- horizon meaning;
- repeat identification;
- the ordering and wording of the negative evidence;
- the label correction ("volume since 04:00 ET" instead of "pre-market").

**Genuinely missing (not a new project; stated only so the template never implies it):**
- news or press-release coverage;
- a live quote at render or send time;
- a field-by-field comparison with a previous-day alert.

The template marks these as unverified or not checked.

**Deployment** would be a separate, declared presentation change to `promotion.render_review` only.
