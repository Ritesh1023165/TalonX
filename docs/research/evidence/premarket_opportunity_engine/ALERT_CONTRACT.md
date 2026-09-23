# Research alert contract

## Meaning

Every alert from this lane is a **RESEARCH opportunity**. It is:
- **not** a V2 TRADE_EVENT;
- **not** an order, intent, paper position or recommendation;
- **never** a trigger for automatic paper trading.

Every alert ends with: `Research alert only. Not a V2 trade event. Paper execution not started.`

**Types:** `WATCH`, `BULLISH_SETUP`, `BEARISH_SETUP`, `MATERIAL_UPDATE`, `INVALIDATED`.

**Example** (rendered by `talonx_premarket/alerts.py::render`):

```
[PREMARKET RESEARCH] XYZ — BULLISH_SETUP (Xyz Inc)
Gap: +4.20% (pre-market last 10.42 vs previous close 10)
Premarket volume: 100,000 sh ($1,000,000), 10.0% of 20d ADV
Previous close: 10 · prev range 9.8-10.1 · above prev high
Catalyst: 8-K earnings (item 2.02) filed 2026-09-22
Score: 70.0/100 (gap 30.0, activity 25.0, liquidity 5.0, catalyst 15.0, structure 10.0, data 0.0)
Why: new candidate; gap +4.20% = 2.3x its 20d ATR (1.80%); pre-market volume ...
Data: Alpaca SIP 1-min, 15-min delayed, as of 12:00 UTC · CORE_PREMARKET · outside V2 scope
Research alert only. Not a V2 trade event. Paper execution not started.
```

## Identity and dedup

**Identity:** `<session_date>:<SYMBOL>:<family>`, where family is `GAP_UP` or `GAP_DOWN`.

| Transition | Alert? |
|---|---|
| none → WATCH / BULLISH_SETUP / BEARISH_SETUP | **yes** (new), subject to the per-session cap of 25 new candidates, applied highest score first |
| WATCH → BULLISH_SETUP / BEARISH_SETUP | **yes** (upgrade) |
| same state; score moved ≥ 15 points **or** gap moved ≥ 3 percentage points, **and** ≥ 30 min since the last alert | **yes**: `MATERIAL_UPDATE` |
| active → gap below 1%, gap flipped direction, or price went stale | **yes**: `INVALIDATED` (once; the identity stays closed for the session) |
| unchanged re-scan; SETUP → WATCH downgrade; any change to a capped (suppressed) candidate | **no** |

Every alert event is persisted in `premarket_research.db` (`alerts`, `candidates`, `scans`), whether delivered or not. Capped candidates are recorded as `SUPPRESSED:SESSION_NEW_ALERT_CAP`.

**Data state unknown (PR19 hardening).**
- **What counts as unknown.** A symbol whose provider fetch is incomplete (`UNKNOWN:PROVIDER_INCOMPLETE`), or every symbol when the provider is stale (`UNKNOWN:PROVIDER_STALE`).
- **Effect.** The symbol is **held**: no new candidate, no update and **no INVALIDATED**. INVALIDATED is reserved for market facts computed from complete data.
- **Catalysts.** A failed catalyst lookup is `CATALYST UNKNOWN`, never "none".

**Routing vs delivery.**
- **Routing.** `alerts.routed` is the routing result (`RECORDED_NOT_DELIVERED` / `ENQUEUED_RESEARCH` / `ENQUEUED_RESEARCH_DESTINATION_DISABLED` / `SUPPRESSED:…` / `PENDING_ROUTE`).
- **Delivery.** `alerts.delivery_state` is the outbox's real state, synced every scan (PENDING / SENT / RETRY / FAILED / EXPIRED / HELD / AMBIGUOUS).
- **`candidates.delivered`** is 1 **only after an alert is actually SENT**.
- **Persistence order.** The alert and candidate are persisted in one transaction **before** routing; a crash in between is re-routed idempotently on restart.

