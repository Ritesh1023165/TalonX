# TalonX

**Project TalonX** is an event-driven, dual-horizon algorithmic trading &
fundamental research engine. It runs two decoupled strategies side by
side against the same watchlist:

- **Intraday Momentum Scanner** — minutes-to-hours holding period,
  technical-signal-triggered.
- **Long-Term Quality & Valuation Compounder** — quarterly-SEC-filing-
  driven, months-to-years holding period.

It's built from six cooperating modules:

- **`talonx_ingest`** (Module 1) — Data Ingestion & Event Producer Engine.
  Pulls SEC filings, news/social content, and live market data into
  searchable/structured form, and publishes real-time events to Redis.
- **`talonx_quant`** (Module 2) — Technical & Quantitative Scanner.
  Listens to the market data Module 1 produces, computes technical
  indicators, and publishes trade-setup signals.
- **`talonx_brain`** (Module 3) — Deep Research Agent & RAG Engine.
  Listens to the trade-setup signals Module 2 produces, retrieves relevant
  SEC filing and news context from Module 1's ChromaDB store, and asks
  an LLM to ground or challenge each technical signal against that
  context, publishing a structured research report.
- **`talonx_core`** (Module 4) — Core Event Bus & Decision Engine.
  Correlates Module 2's technical signals with Module 3's research
  reports per ticker, runs a Decision Matrix against them (do they agree,
  or contradict?), and publishes an actionable alert when one clears the
  confidence bar and isn't in cooldown.
- **`talonx_dispatch`** (Module 5) — Notification Dispatcher & Streamlit
  Interface. Listens for Module 4's actionable alerts, pushes them to
  Telegram as mobile notifications (including an interactive `/ping`
  health check), records every one to a durable audit trail, and serves
  a live Streamlit dashboard over that trail for monitoring and trade
  audit review.
- **`talonx_paper`** (Module 6) — Live Paper Trading Engine. Simulates
  BUY/SELL execution for both horizons per ticker, with ATR-anchored
  intraday stops and a DCA-aware long-term ledger.

---

## Documentation

Full documentation lives in **[`docs/`](docs/README.md)** — start there
for anything beyond this quick overview:

| | |
|---|---|
| **Getting started** | [Setup](docs/setup.md) · [Running things](docs/running.md) · [Troubleshooting](docs/troubleshooting.md) · [Configuration reference](docs/configuration.md) |
| **Architecture** | [Overview & data flow](docs/architecture-overview.md) · [Module 1: ingest](docs/modules/ingest.md) · [Module 2: quant](docs/modules/quant.md) · [Module 3: brain](docs/modules/brain.md) · [Module 4: core](docs/modules/core.md) · [Module 5: dispatch](docs/modules/dispatch.md) · [Module 6: paper](docs/modules/paper.md) · [Orchestrator](docs/modules/orchestrator.md) |
| **Cross-cutting features** | [Phase 2 multi-horizon](docs/phase2-multi-horizon.md) · [Earnings Radar](docs/earnings-radar.md) · [Pre-Market Radar](docs/premarket-radar.md) · [Bar buffer persistence](docs/bar_buffer_persistence.md) |
| **Reference** | [Roadmap / not built yet](docs/roadmap.md) · [Performance & Gemini tradeoffs](docs/performance.md) |

## Quick start

1. **[Prerequisites & first-time setup](docs/setup.md)** — Python
   3.11/3.12, Redis (`docker compose up -d`), a `.env` file, and (for
   Module 3) either a `GEMINI_API_KEY` or a local Ollama install.
2. Install and run everything together:
   ```powershell
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r talonx_ingest\requirements.txt
   copy .env.example .env
   # edit .env: at minimum, set TALONX_SEC_USER_AGENT
   python run_talonx.py
   ```
3. In a second terminal, the live dashboard:
   ```powershell
   streamlit run talonx_dispatch\app.py
   ```

See **[docs/running.md](docs/running.md)** for every module's standalone
entrypoint, `--skip-*` flags, and the test suite.

## Project layout

See **[docs/architecture-overview.md](docs/architecture-overview.md)**
for the full annotated directory tree. `.env` lives at the repo root and
is shared by every module; run all commands from `C:\workspace\TalonX`
(the repo root), not from inside a `talonx_*` package folder.
