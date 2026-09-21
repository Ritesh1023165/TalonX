# Secret exposure trace (TASK F) - values never printed; fingerprints only
**TELEGRAM TOKEN WAS LOGGED: YES.**
- **Mechanism:** the Telegram Bot API puts the bot token in the URL path (`https://api.telegram.org/bot<token>/<method>`). `httpx` (used by the Telegram client) logs every request URL at INFO
  (`HTTP Request: POST <url> "HTTP/1.1 200 OK"`). `talonx_v2.run` (V2 companion) configured raw `logging.basicConfig(level=INFO, ...)` with no redaction and no httpx level, so the token was written to
  `results/prospective_2026-09-21/logs/v2_companion.log` (22 lines in the canary). `talonx_ops.logging_setup.configure_logging` (Original stack) already raised httpx to WARNING but was not used by the companion; older Original logs in `.run/logs` and `reports/` predate that.
- **Chat id:** not logged (it travels in the request body, not the URL). **Headers/query/body:** only the URL path carried a secret. **Alpaca keys / Gemini key / chat ids / Signal token / Lab token:** exact-value scan of the whole working tree found NO occurrence.
- **Exposed credentials (by one-way fingerprint sha256[:12]):** `TELEGRAM_BOT_TOKEN` (legacy/primary bot; 34 local files since 2026-08-13: `.run/logs` 24, `reports/` 7, `results/` 3) and `TALONX_NOTIFY_OPERATIONS_BOT_TOKEN` (Sentinel; 1 file: the canary companion log).
  Fingerprints are recorded in `talonx_v2/release_gate.py` (`compromised_secret_fingerprints`), not reversible.
- **Not on GitHub:** `git grep` of HEAD finds no token-shaped string; the affected directories (`.run/`, `reports/`, `results/`) are gitignored. (Git history was not exhaustively scanned.)
- **Local remediation done:** 35 local raw log files scrubbed in place (11,260 occurrences -> `bot[REDACTED]`). The evidence copy from the canary was already redacted.
