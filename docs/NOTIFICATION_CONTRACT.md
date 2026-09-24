# TalonX notification contract

This is the authoritative description of TalonX's three Telegram bots. The code that enforces it is `talonx_ops/notify/__init__.py` (`resolve_destination_config`).

## Destinations

| Bot | Logical destination | Role | Delivery model today |
|---|---|---|---|
| **TalonX Signal** | `TRADE_EVENT` | User-facing trade and intelligence events (V2 ENTRY/EXIT, Intelligence cards) | One configured private `chat_id` |
| **TalonX Sentinel** | `OPERATIONS` | Private, owner-only operations: incidents, account blocks, reconciliation, startup/shutdown, delivery failures | One configured owner/private `chat_id` |
| **TalonX Lab** | `RESEARCH` | Private, owner-only research (for example `PREMARKET_RESEARCH_*`). Never a trade event. | One configured owner/private `chat_id`, **OFF by default** |

## Identity model: bot token vs chat_id

- A **bot token** identifies the sender (which bot posts).
- A **chat_id** identifies the Telegram conversation it posts into.
- **The same chat_id MAY be used by multiple TalonX bots.** A person's private chat_id is the same for every bot they talk to. Telegram still shows each bot as a separate conversation.
- **The same chat_id does NOT mean the same logical TalonX destination.**

Isolation is therefore enforced by **logical destination + bot identity + event contract**, not by chat_id uniqueness:

1. Each logical destination has its own bot token. A token reused across destinations is rejected.
2. Business code names a logical destination; only `talonx_ops.notify` resolves it to a bot and chat.
3. `RESEARCH` has **no fallback**. Without its own token, chat and explicit enable, it is disabled and rows stay PENDING. It is never sent through Signal, Sentinel or the legacy primary bot.
4. `TRADE_EVENT` / `OPERATIONS` may fall back to the legacy `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` (unchanged behaviour). They never resolve to the Lab bot.
5. The outbox `destination` column decides which bot drains a row. Research producers write only `destination=RESEARCH` with `PREMARKET_RESEARCH_*` event types.
6. Research uses its own outbox (`results/premarket_research/premarket_research_notifications.db`) and refuses `v2_release_rc1_notifications.db`, `notifications.db`, `v2_release_rc1.db` and `v2_lane.db`.

## Lab enablement (double opt-in)

`RESEARCH` resolves as enabled only when **all** of these hold:

- `TALONX_NOTIFY_RESEARCH_ENABLED=1` **in the research process only**. The persistent `.env` value stays `0`, and it is never set in the V2 window: the V2 release gate's `lab_off` check fails if it is.
- `TALONX_NOTIFY_RESEARCH_BOT_TOKEN` and `TALONX_NOTIFY_RESEARCH_CHAT_ID` are set.
- The Lab token differs from the Signal token (`TALONX_NOTIFY_TRADE_EVENT_BOT_TOKEN`), the Sentinel token (`TALONX_NOTIFY_OPERATIONS_BOT_TOKEN`) and the legacy `TELEGRAM_BOT_TOKEN`.

A Lab chat_id equal to the Signal/Sentinel chat_id is **allowed**. (Before 2026-09-24 this was rejected; that rule was retired as an obsolete assumption.)

## Research producers and the attention budget (S14, 2026-09-24)

| Producer | Outbox (research-only; the protected V2/shared outboxes are refused) | Event types |
|---|---|---|
| `talonx_opportunity.notifier` (Continuous Opportunity Engine) | `results/opportunity/opportunity_research_notifications.db` | `OPPORTUNITY_RESEARCH_{NEW,UPGRADE,MATERIAL_UPDATE,INVALIDATED}` |
| `talonx_premarket` (V1 pre-market canary; SUPERSEDED for live use, kept for history) | `results/premarket_research/premarket_research_notifications.db` | `PREMARKET_RESEARCH_*` |

Every row has `destination=RESEARCH` and provenance `not_a_trade_event: true`. The text ends with "Research alert only. Not a V2 trade event. Paper execution not started."

**Candidate detection and durable persistence are independent from notification limits.**

The attention budget exists only in the notification worker (`LAB_NOTIFY_POLICY_V1`, versioned and fingerprinted):

- **Total:** 25 new surfacings per trading window. This is V1's figure, kept for a controlled comparison; it is configuration, not an evidence-derived value.
- **WATCH share:** WATCH may use at most 15. 10 are reserved so that later BULLISH/BEARISH setups stay deliverable.
- **Priority:** setups come before WATCH within one discovery evaluation.
- **Updates and invalidations:** MATERIAL_UPDATE and INVALIDATED are sent only for candidates that were surfaced.
- **Bookkeeping:** EXPIRED and REFERENCE_ROLLED are never sent.
- **Recorded decisions:** every decision is persisted (`SELECTED` / `BUDGET_EXHAUSTED_*` / `NOT_SURFACED_PARENT` / `POLICY_SILENT` / `PHASE_DISABLED`), together with the real outbox state. ENQUEUED is not SENT.

This **SUPERSEDES** the V1 contract's "at most 25 new candidates per session (highest score first)". That cap sat inside candidate lifecycle creation, where it froze suppressed identities. It never limited raw detection.

## Signal roadmap (NOT implemented)

Signal may later become an opt-in subscriber bot. Possible future work:

- subscriber joins via `/start` opt-in
- subscription persistence
- unsubscribe
- broadcast / fan-out
- owner/admin controls
- abuse and rate-limit protections

**None of this is implemented.** Signal today delivers to one configured chat only. Any subscriber work needs its own authorised task, and it must keep Sentinel and Lab private and owner-only.
