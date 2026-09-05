# Tomorrow 08:00 UK Handoff

> **SUPERSEDED (Task 66A, 2026-08-24).** This document is preserved as historical evidence of Task 64's
> handoff state and must not be edited to reflect later events. It predates Task 65/65B (feed mode, real
> decision path, causal warmup, crash-resilience fix, PIV_LIFECYCLE_PROBE) and Task 66A (restart-safe
> readiness persistence, restored Telegram inbound `/ping`, this cleanup). For current status, use
> **[`results/task65_piv/claude_handoff_next.md`](../task65_piv/claude_handoff_next.md)** (session outcome)
> and **[`results/task64_paper_piv_readiness/piv_runbook.md`](piv_runbook.md)** (current runbook, kept
> up to date in place rather than superseded).

Branch: `research/talonx-strategy-validation`. Approved release is the Task 64 commit containing this document; verify its SHA equals the completion handoff with `git rev-parse HEAD`. Deployment is `PAPER_PIV_BLOCKED` until every preflight check passes. REAL CAPITAL IS DISABLED. ORPB_V1 and FPRC_V1 are rejected; do not tune, replicate, promote, or invent alpha.

## Environment

Load `.env` with `APCA_API_KEY_ID`, `APCA_API_SECRET_KEY`, `TELEGRAM_BOT_TOKEN`, and `TELEGRAM_CHAT_ID`. Set `TALONX_PIV_PAPER_TRADING=true` and `TALONX_PIV_REAL_CAPITAL=false`. Do not set a live broker endpoint. Alpaca verification must report `PAPER endpoint=https://paper-api.alpaca.markets`; SIP verification must return HTTP 200 for explicit `feed=sip`; Telegram `getMe` must pass.

## Exact sequence and commands

At 08:00 UK run:

`py -3.12 -m talonx_piv.cli preflight --approved-sha (git rev-parse HEAD)`

`PIV_READY` means all release, paper identity/state, SIP, calendar/universe, writable telemetry, Telegram, kill-switch, flatten, and duplicate checks passed. Any other result is `PIV_BLOCKED`; do not start. A pass does not enable orders.

If a clean paper slate is explicitly wanted:

`py -3.12 -m talonx_piv.cli cleanup --confirm-paper-cleanup`

After `PIV_READY`, and only on explicit operator authorization:

`py -3.12 -m talonx_piv.cli start --approved-sha (git rev-parse HEAD) --confirm-paper-session-start`

Expected Telegram sequence begins `PAPER / NO REAL CAPITAL | ... | STARTUP`, then `PREFLIGHT_PASS`, then `PAPER_SESSION_STARTED`; market events follow. Telegram failures are observational and isolated after startup.

Kill switch:

`py -3.12 -m talonx_piv.cli kill-switch --cancel-paper-orders`

EOD/reconciliation:

`py -3.12 -m talonx_piv.cli eod`

Runtime logs/artifacts are in `results/task64_paper_piv_readiness/runtime/`: `piv_events.jsonl`, `lifecycle_state.json`, `latest_preflight.json`, `latest_reconciliation.json`, and `latest_session_report.json`.

## Known blocker and limits

Tonight's live non-ordering preflight positively verified the paper account (zero orders, zero positions, matched internal state) and Telegram, but explicit Alpaca SIP latest-trade access returned HTTP 403. Consequently the release is fail-closed and no session start/order was authorized. Resolve SIP entitlement/access without substituting IEX. The new control plane is separately namespaced; connecting it to a strategy process must not bypass readiness or hard guards.

After the session paste back: approved SHA, full preflight report, event JSONL, reconciliation and session reports, broker paper activity export, Telegram delivery failures, readiness gaps, unexpected/missed/duplicate events, and the anomaly classification. Never paste credentials.
