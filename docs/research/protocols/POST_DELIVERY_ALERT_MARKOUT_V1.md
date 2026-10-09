# POST_DELIVERY_ALERT_MARKOUT_V1: protocol revision 2 (exact targets)

**Status: `IMPLEMENTED_INACTIVE`, awaiting owner activation approval.** Protocol fingerprint: `c812a3e65e4018a5`
(`talonx_paperperf.post_delivery_markout.PDM_V1`).

**Output name.** *Post-delivery price markout under stated cost assumptions*. It is descriptive. It is **not**
executable profit, a paper-trading portfolio or a strategy profitability verdict.

**Separation.** It is separate from the promotion `paper_outcomes` (data-time markouts, unchanged), VR_PAPER_V1, the
V2 forward tracker and every frozen study.

**Pre-outcome commitment.** Every value here was fixed before any post-delivery price of any real alert was read. No
historical alert has been paired with later prices.

## 1. Population and selection

**Delivery records.** Outbox rows with `event_type = RESEARCH_OPPORTUNITY`, destination `TRADE_EVENT`, and the joined
promotion `RESEARCH_REVIEW_ALERT`. They must be created at or after the activation boundary and belong to one of the
**20 fixed study sessions**. State `SENT` or `AMBIGUOUS` = *may have reached Telegram*. `FAILED`, `EXPIRED` and
`PENDING` never did; they are not deliveries.

**Delivery classification** happens before selection and is conservative. An uncertain send is never "definitely
delivered". A record is `AMBIGUOUS_DELIVERY` when any of these holds:
- outbox state `AMBIGUOUS`;
- worker `attempts > 1`;
- a non-null `last_error`;
- under trace policy `REQUIRED`, no delivery trace;
- a trace showing hidden client-level network retries (a timed-out request may have delivered), or more than one
  accepted trace.

A clean record must also pass the **clock checks** (§3); otherwise `CLOCK_UNVERIFIED`.

**Selection.** One observation per (trading session, symbol). Among *all* delivery records for that pair, take the
earliest by anchor, with ties broken by `event_id`, **before any price data is read**.
- If that record is ambiguous or clock-unverified, the pair is excluded with that state.
- Later records are `REPEAT_SAME_SESSION`.
- A selected record is **never** replaced by a later alert because its bars or quotes are missing.

The population is long-only (BULLISH review setups). Records before activation, legacy `PAPER_OPPORTUNITY` rows and
sessions outside the fixed 20 are never observations. There is no backfill.

## 2. Exact timing (1-minute SIP bars; bar `t` = interval start; a bar covers `[t, t+60 s)`)

| Quantity | Definition |
|---|---|
| Anchor `D` | **API-acceptance acknowledgement time**: the local, timezone-aware `outbox.sent_at_utc`, written after a successful Telegram API response (provenance stored per record). Not device receipt, not user reading |
| Reaction delay `R` | 300 s |
| Entry target `E` | `ceil_to_minute(D + R)` in UTC; kept unchanged if already on a minute boundary |
| Entry reference | raw **open** of the positive-volume bar whose interval is exactly `[E, E + 1 min)` |
| Exit target `X` | `E + 30 min` |
| Exit reference | raw **close** of the positive-volume bar whose interval is exactly `[X − 1 min, X)` |
| Session rule | `E` and `X` inside the **same** XNYS regular session (`trading_window`: half days, holidays, DST). `X = close` is allowed. Otherwise `SESSION_INELIGIBLE`: never shifted to another day, never shortened |

**No search.** There is no "first available" entry and no "last available" exit. A target bar that is absent,
zero-volume, has invalid prices, or is duplicated is `MISSING_ENTRY_BAR` / `MISSING_EXIT_BAR`. It is never replaced by
a neighbouring bar and never counted as a zero return.

## 3. Clock and delivery traceability

**Machine clock** (observed 2026-10-09, read-only `w32tm /query /status`): synchronised by NTP to `time.windows.com`,
stratum 5, root dispersion ≈ 0.28 s, last sync 06:25:30 local. The clock was not changed.

