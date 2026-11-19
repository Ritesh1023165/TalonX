# Telegram alert volume forensics + noise reduction — 2026-09-28

Branch `feature/continuous-opportunity-engine`, start `6cfde8f`. Paper only; no strategy, scoring, discovery,
lifecycle, promotion-eligibility or universe change. Not deployed (live session running; see §9).
Evidence: `2026-09-28_telegram_noise/` — `forensics_2026-09-28.json`, `replay_2026-09-28.json`, `tools/`.

## 1. Counts reconciled from durable outboxes (window 2026-09-28)

| Bot | Source | Sent | Retries | Duplicates | Queued/expired/failed |
|---|---|---|---|---|---|
| Signal | `promotion_signal_notifications.db` (TRADE_EVENT) | **154** | 0 | 0 | 0 |
| Lab | `opportunity_research_notifications.db` (RESEARCH) | **314** at 21:55Z (315 by 22:30Z) | 0 | 0 | 0 |
| Sentinel | `v2_release_rc1_notifications.db` + `sentinel_replies.jsonl` | **2** (1 STARTUP, 1 command reply) | 0 | 0 | 0 |

No other sender to these bots today: legacy `run_talonx` pushes 0, V2 `v2_alert_outbox` 0.

Lab by kind: MATERIAL_UPDATE of a setup 147 (91 bullish, 56 bearish), INVALIDATED 73, UPGRADE to a setup 54,
NEW setup 18 (7 bullish, 11 bearish), NEW WATCH 15, WATCH MATERIAL_UPDATE 7. By phase: PREMARKET 159, REGULAR 135,
AFTER_HOURS 20. 117 symbols, 2.7 messages per symbol; 17 symbols received 5 or more messages (MEDS 16, ONCO 15, NAMI 15,
INLF 12, MSGY 11).

Signal: 154 messages, 154 symbols, 1 message per symbol.

