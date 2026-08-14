# TalonX Documentation

Split out of the single top-level `README.md` for easier navigation.
Start with [../README.md](../README.md) for the project overview and
quick start, then come here for depth on any specific topic.

## Getting started

- [setup.md](setup.md) — prerequisites and first-time setup (`.env`,
  API keys, Telegram/Reddit registration)
- [running.md](running.md) — how to run everything together, or each
  module standalone
- [troubleshooting.md](troubleshooting.md) — common problems and their
  fixes, including a live per-ticker diagnostic tool
- [configuration.md](configuration.md) — environment variable reference

## Architecture

- [architecture-overview.md](architecture-overview.md) — project layout
  and the end-to-end data-flow diagram
- Per-module deep dives:
  - [modules/ingest.md](modules/ingest.md) — Module 1: Data Ingestion & Event Producer
  - [modules/quant.md](modules/quant.md) — Module 2: Technical & Quantitative Scanner
  - [modules/brain.md](modules/brain.md) — Module 3: Deep Research Agent & RAG Engine
  - [modules/core.md](modules/core.md) — Module 4: Core Event Bus & Decision Engine
  - [modules/dispatch.md](modules/dispatch.md) — Module 5: Notification Dispatcher & Streamlit Interface
  - [modules/paper.md](modules/paper.md) — Module 6: Live Paper Trading Engine
  - [modules/orchestrator.md](modules/orchestrator.md) — `run_talonx.py`

## Cross-cutting features

- [phase2-multi-horizon.md](phase2-multi-horizon.md) — the `LONG_TERM`/
  `DUAL_HORIZON` fundamentals-driven investing horizon, alongside the
  original intraday engine
- [earnings-radar.md](earnings-radar.md) — Event-Driven Earnings Radar
  (calendar sync, T-48h heads-up, fast-track filing ingestion,
  two-stage revaluation)
- [premarket-radar.md](premarket-radar.md) — whole-watchlist pre-market
  price capture, and `talonx_quant`'s own pre-market signal-quality gates
- [bar_buffer_persistence.md](bar_buffer_persistence.md) — how
  `talonx_quant`'s rolling bar buffers checkpoint to and reload from
  disk, and exactly how a restart gap (redeploy, overnight, weekend) is
  handled

## Reference

- [roadmap.md](roadmap.md) — what's not built yet, and why
- [performance.md](performance.md) — throughput profile, the Gemini
  model tradeoff and upgrade path, the Ollama local alternative,
  `talonx_quant`'s noise-filter history, and yfinance session
  self-healing