**Delivery trace** (`talonx_paperperf/delivery_trace.py`, **not wired**):
- `TracedTransport` wraps the existing client for the **unchanged** `worker.drain(client=…)`. It records `send_start`,
  `response` (local), the Telegram `message_id` and server `date`, a chat **hash**, and hidden-retry counts taken from
  the client's own retry warnings.
- It changes no routing, retry policy or deduplication.
- Wiring is a declared promotion deployment (owner decision).

**Checks when a trace exists:**
- `send_start ≤ response`;
- `outbox.sent_at_utc ≥ response − 2 s`;
- `server_date − 2 s ≤ response ≤ server_date + 1 s + 2 s` (Telegram's date has 1-second resolution).

Any failure → `CLOCK_UNVERIFIED`, excluded and visible. The server date is kept for audit. The anchor is **not**
switched to it, and server acceptance is not user reading.

**Without a trace,** hidden client retries cannot be excluded:
- `delivery_trace_policy = REQUIRED` → all untraced sends are `AMBIGUOUS` (recommended).
- `NOT_AVAILABLE_ACCEPTED` → the owner accepts this residual risk explicitly.

## 4. Costs (proposed for owner approval; not chosen from any outcome)

**Quote selection.** At `E` and at `X`: the **latest valid SIP NBBO quote** with `target − 60 s ≤ t ≤ target`.
- Never after the target. Comparison uses exact nanoseconds; provider times have 9 fractional digits.
- Valid means finite `bid, ask > 0` and `ask ≥ bid`. A locked quote (`ask = bid`) is valid with zero spread and is
  flagged. A crossed quote is skipped, and the next older valid quote is used.
- Equal timestamps: the widest valid spread (conservative), then the highest ask.

**Formulas.**
```
m_E = (ask_E + bid_E)/2         m_X = (ask_X + bid_X)/2
spread_cost            = (ask_E − bid_E)/(2·m_E) + (ask_X − bid_X)/(2·m_X)
assumed_additional_cost = 0.0005      (5 bps TOTAL round trip, subtracted once)
gross_markout          = exit_bar_close / entry_bar_open − 1
cost_adjusted_markout  = gross_markout − spread_cost − 0.0005
```

**Caveats.**
- Quote midpoints and bar prices need not coincide. This is an *approximate* cost adjustment to a bar-based markout.
- The additional 5 bps is an **unsupported modelling assumption**, not measured slippage.
- Quote presence does not prove liquidity for any order size. Market impact and actual execution are unmeasured.
- Borrow is irrelevant (long only).

**Missing quotes.**
- No valid quote within 60 s → `QUOTE_UNAVAILABLE`.
- Quotes never obtained before the deadline → `QUOTE_ACQUISITION_FAILED`.

Either way the cost-adjusted value is unavailable. **The gross observation is kept** and no zero cost is implied. Gross
and cost-adjusted sample sizes are reported separately.

## 5. Acquisition (`talonx_paperperf/post_delivery_acquisition.py`)

**Requests per selected observation (exact scope).**
- Bars: `/v2/stocks/bars`, SIP, 1Min, `adjustment=raw`, `start = bar start`, `end = start + 59 s` (Alpaca's end is
  inclusive), once for the entry bar and once for the exit bar.
- Quotes: `/v2/stocks/quotes`, SIP, `sort=desc`, `[target − 60 s, target]`, at `E` and at `X`.
- Each part is fetched once. Only missing parts are retried.

**Eligibility.**
- Not before the session close + 60 min.
- Never inside **R5** (weekdays 09:00–16:30 America/New_York, DST-aware). On half days, close + 60 min is 14:00 ET, so
  acquisition waits until 16:30 ET.
- Only selected, non-terminal observations of the activated population.

**Bounds.**
- ≤ 40 requests/min (shared production quota).
- 2 retries for 429, 5xx and transport errors.
- ≤ 5 quote pages; stop once every quote at the latest valid time is in hand.
- A per-run time budget.
- Default TLS verification.

**Typed outcomes.** `RETRIEVED` (an empty list = confirmed absence), `TRANSPORT_FAILURE`, `RATE_LIMITED`,
`ENTITLEMENT_DENIED`, `REQUEST_REJECTED`, `MALFORMED_RESPONSE`, `PAGINATION_BOUND_EXCEEDED`, `BUDGET_EXHAUSTED`,
`R5_REFUSED`.
- A failure is never an empty success.
- Errors go to `acquisition_errors`, separate from confirmed absence of target data.
- Raw payloads are stored with request scope, retrieval time, provider and SHA-256.

**Live verification** (2026-10-09 09:35Z, outside R5; one capability probe on **SPY**, a past minute that is not a
study observation; outcomes only, no prices recorded):
- Raw 1-minute SIP bar: `RETRIEVED`, exactly 1 bar.
- SIP quotes with `sort=desc`: `RETRIEVED`, 50 quotes on page 1, timestamps confirmed **descending**, nanosecond
  precision.

Historical bar and quote entitlement is therefore **live-verified** for that probe. Orchestration is fixture-tested
only.

## 6. Finite waiting and endpoint

**Deadline per session** = close of the **second subsequent** XNYS trading session + 60 min (calendar-defined: half
days, holidays, DST).

**Every invocation reconciles deadlines first,** before any request. Anything still waiting at or after its
**original** deadline becomes terminal: `EXPIRED_NO_DATA`, or `MEASURED` with `QUOTE_ACQUISITION_FAILED` if only quotes
were missing. Attempts and partial inputs are kept.
- Terminal observations are never reopened.
- Downtime never extends a deadline. A stopped worker cannot write, so expiry is applied on the next invocation using
  the original deadline.

**Fixed calendar.**
- **Activation:** a future full trading session, approved before that session's window opens (00:00Z of its date).
- **Period:** exactly **20 trading sessions** from that first session; not 20 sessions with alerts, and never extended.
- **Endpoint:** the deadline of the 20th session.
- Policy or universe changes start a new **segment** without resetting the clock.
- A day where collection fails is recorded (`health()`) and never replaced.

## 7. Reporting

**`health()` (operational, any time).**
- delivery counts by class;
- observation states (selected, pending, measured, missing by reason, expired);
- per-session states;
- acquisition errors by class;
- sessions where every selected observation expired.

It shows **no return values**.

**`final_report()` (refused before the endpoint), per segment.**
- counts by state;
- selected / gross-measured / cost-adjusted-measured, with coverage = measured ÷ selected (missing stays in the
  denominator, never as a zero);
- gross and cost-adjusted mean, median, positive fraction, p05, p10 and worst 5;
- concentration by session and symbol.

It is labelled **alert-level, not portfolio**. There is no PASS threshold. Alerts within a session share market moves,
so the effective sample is closer to 20 sessions than to the alert count. Any interval resamples whole sessions and is
labelled low-power.

## 8. Superseded proposal (revision 1, commit `3e11919`, never activated, no outcomes)

Revision 1 differed in three ways:
- **Entry:** the first traded bar within 5 minutes after `T_e`.
- **Exit:** the last traded bar in a 5-minute window before `T_x`.
- **Cost:** the entry quoted spread + 5 bps.

Revision 2 replaces these with exact target bars and the explicit two-sided half-spread formula above. Revision 1 is
kept here for the record; no historical report was rewritten.

## 9. Proposed activation

- **First session:** Monday **2026-10-19**.
- **Sessions:** 2026-10-19 … **2026-11-13** (20 sessions, spanning the 2026-11-01 DST change).
- **Endpoint:** **2026-11-17 22:00Z**.

**Prerequisites** (see `ACTIVATION_PREFLIGHT.md`):
1. owner approval of the formulas and values;
2. the decision on the delivery trace (wire it, or accept `NOT_AVAILABLE_ACCEPTED`);
3. a scheduled post-session invocation outside R5, which is not created by this package.
