# Troubleshooting

## Diagnose a hang or connectivity issue

If any command in [running.md](running.md) seems to hang with no log
output:
```powershell
python talonx_ingest\check_connectivity.py
```
Tests each external endpoint (SEC ticker map, SEC submissions API, SEC
archives, Hugging Face) with an 8-second timeout each, so you know in
under a minute which one (if any) is blocked — rather than waiting
indefinitely on a full pipeline run.

If you're behind a corporate proxy, set it first:
```powershell
$env:HTTPS_PROXY = "http://your-proxy:port"
python talonx_ingest\check_connectivity.py
```
(The pipeline and market data client both automatically honor
`HTTP_PROXY`/`HTTPS_PROXY` if set, via `trust_env=True`.)

For a live, per-ticker trace of exactly where the pipeline stalled (which
gate dropped it, whether it ever reached quant/brain/core/dispatch), use:
```powershell
python scripts\ticker_funnel_report.py <TICKER>
```
Safe to run against a live instance — every read is read-only.

## Common problems

| Symptom | Likely cause | Fix |
|---|---|---|
| `No module named 'talonx_ingest...'` | Running from the wrong folder | `cd` to `C:\workspace\TalonX` (the parent of `talonx_ingest`), not inside it |
| Command hangs, zero log lines | Corporate proxy/firewall blocking direct connections, or slow first-time model download | Run `check_connectivity.py`; set `HTTPS_PROXY` if needed |
| `403` errors from SEC | `TALONX_SEC_USER_AGENT` not set to a real contact string | Edit `.env`, set a real name/email |
| `pip install` fails on `chromadb`/`hnswlib` | Missing C++ build tools | Install VC++ Build Tools (see [setup.md](setup.md)) |
| New dependency "not found" after editing `requirements.txt` | Editing a different copy of the file than the one `pip install -r` reads | Confirm you're editing `C:\workspace\TalonX\talonx_ingest\requirements.txt` specifically, then re-run `pip install -r` |
| `.env` values seem ignored | `.env` isn't at the repo root | Move it to `C:\workspace\TalonX\.env` — it's resolved relative to each module's own file location (`../.env` from inside each package), not the current directory |
| `talonx_brain` raises `ValueError: GEMINI_API_KEY is not set` | Missing/empty `GEMINI_API_KEY` in `.env` while `TALONX_BRAIN_LLM_PROVIDER` is `gemini` (the default) | Get a key from [Google AI Studio](https://aistudio.google.com/apikey) and set it in `.env` at the repo root, or switch to the local provider instead: `TALONX_BRAIN_LLM_PROVIDER=ollama` (see [performance.md](performance.md)) |
| `talonx_brain` reports always come back `insufficient_context` | No filings ingested yet for that ticker | Run `python -m talonx_ingest.pipeline <TICKER>` ([running.md](running.md)) first so there's something in ChromaDB to retrieve |
| `talonx_brain` logs `404 NOT_FOUND ... is not found for API version` | The pinned model name in `TALONX_BRAIN_GEMINI_MODEL` was retired/restricted for your key | Leave it unset to use the default `gemini-flash-latest` alias (tracks whatever Google currently recommends), or pick a live one from `client.models.list()` |
| `talonx_brain` logs `429 RESOURCE_EXHAUSTED ... limit: 0` | Your key's free tier grants **zero** quota for that model (typically Pro models) | Switch to a Flash model, or enable billing on the Google AI Studio project |
| `talonx_brain` logs `429 RESOURCE_EXHAUSTED` with a nonzero `limit` **and** `quotaId: GenerateRequestsPerMinutePerProjectPerModel-FreeTier` | Genuine free-tier PER-MINUTE rate limit (can be as low as 5 requests/minute) -- with enough tickers under surveillance, signals can arrive faster than that | Lower `TALONX_BRAIN_GEMINI_RPM` to match your actual quota (the built-in rate limiter paces calls to stay under it instead of retrying into it), or enable billing for a higher limit |
| `talonx_brain` logs `429 RESOURCE_EXHAUSTED` with `quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier` (e.g. `limit: 500`) | A DIFFERENT, PER-DAY quota for that specific model -- distinct from the per-minute one above and NOT paced by `TALONX_BRAIN_GEMINI_RPM` (that limiter only throttles requests/minute, it has no daily budget concept). Easy to exhaust during active testing/development across a single day | Either wait for the quota to reset (resets daily, Pacific time), point `TALONX_BRAIN_GEMINI_MODEL` at a DIFFERENT model (the quota is per-model, so an unused one has its own separate 500/day allowance), or switch providers entirely: `TALONX_BRAIN_LLM_PROVIDER=ollama` (see [performance.md](performance.md)) has no quota of any kind |
| `talonx_brain` logs `503 UNAVAILABLE ... high demand` | Transient: Google's model servers are temporarily overloaded (shared free-tier capacity), unrelated to your quota or config | No action needed -- both the `google-genai` SDK and `llm.py`'s own retry wrapper (`TALONX_BRAIN_GEMINI_MAX_RETRIES`, default 3) retry this automatically. Only worth investigating if it persists past all retries and the signal gets logged as `Failed to generate research report` |
| `talonx_brain` (with `TALONX_BRAIN_LLM_PROVIDER=ollama`) logs a connection error / `Failed to generate research report` on every signal | `ollama serve` isn't running, or `TALONX_BRAIN_OLLAMA_MODEL` hasn't been pulled | Run `ollama list` to confirm the service is up and the model is present; `ollama pull <model>` if not (see [performance.md](performance.md)) |
| `talonx_core` never alerts even though both a signal and a report clearly arrived | Confidence below `TALONX_CORE_MIN_CONFIDENCE`, verdict is neutral/insufficient_context, one half is stale (outside `TALONX_CORE_CORRELATION_WINDOW`), or the ticker is still in cooldown (`TALONX_CORE_TICKER_COOLDOWN`) | Use `scripts\ticker_funnel_report.py <TICKER>` to see exactly which gate suppressed it, or temporarily lower the thresholds to confirm the pipeline itself is wired correctly |
| `talonx_core` (or `run_talonx.py`) logs `database is locked` from `store.py` | Two processes pointed at the SAME `TALONX_CORE_STATE_DB` file at once (e.g. `talonx_core.run` standalone AND `run_talonx.py` both running) -- SQLite allows one writer at a time | Only run one talonx_core instance per state DB file; point a second instance at a different `TALONX_CORE_STATE_DB` path if you genuinely need two |
| Streamlit dashboard (`app.py`) stays empty | `talonx_dispatch.run` isn't running -- the dashboard only READS the audit trail, it never touches Redis itself | Start `python -m talonx_dispatch.run` in another terminal; confirm alerts are actually reaching `talonx:alerts:dispatch` in the first place ([running.md](running.md)'s dashboards can confirm this) |
| No Telegram push arrives even though the audit trail shows the alert | Severity below `TALONX_DISPATCH_MIN_SEVERITY` (default `warning` -- `info` alerts are recorded but not pushed on purpose), or `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` unset | Check the alert's `severity` in the audit trail/Streamlit feed; lower `TALONX_DISPATCH_MIN_SEVERITY` to `info` if you want everything pushed. Also check `scripts\ticker_funnel_report.py <TICKER>` and the Daily Funnel & Metrics tab — the alert may simply never have been published by quant/core in the first place (e.g. confluence-gate suppression) |
| Telegram send fails with `Forbidden` | The bot hasn't been messaged first (bots can't initiate a DM), or it was blocked/removed from the chat | Message your bot at least once from the Telegram app before running `talonx_dispatch.run` ([setup.md](setup.md)) |
| Telegram message text looks garbled/truncated mid-sentence | An underscore/asterisk/backtick/bracket in Gemini-generated text wasn't escaped correctly, or a message exceeded Telegram's 4096-character limit | `formatter.py` escapes the 4 legacy-Markdown special characters and truncates the research summary to 500 chars -- if this still happens, it's likely in `key_findings`/`risk_factors` text, which isn't length-capped per-item today |
| `generate_eod_report.py`'s "LLM / cache economics" / signal-funnel sections say "Not available" | `talonx_core`/`talonx_quant`/`talonx_brain` haven't run with persistence enabled since this feature was added (or `TALONX_*_ENABLE_PERSISTENCE=false`) -- their stats stores have no rows yet | Run the pipeline normally for at least one session with persistence enabled (the default); the report only ever shows what those processes actually recorded |
| `generate_eod_report.py` shows an empty per-ticker section for a day you know had activity | `--date`/`--tz` picked a different trading-day window than you expected (a UTC timestamp near local midnight can land on the adjacent day) | Pass `--tz` explicitly if you're not in `America/New_York`, and double check `--date` is the LOCAL calendar date, not UTC |
| `yfinance` logs `possibly delisted; no price data found` / `'exchangeTimezoneName'` for every ticker at once, and `talonx_quant` stops evaluating anything | A long-running process's cached `yfinance` session got stuck (Yahoo's undocumented API occasionally returns a malformed response that a bare dict-key access in `yfinance` itself doesn't guard against) | `talonx_ingest.market_data.yfinance_poll.YFinancePoller` now detects a degraded cycle (most/all symbols failing) and self-heals by resetting the cached session after enough consecutive failures — see [performance.md](performance.md). If it's still stuck, a restart clears it immediately |
| After a restart, `talonx_quant` produces nothing for ~24 minutes, or the 15-min trend gate never seems to activate | Expected warm-up behavior, not a bug — the 1-min buffer needs 120 bars (~24min at the default 12s poll interval), and the 15-min HTF buffer needs 200 bars (~50 continuous hours) | See [bar_buffer_persistence.md](bar_buffer_persistence.md) for exactly how both buffers checkpoint/reload across a restart, and use `scripts\ticker_funnel_report.py <TICKER>`'s "BUFFER WARM-UP" section to check current progress |