**Tests:** `test_alert_state_machine_new_upgrade_update_invalidate_and_no_duplicates`, `test_new_alert_cap_suppresses_instead_of_spamming`, `test_session_cap_keeps_the_highest_scoring_new_candidates`, `test_replay_scan_cannot_see_future_bars` (an unchanged re-scan produces no alert).

## Routing (Telegram): an isolated RESEARCH path only

| Item | Value |
|---|---|
| **RESEARCH DESTINATION** | Logical destination `RESEARCH` in `talonx_ops.notify`, which is TalonX Lab. It needs its own bot token **and** chat, plus `TALONX_NOTIFY_RESEARCH_ENABLED=1`. It refuses to alias the TRADE_EVENT bot or chat, and has no fallback. |
| Outbox | Its own file, `results/premarket_research/premarket_research_notifications.db`. The engine refuses `v2_release_rc1_notifications.db`, `notifications.db`, `v2_release_rc1.db` and `v2_lane.db`. |
| Event types | `PREMARKET_RESEARCH_<TYPE>` (never TRADE_EVENT) |
| Freshness | `deliver_by = decision + 30 min`, so an alert that can't be sent promptly expires rather than arriving late |
| **LIVE ENABLED NOW** | **NO.** `.env` has `TALONX_NOTIFY_RESEARCH_ENABLED=0`, **and** the configured research chat ID equals the primary chat ID, so `resolve_destination_config(RESEARCH)` refuses it ("RESEARCH chat aliases TRADE_EVENT; isolation required"). |
| Default canary mode | `python -m talonx_premarket run`, without `--deliver`: every alert is recorded (`routed=RECORDED_NOT_DELIVERED`) and nothing is sent. |

**Explicit canary enable step** (operator action; secrets typed by the operator, never echoed):
1. Create or pick a separate Telegram chat for TalonX Lab. It must not be the Signal/primary chat.
2. Set `TALONX_NOTIFY_RESEARCH_CHAT_ID` to that chat in `.env`. The research bot token is already distinct.
3. Start the engine with the flag scoped to **its own process only**, never in the V2 stack's shell. The V2 release gate's `lab_off` check must stay PASS:
   ```powershell
   $env:TALONX_NOTIFY_RESEARCH_ENABLED = "1"; .venv\Scripts\python.exe -m talonx_premarket run --deliver
   ```
   `.env` is loaded with `override=False`, so this process-scoped value wins only inside this process.
4. Confirm the first status line shows `"research_destination_enabled": true`. If it's false, the reason is printed, and alerts are enqueued but never sent (`ENQUEUED_RESEARCH_DESTINATION_DISABLED`).

**Guards and tests:**
- `test_research_router_uses_only_the_research_destination`: only RESEARCH rows are written; a disabled destination sends nothing; protected DBs are refused.
- `test_research_destination_refuses_to_alias_the_primary_chat`.
- `test_research_lane_has_no_trading_or_v2_ledger_capability`: token scan for `TRADE_EVENT`, `submit_order`, `PaperTradingStore`, `execute_buy/sell`, and any `talonx_v2` import.
- `test_no_frozen_release_module_imports_the_research_lane`.

## Post-open confirmation (evaluation only)

- **Scope.** Only already-alerted candidates are tracked. Tracking never changes an alert, a score or a candidate (`test_outcomes_are_computed_only_after_alerts_and_do_not_change_them`).
- **Reference price.** The last pre-market price at the candidate's first alert. Measurements are direction-adjusted for GAP_DOWN.

| Horizon | Definition |
|---|---|
| OPEN | first regular-session 1-min bar open |
| +30M / +1H | close of the bar ending at open + 30 / + 60 min |
| CLOSE | last regular-session bar close |
| MFE / MAE | best and worst excursion over the session vs the reference price |

| Status | Rule |
|---|---|
| `OUTCOME_PENDING` | +30M not yet available |
| `INVALIDATED` | gap fully filled in the first 30 min (price crossed the previous close) |
| `CONFIRMED` | +30M price on the setup's side of the reference price |
| `FAILED_CONFIRMATION` | otherwise |

Nothing is traded.