**Unread badges.** Today's durable sends (Signal 154, Lab 314) are larger than the visible unread counts (112 and 133).
The badges are therefore consistent with today's traffic, some of it already read. Older unread messages cannot be
excluded (Friday's Lab traffic was 294), but today's traffic alone accounts for the badges.

## 2. Signal forensics (read-only; eligibility unchanged)

- **Classification.** All 154 are NEW_PAPER_OPPORTUNITY. There were 0 duplicates, 0 retries and 0 lifecycle updates.
  No candidate or symbol was promoted twice, and every candidate was first seen today (no re-entry across windows).
- **Queue.** 207 events were eligible. Of these, 154 were promoted, 28 were rejected while queued as STALE, and 25
  expired after 30 minutes in the queue.
- **Rejected at evaluation.** 2,342 WATCH, 767 BEARISH and 37 wrong-phase events were rejected.
- **Rate limiter.** At most 3 sends in any rolling 5 minutes (at the cap). There were 0 score-order inversions: no
  item was released while a higher-scored item was waiting.
- **Latency.**
  - Queue wait: median 1.5 min, p90 9.0 min, max 13.6 min.
  - Event to send: median 3.4 min, p90 10.2 min.
  - Data time to send: median 19.6 min, including the 15-minute SIP delay.
- **Score bands.**

  | Score | Sent |
  |---|---|
  | <65 | 49 |
  | 65–70 | 32 |
  | 70–75 | 34 |
  | 75–80 | 23 |
  | 80–85 | 13 |
  | 85+ | 3 |

  **32% of Signals scored below 65.**
- **Price bands.**

  | Price | Sent |
  |---|---|
  | $1–5 | 27 |
  | $5–20 | 52 |
  | $20–100 | 59 |
  | $100+ | 16 |

- **Other splits.** Every Signal had horizon INTRADAY/SAME_DAY and REGULAR data. By hour (UTC):

  | 13h | 14h | 15h | 16h | 17h | 18h | 19h | 20h |
  |---|---|---|---|---|---|---|---|
  | 6 | 33 | 23 | 30 | 26 | 12 | 21 | 3 |

- **Paper outcomes (descriptive only).** Outcomes are not monotonic in score. For example, mean 30-minute return is
  −0.09% for <65, −0.89% for 65–70, +0.30% for 75–80 and −0.09% for 80–85. The samples are small, and **this makes
  no claim of edge.**

**Conclusion:** the Signal volume comes from the policy itself (3 per 5 minutes, all day, with no score floor). It
does not come from duplicates, retries or replays.

## 3. Lab noise forensics

Every message sent today, classified under the new policy:

- **HIGH — 142:**
  - 18 new setups;
  - 54 upgrades to a setup;
  - 70 invalidations of setups already sent to Lab.
- **MEDIUM — 38:** setup updates where the move extended beyond the last value shown to the reader.
- **LOW — 135:**
  - 110 setup updates that faded or re-tested without a new extreme — the oscillation churn behind MEDS, ONCO and
    NAMI;
  - 15 new WATCH;
  - 7 WATCH updates;
  - 3 invalidations of candidates never sent as a setup.

Today's traffic also contained a HIGH case the old policy never sent. **62** invalidations belonged to candidates
promoted to Signal but never surfaced in Lab:
- **23** happened while the Signal's SAME_DAY horizon was still open;
- **39** were Friday promotions invalidated on Monday, after their horizon had closed.

## 4. What changed (Telegram only; every event is still persisted)

**Lab delivery policy (`LAB_DELIVERY_POLICY_V1`)** lives in `talonx_opportunity/lab_delivery.py` and is applied in
`notifier.py`. It runs *after* the unchanged `LAB_NOTIFY_POLICY_V1_REGULAR_EXT_20260925` decision. The decision,
`counted_new`, budget JSON, AFTER_HOURS reserve and `surfaced` table are byte-identical (tested; see also the §6
replay). Each decided event additionally gets `lab_route`, `info_class`, `route_reason`, `gap_pct` and `digest_id`
(additive columns).

| Event | Route |
|---|---|
| NEW or UPGRADE to BULLISH/BEARISH | IMMEDIATE (HIGH) |
| INVALIDATED of a setup already sent to Lab | IMMEDIATE (HIGH) |
| INVALIDATED of a Signal-promoted candidate before its window's regular close (also when V1 said NOT_SURFACED_PARENT) | IMMEDIATE (HIGH) |
| MATERIAL_UPDATE of a sent setup where \|gap\| is greater than the last \|gap\| shown for it | IMMEDIATE (MEDIUM) |
| Setup update not beyond the last shown value; new WATCH; WATCH update; invalidation never sent as a setup | DIGEST (LOW) |
| Every other V1 decision (budget-held, NOT_SURFACED_PARENT, bookkeeping) | not delivered (unchanged) |

**Digest.**
- Built at 30-minute UTC boundaries, once 5 or more held events are pending or the oldest has waited 2 hours.
- It lists counts per reason, active setups, the setups sent individually in the period, and whether any Signal
  candidate was affected.
- It contains no symbol list. Details stay in `notification.db` (`decisions.digest_id`, `digests`).

**Formats.**
- Signal (`promotion.render`, presentation only): `🚨 TALONX SIGNAL — PAPER`, followed by symbol·direction, score,
  reference, phase·data time and horizons. A one-line footer reads "paper · no order · not proven profitable".
- Lab: `🧪 TALONX LAB — NEW SETUP / SETUP UPGRADE / SETUP UPDATE / SETUP INVALIDATED / DIGEST`, with one compact
  footer.
- Sentinel is unchanged: `🛰 TalonX Sentinel`. The three bots stay visually distinct: Signal 🚨, Lab 🧪, Sentinel 🛰.

**Rollback.** Restart the notifier with `TALONX_LAB_DELIVERY=LEGACY`. That restores the exact previous delivery path
and config-fingerprint set.

## 5. Duplicate / replay safety

- **Immediate messages.** An immediate message uses the event id as its outbox id (as before). Re-processing after a
  restart is skipped by the existing decided-event guard, and outbox enqueue is idempotent.
- **Digest write order.** The digest row and the links from its decisions are written in one transaction. The digest
  is then enqueued under a deterministic id, `LAB_DIGEST:<bucket end>`. So a decision belongs to at most one digest,
  and a crash between recording and enqueueing still produces exactly one enqueue (tested).
- **Suppressed events** are never replayed later as individual messages. Routing is decided once, when the event is
  first decided.
- **No double counting.** An IMMEDIATE event never carries a `digest_id` (tested).
- **Signal** is unaffected: its dedup is by promotion id, as before.
- **Destinations.** Lab code never references TRADE_EVENT. In the replay, every Lab outbox row went to RESEARCH.

## 6. Offline replay of 2026-09-28 (nothing sent)

`tools/replay_lab_delivery.py` works on snapshots of the live DBs. It replays events minute by minute, at the minutes
the live notifier decided them.

| Check | Result |
|---|---|
| LEGACY replay reproduces the live decisions (event_id, decision, counted_new) | **true** (315 = 315) |
| V1 decisions identical to live | **true** |
| CURRENT_LAB_MESSAGES | 315 |
| NEW_IMMEDIATE_LAB_MESSAGES | 203 (includes 23 open-Signal invalidations never sent before) |
| NEW_DIGEST_MESSAGES | 18 |
| SUPPRESSED_LOW_INFO_MESSAGES (held for the digest, still persisted) | 135 |
| **LAB_MESSAGE_REDUCTION_PERCENT** | **29.8%** (315 → 221) |
| High-information capture (spec definition, computed independently of the router) | 165/165 **PASS** |
| CURRENT vs NEW Signal messages | 154 / 154 **PASS** |

**How the Signal check works.** Comparing the AST of `promotion.py` with `6cfde8f` shows only `render`, `_ref` and
`SIGNAL_FOOTER` changed. `PROMOTION_POLICY` fingerprint `4926c12e5eace04e` is unchanged, and all 154 promotions
re-render.

**Why the reduction is capped near 30%.** The remaining volume is dominated by events the specification itself
classes as HIGH: 70 invalidations of setups already sent, plus 72 new or upgraded setups. Cutting Lab further would
need a change to the Lab *budget* or lifecycle, which is out of scope here.

## 7. Future Signal-volume options (READ-ONLY estimates; nothing implemented)

The queue was replayed at 30-second ticks using the real invalidation times. The simulated current policy gives 164
against 154 actual, so treat every row as ±7%. Outcome metrics exist only for items the real run promoted. They are
descriptive, the samples are small, and they make no claim of edge.

| Policy | Sent | Unique | ≥80 captured | Missed ≥80 | Confirmed @30m | Mean 30m | Mean close |
|---|---|---|---|---|---|---|---|
| Current, simulated | 164 | 164 | 16/16 | 0 | 43% | −0.15% | +0.02% |
| Score ≥70 | 73 | 73 | 16/16 | 0 | 47% | +0.10% | +0.17% |
| Score ≥75 | 39 | 39 | 16/16 | 0 | 42% | +0.20% | +0.14% |
| Top-1 per 5 min | 78 | 78 | 16/16 | 0 | 41% | +0.04% | −0.10% |
| Top-2 per 15 min | 52 | 52 | 16/16 | 0 | 36% | −0.01% | −0.25% |
| Price ≥$5 and session $ ≥$5M | 71 | 71 | 10/16 | 6 | 39% | −0.07% | −0.03% |
| One per symbol per day | 164 | 164 | 16/16 | 0 | 43% | −0.15% | +0.02% |
| Score ≥70 and tradability | 38 | 38 | 10/16 | 6 | 45% | −0.08% | −0.09% |

**Reading.**
- A score floor (≥70) or a top-1-per-5-minute cap halves the volume and keeps every ≥80 candidate.
- The tradability gate as sketched would lose 6 of 16 ≥80 names. The high scorers include illiquid names, so that
  gate needs its own design, together with the Dynamic Tradable Universe.
- "One per symbol" does nothing today: there were no repeats.
- No option shows an outcome difference that can be distinguished from noise at n = 39–164.

## 8. Tests

- **New:** `tests/test_telegram_noise_reduction.py`, 22 tests, all passing. They cover:
  - new bullish/bearish setups, and a WATCH→setup upgrade, sent immediately;
  - WATCH updates and never-sent invalidations held for the digest;
  - invalidation of a sent setup, and of an open-Signal candidate, sent immediately; a Signal candidate after its
    horizon closed is not;
  - updates sent only when the move extends;
  - V1 decisions identical with and without the new policy;
  - digest aggregation, the minimum/hold rule, no resend after restart, crash-then-enqueue exactly once, and no event
    both immediate and digested;
  - no replay of immediate messages after restart; the legacy switch;
  - Signal policy unchanged; Signal and Lab format contracts; no cross-channel source;
  - hash coverage via AST imports; the promotion boundary rule.
- **Updated (assertion form only):**
  - `test_opportunity_promotion.py`, for the new Signal header;
  - `test_p0_ah_reserve_data_phase.py`, which now compares by column name instead of position.
- **Targeted regression:** 22 notify/engine/SEC/operator suites — 500 passed. The only failures were the 2 task114
  tests (ConcurrentStartError while the live stack runs) and `test_ri3_operator` (a Windows subprocess environment
  issue). Both fail identically on the baseline.
- **Full suite, run file by file with a 120 s cap per file:** 5,615 passed, 6 skipped, **43 failed**.
  - All 43 failures fail identically with this change stashed (baseline). They are in task100a/102/104/111/112/114/117/
    118a/131, `telegram_listener` and `ri3`.
  - 4 files hit the 120 s cap (backtest cost/sample data, package5 causality, task73s control fixture). They are known
    long-running files and were not touched.
- **Flake found and fixed** (in the test, not the code): two outbox rows can share a `created_at_utc` value on Windows'
  15.6 ms clock, so tests now select rows by event type. 25 of 25 reruns are green.

## 9. Version / boundary / deployment

- **Hash coverage (closes F-M1).**
  - `COMPONENT_SOURCES["notifier"]` now also includes `lab_delivery.py` and `store.py`.
  - `promotion` has its own sources for the first time: `promotion.py`, `store.py`, the notify outbox/worker,
    `operator_control/gates.py` and `alpaca_data.py`. Before, its hash covered the shared modules only.
  - A test asserts that every engine or notify module either component imports is hashed.
- **Boundary classes.**

  | Component | Class | Rule |
  |---|---|---|
  | notifier | **ROUTING_FIX** | Forced by the new `LAB_DELIVERY_POLICY` config fingerprint (`46a2c622a7856f88`). Delivery decisions change, so notification, alert-count and delivery metrics are segmented. |
  | promotion | **UI_ONLY** | `CONFIG_KEY_CLASS["promotion"] = {"promotion_src": "UI_ONLY"}`, applied only with a UI_ONLY declaration. |

  For promotion, an undeclared change, or any `PROMOTION_POLICY` fingerprint change, stays STRATEGY_MATERIAL (tested).
- **Other components.** Because `runtime.py` changed, every other component's hash moves. These are
  runtime-only changes: at each component's next restart,
  `python -m talonx_opportunity declare-shared-runtime --apply` records them as verified OPERATIONS_ONLY. The
  exception is discovery, which also carries the undeployed SEC remediation and still needs its DATA_FIX declaration.
- **Deployment scope.** Restart **notifier + promotion only**, after the after-hours session and before the next
  premarket. From a shell with the runbook §S3 environment (PAPER_SIGNAL, deliver, notify policy):
  1. `declare-change notifier --class ROUTING_FIX --reason "Lab delivery policy V1: immediate/digest routing + compact Lab format; V1 decisions unchanged"`
  2. `declare-change promotion --class UI_ONLY --reason "Signal message format only; PROMOTION_POLICY 4926c12e5eace04e unchanged"`
  3. `restart notifier`, then `restart promotion`.

  No discovery or evaluator restart is needed.
- **Live deployed:** NO.

## 10. Follow-ups

- **Signal volume:** decide on a score floor or top-N cap (a separate, authorised task; §7).
- **Lab budget / lifecycle:** the 30% ceiling here comes from HIGH-class invalidation and setup volume.
- **MATERIAL_UPDATE oscillation (MEDS, ONCO, NAMI):** candidates for a lifecycle-level hysteresis review. Not touched
  here.
- **Digest "Active setups":** includes identities carried over from earlier windows. Consider scoping it to the
  current window.
