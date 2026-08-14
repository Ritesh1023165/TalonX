# Setup

## Prerequisites

| Requirement | Notes |
|---|---|
| **Python 3.11 or 3.12** | Get it from [python.org/downloads](https://www.python.org/downloads/) — not the Microsoft Store version. Check "Add python.exe to PATH" during install. **Avoid Python 3.13+** for now: `numba` (a `pandas_ta` dependency) doesn't yet support it. |
| **Visual C++ Build Tools** (Windows only) | Needed if `pip install` fails compiling `chromadb`/`hnswlib`. Get the "Desktop development with C++" workload from the [VC++ Build Tools installer](https://visualstudio.microsoft.com/visual-cpp-build-tools/). |
| **An editor** | VS Code (Python extension) or Visual Studio 2022 (Python Development workload). |
| **~2GB free disk** | `sentence-transformers` pulls in PyTorch on first install. |
| **Redis** | Required for Module 2 and Module 3, and for event publishing in Module 1 (Module 1 still works without it — publishing just degrades gracefully). `docker compose up -d` from the repo root starts it (see `docker-compose.yaml` — pinned `redis:7.0.15`, healthchecked, named `talonx-redis`); `docker compose down` to stop it. |
| **An LLM for Module 3** (`talonx_brain`) | Two options, switchable via `TALONX_BRAIN_LLM_PROVIDER` — see [modules/brain.md](modules/brain.md) and [performance.md](performance.md). **Gemini** (default): free-tier cloud, needs a `GEMINI_API_KEY` from [Google AI Studio](https://aistudio.google.com/apikey), but its free-tier quotas (per-minute AND per-day) are easy to exhaust under active testing. **Ollama** (local): no API key, no quota, runs entirely on your machine — needs [Ollama](https://ollama.com/download) installed with a model pulled (`ollama pull llama3.1`). |

See [architecture-overview.md](architecture-overview.md) for the full
project layout.

## First-time setup

Open a terminal (VS Code integrated terminal, or Visual Studio's Terminal
pane) **in `C:\workspace\TalonX`** — the parent folder, not `talonx_ingest`.

```powershell
# 1. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate

# Your prompt should now show (.venv) at the start of the line.

# 2. Install dependencies
pip install -r talonx_ingest\requirements.txt
```

This installs `aiohttp`, `chromadb`, `sentence-transformers` (pulls in
PyTorch — the slow part), `websockets`, `yfinance`, and a few smaller
libraries. Expect this step to take several minutes on first run.

```powershell
# 3. Set up your .env file (repo root, shared by every module)
copy .env.example .env
```

Edit `.env` and set at minimum:
```
TALONX_SEC_USER_AGENT="Your Name Your Company your.email@example.com"
```
SEC EDGAR requires a real, descriptive User-Agent — without one you'll get
403 errors. Everything else in `.env.example` is optional and has sane
defaults (commented out).

If you want live market data via Polygon.io (optional — yfinance polling
works with no key at all), also set:
```
POLYGON_API_KEY=your_polygon_io_api_key
```

If you want to run Module 3 (`talonx_brain`), pick ONE of the two LLM
providers below ([performance.md](performance.md) has the full tradeoff
writeup):

**Option A — Gemini (default, cloud)**, required — there's no fallback
path without it:
```
GEMINI_API_KEY=your_gemini_api_key
```

**Option B — Ollama (local, no API key/quota)** — install
[Ollama](https://ollama.com/download), run `ollama pull llama3.1` once,
then set:
```
TALONX_BRAIN_LLM_PROVIDER=ollama
```
`ollama serve` must be running (the installer sets it up as a background
service on Windows, so this is usually already true — check with
`ollama list`). No `GEMINI_API_KEY` needed for this path.

If you want Reddit as an additional news/social source (optional —
NewsAPI/RSS already work with no signup at all; Reddit adds ON TOP of
that, it's not required for anything else to function):
1. Log into Reddit, go to https://www.reddit.com/prefs/apps
2. Click "create another app...", choose **script**, fill in any
   name/description, redirect URI can be `http://localhost:8080`
   (unused, but the form requires something)
3. After creating it, the client ID is the string under the app name;
   the client secret is labeled "secret"
4. Set in `.env`:
```
REDDIT_CLIENT_ID=your_client_id
REDDIT_CLIENT_SECRET=your_client_secret
REDDIT_USER_AGENT="TalonX Research Engine by /u/your_reddit_username"
```
Reddit requires a real, descriptive User-Agent identifying an actual
account (same non-negotiable rule SEC EDGAR has for
`TALONX_SEC_USER_AGENT`) — a generic or missing one gets throttled hard
or blocked.

If you want Telegram push notifications from Module 5
(`talonx_dispatch`), optional — without it, alerts are still recorded to
the audit trail and shown in the Streamlit dashboard, you just don't get
a mobile push:
1. In Telegram, message **@BotFather** → `/newbot` → follow the prompts
   (name, username ending in `bot`). It replies with a token that looks
   like `123456789:AAH...` — that's your `TELEGRAM_BOT_TOKEN`.
2. Send your new bot ANY message first (bots can't message you until you
   message them first) — search for its username and send e.g. `hi`.
3. Get your chat ID: open
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser
   (substitute your real token), and find `"chat":{"id":...}` in the
   response — that number is your `TELEGRAM_CHAT_ID`.
4. Set in `.env`:
```
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

Each push is now a short summary ending in an ID (`#47`) — **reply to
that message with the number** (`47`, `#47`, `/details 47`, or `/id 47`
all work) to get the full research writeup back from the bot, or send
`/ping` for a live health check (uptime, CPU/RAM, WebSocket status,
today's signal counts — see [modules/dispatch.md](modules/dispatch.md)).
Only replies from the `TELEGRAM_CHAT_ID` above are answered. An ID stops
working once its alert ages out of the audit trail
(`TALONX_DISPATCH_RETENTION_DAYS`, default 5 days) — the bot replies
"not found" rather than erroring.

Next: [running.md](running.md) for how to start everything.
