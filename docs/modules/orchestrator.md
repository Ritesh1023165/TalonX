# `run_talonx.py` — orchestrator

Runs Module 1's periodic ingestion (filings + news, immediately then on
a repeating interval) and Module 1 + 2 + 3 + 4 + 5 + 6's six continuous
streams (market data, quant scanner, research agent, decision engine,
dispatch agent, paper trading engine) together as concurrent tasks in one
process. A failure in one periodic ingestion cycle is logged and the loop
continues to the next scheduled run; the continuous streams are
unaffected by ingestion cycle failures entirely, since they're
independent tasks. Module 3 is optional here -- `--skip-brain` leaves it
out on purpose, and it's left out automatically (with a warning, not a
crash) if its configured LLM provider isn't ready (see
[brain.md](brain.md)). Modules 5 and 6 degrade the same way if their
respective SQLite ledgers can't be opened (rare). Modules 2 and 4 are
always included unless explicitly skipped. **The Streamlit dashboard is
never included** (see [dispatch.md](dispatch.md) -- run it alongside
this file, in its own terminal, [../running.md](../running.md)).

**Every continuous component can be pulled out individually**
(`--skip-market-data`, `--skip-quant`, `--skip-brain`, `--skip-core`,
`--skip-dispatch`, `--skip-paper-trading`, `--skip-earnings-sync`,
`--skip-earnings-fast-track` -- the last two disable the Event-Driven
Earnings Radar's weekly calendar sync / 15-min fast-track poller
respectively, see [../earnings-radar.md](../earnings-radar.md) --
`--skip-premarket` disables the whole-watchlist pre-market poller, see
[../premarket-radar.md](../premarket-radar.md)) -- useful while actively
iterating on one piece: run the others here and the one you're changing
in its own terminal, so you don't have to restart this whole process on
every edit. If every component ends up skipped (including
`--skip-ingestion`), it logs an error and exits immediately rather than
hanging on an empty task list.

See [../architecture-overview.md](../architecture-overview.md) for the
full end-to-end data-flow diagram across all 6 modules.
