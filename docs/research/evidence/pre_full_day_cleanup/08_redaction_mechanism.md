# Redaction mechanism (TASK G) - **LOGGING FIXED: YES**
`talonx_ops/log_redaction.py` (installed on import; idempotent) applies at LOG-RECORD level for the whole process, independent of logger/handler/format:
- `logging.setLogRecordFactory` wrapper redacts the fully formatted message; `Formatter.formatException` / `formatStack` are wrapped, so exception and stack text are redacted;
- redacts Telegram `bot<id>:<token>` URLs, `Authorization`/`Bearer` values, `APCA-API-KEY-ID`/`APCA-API-SECRET-KEY`, `token|secret|api_key|password|chat_id` key=value/query pairs, and **the exact value of every secret-looking environment variable**;
- `httpx`/`httpcore` also set to WARNING (defence in depth only - not the mechanism).
Installed by `talonx_v2/run.py` (V2 companion), `talonx_ops/supervisor.py`, `talonx_dispatch/run.py`, `talonx_dispatch/telegram_client.py`, `talonx_ops/notify/__init__.py`, `talonx_ops/logging_setup.py`.
Tests: `test_07` (request + failure logs), `test_08` (exception + stack text), `test_09` (provider secret, Authorization, api_key, password, exact env value), `test_10/11` (process-wide, entry points). Mutation-verified (redaction disabled -> 4 tests fail). No real token in any test.
