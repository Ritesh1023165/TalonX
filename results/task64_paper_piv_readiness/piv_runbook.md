# Paper PIV Runbook

Required environment: `APCA_API_KEY_ID`, `APCA_API_SECRET_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TALONX_PIV_PAPER_TRADING=true`, `TALONX_PIV_REAL_CAPITAL=false`, `TALONX_PIV_FEED_MODE` (`RESEARCH_SIP` or `IEX_PAPER_PIV`, default `RESEARCH_SIP`). The broker endpoint is immutable paper Alpaca. The configured feed mode pins the market-data `feed` param for every request (`sip` or `iex`) with no fallback between them in either direction. `IEX_PAPER_PIV` is operational PIV evidence only -- never canonical alpha validation, which remains SIP-based.

1. `py -3.12 -m talonx_piv.cli preflight --approved-sha (git rev-parse HEAD)`
2. Continue only on exact `PIV_READY`. This does not enable orders.
3. Optionally clear verified paper state: `py -3.12 -m talonx_piv.cli cleanup --confirm-paper-cleanup`.
4. Explicitly start: `py -3.12 -m talonx_piv.cli start --approved-sha (git rev-parse HEAD) --confirm-paper-session-start`. As of Task 65 this **blocks** for the rest of the session: it runs `SessionRunner`, which polls Alpaca's batched multi-symbol bars endpoint every 60s on the configured feed, drives `SessionReadinessValidator` and the frozen ORPB_V1 shadow controller (read-only import, symbols excluded from live evaluation if `DATA_NOT_READY`), and submits any resulting entry/exit through the paper lifecycle -- until the configured EOD flatten time. Pass `--no-live-loop` to keep the old Task64 behavior (flip `session_enabled` and return immediately, no data loop).
5. Emergency, from a separate terminal while `start` is still running: `py -3.12 -m talonx_piv.cli kill-switch --cancel-paper-orders`. The running loop reloads lifecycle state from disk every tick and stops cleanly (no new orders) once it observes the kill switch.
6. EOD: `py -3.12 -m talonx_piv.cli eod`.

Never continue after `PIV_BLOCKED`. Cleanup and session start are separate explicit actions. No command supports a live-money endpoint.
