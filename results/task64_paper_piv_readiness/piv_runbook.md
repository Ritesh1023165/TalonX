# Paper PIV Runbook

Required environment: `APCA_API_KEY_ID`, `APCA_API_SECRET_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TALONX_PIV_PAPER_TRADING=true`, `TALONX_PIV_REAL_CAPITAL=false`. The broker endpoint is immutable paper Alpaca; SIP requests explicitly use `feed=sip`.

1. `py -3.12 -m talonx_piv.cli preflight --approved-sha (git rev-parse HEAD)`
2. Continue only on exact `PIV_READY`. This does not enable orders.
3. Optionally clear verified paper state: `py -3.12 -m talonx_piv.cli cleanup --confirm-paper-cleanup`.
4. Explicitly start: `py -3.12 -m talonx_piv.cli start --approved-sha (git rev-parse HEAD) --confirm-paper-session-start`.
5. Emergency: `py -3.12 -m talonx_piv.cli kill-switch --cancel-paper-orders`.
6. EOD: `py -3.12 -m talonx_piv.cli eod`.

Never continue after `PIV_BLOCKED`. Cleanup and session start are separate explicit actions. No command supports a live-money endpoint.
