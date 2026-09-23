# TalonX Lab channel enablement: one controlled validation send

Date: 2026-09-23 23:18 UTC (the evening before the 2026-09-24 session). Base: main `c0b46bb` (PR #19 merged).

## Requirement change

Signal, Sentinel and Lab may share one private owner `chat_id`. Isolation is **logical destination + bot identity + event contract**, not chat_id uniqueness. See [`docs/NOTIFICATION_CONTRACT.md`](../../../NOTIFICATION_CONTRACT.md).

## Review of chat and bot identity checks

| Location | Check | Classification | Action |
|---|---|---|---|
| `talonx_ops/notify/__init__.py` (RESEARCH) | Research chat == TRADE_EVENT chat → refuse | **OBSOLETE ASSUMPTION** | Removed |
| `talonx_ops/notify/__init__.py` (RESEARCH) | Research token == primary token → refuse | **REQUIRED SECURITY CONTROL** | Kept and widened: the Lab token must also differ from the Sentinel (`OPERATIONS`) token and the legacy `TELEGRAM_BOT_TOKEN` |
| `talonx_ops/notify/__init__.py` (RESEARCH) | No fallback; explicit `TALONX_NOTIFY_RESEARCH_ENABLED=1` | REQUIRED SECURITY CONTROL | Unchanged |
| `talonx_v2/release_gate.py` `signal_sentinel_distinct` | (bot, chat) pairs differ | REQUIRED (V2 frozen gate) | Unchanged. It already passes with a shared chat and distinct bots. |
| `talonx_v2/release_gate.py` `lab_off` | Research not enabled in the V2 environment | REQUIRED SECURITY CONTROL | Unchanged |
| `talonx_ops/operator_read.py` `shares_chat_with` | Informational dashboard field | UNRELATED | Unchanged |
| `talonx_premarket/__main__.py` `PROTECTED_DB_NAMES` | Research refuses V2/shared DBs | REQUIRED SECURITY CONTROL | Unchanged; re-tested |

## Controlled send (one real message)

Bot identities are shown as labels; no token or chat ID is recorded.

| Step | Result |
|---|---|
| Persistent `.env` `TALONX_NOTIFY_RESEARCH_ENABLED` | `0` before and after |
| RESEARCH before the override | disabled |
| RESEARCH with the process-scoped override | enabled, bot = **Lab** (not Signal, not Sentinel), same chat as Signal = true (allowed) |
| Outbox | `results/premarket_research/premarket_research_notifications.db` (research-only, not a protected DB; empty beforehand) |
| Event | `event_id`/`dedup_key` `lab-channel-validation-2026-09-24-001`, `event_type` `PREMARKET_RESEARCH_LAB_TEST`, `deliver_by` = enqueue + 10 min |
| Text | `[TALONX LAB TEST]` / Research destination validation. / No trade event. / No market action. / TalonX Lab channel test only. |
| First drain | considered 1, **sent 1**, failed 0, ambiguous 0, expired 0, retry 0, held 0; row state **SENT**, attempts 1 |
| Real Telegram sends by bot | Lab 1, Signal 0, Sentinel 0 (every `TelegramClient.send` was counted by bot identity) |
| One-message guard | `retry_ambiguous=False` and `max_attempts=1` for this run, so a timeout could not double-send |
| Dedup: same event id re-enqueued | `enqueue` returned False (no new row); second drain considered 0, sent 0; outbox total rows 1 |
| Override removed | RESEARCH disabled again; the disabled drain sent 0 |
| V2 files (`v2_release_rc1*.db` + WAL, `v2_lane.db`, `notifications.db` + WAL, `v2_release_rc1_status.json`) | sha256 and mtime unchanged |

## V2 release gate after the send

Run with the seven V2 release variables and no research enable in the shell. Status **READY**:

- strategy `e2acf6454789217e`
- provider `ac5e51aa3599d6c9`
- `signal_sentinel_distinct` PASS
- `lab_off` PASS
- the only WARN is the pre-existing, disclosed `intelligence_card_delivery`

PREMARKET_RESEARCH_V1 fingerprint: `62ba413daf85e674` (unchanged).
