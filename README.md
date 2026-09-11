# TalonX

TalonX is a **descriptive, human-in-the-loop, event-driven trading & risk-intelligence system**
for US equities. It ingests live market data and SEC filings, runs one frozen selective intraday
strategy (**Original**), runs a second internal-only validation lane (**Experimental**), produces
deterministic event/risk intelligence, and surfaces everything on a single read-only operator
cockpit.

**TalonX makes no profitability claim. It executes no real capital, takes no short positions, and
uses no paid data. The current Original strategy is deliberately selective and its edge is
UNPROVEN.**

Full docs: **[`docs/README.md`](docs/README.md)** ·
architecture: **[`docs/CURRENT_ARCHITECTURE.md`](docs/CURRENT_ARCHITECTURE.md)**.

## 1. What TalonX is

An operator's cockpit over four supervised processes: an Original control pipeline, an
internal-only Experimental shadow lane, a descriptive SEC intelligence service, and a read-only
dashboard — all owned by `talonx_ops.supervisor`.

## 2. Current capabilities

- Live market ingestion → one authoritative market path + one authoritative health accessor.
- Original Quant → Brain → Decision pipeline with **frozen** thresholds; long-only local paper.
- Experimental shadow lane: relaxed-profile directional alerts, `WOULD_PASS`/`WOULD_REJECT`
  labels, experimental paper, forward outcomes (MFE/MAE/+30m/+60m/EOD/+1D), persisted pre-market
  surface — **never externally dispatched**.
- Risk & Event Intelligence: SEC 8-K/10-Q/10-K + Form 3/4/5, deterministic "what changed",
  insider aggregation, an explainable **Information Significance** band — **no forward-return
  input, no direction**.
- One unified `:8787` cockpit (six sections) + a loopback-only `/admin/` config page.
- Durable EOD reconciliation; one official Telegram send path; one `get_updates` poller.

## 3. Architecture overview

`talonx_ops.supervisor` → `run_talonx.py` (Original, MANDATORY) ∥ `talonx_signals.run`
(Experimental, OPTIONAL) ∥ `talonx_ingest.intelligence.service` (Intelligence, OPTIONAL) ∥
`dashboard_web.py` (`:8787`, OPTIONAL). Market data has a single publisher; Telegram has one
send path and one poller. See [`docs/CURRENT_ARCHITECTURE.md`](docs/CURRENT_ARCHITECTURE.md).

## 4. Runtime components

| package | role |
|---|---|
| `talonx_ingest` | market-data + SEC/news ingestion; `talonx_ingest/intelligence/` = Task 96 significance service |
| `talonx_quant` | technical scanner (frozen) |
| `talonx_brain` | LLM-grounded descriptive research report (context only) |
| `talonx_core` | decision engine |
| `talonx_dispatch` | official Telegram + audit trail + the one `get_updates` listener |
| `talonx_paper` | Original local paper engine (no broker) |
| `talonx_watchlist` | watchlist store (config, editable via `/admin/`) |
| `talonx_signals` | the internal-only Experimental lane |
| `talonx_ops` | supervisor, read model, market health, EOD store, official router, admin config, dashboard read model |
| `talonx_compare` | Original-vs-PIV comparison collector (dormant with PIV) |
| `talonx_piv` | opt-in Alpaca **PAPER-only** order-lifecycle validation harness |
| `talonx_backtest` | frozen-strategy replay + cost model (also used by `talonx_piv`) |

## 5. Original vs Experimental

| | Original | Experimental |
|---|---|---|
| thresholds (frozen) | `0.25 / 2 / 1.5` | `0.10 / 1 / 1.0` |
| external alerts | sole official/external lane | **never** |
| paper store | `paper_trading.db` | `experimental_paper.db` (isolated) |

`BEARISH` is informational. `SELL`/`EXIT` closes an existing long. Details:
[`docs/SAFETY_BOUNDARIES.md`](docs/SAFETY_BOUNDARIES.md).

## 6. Intelligence module

Descriptive only — see [`docs/INTELLIGENCE.md`](docs/INTELLIGENCE.md). The significance band is
"how much human attention this event deserves", never a prediction or a signal.

## 7. Paper trading model

Three completely separate simulated ledgers (Original / Experimental / PIV Alpaca PAPER), never
merged. See [`docs/PAPER_TRADING.md`](docs/PAPER_TRADING.md).

## 8. Dashboards

`:8787` primary (read-only) · `:8787/admin/` (loopback-only writes) · `:8760` intelligence deep
evidence (retained) · `:8770` legacy validation (`[COMPATIBILITY]`) · `:8501` Streamlit residual
(`[COMPATIBILITY]`). See [`docs/DASHBOARD.md`](docs/DASHBOARD.md),
[`docs/COMPATIBILITY.md`](docs/COMPATIBILITY.md).

## 9. Admin / config

`:8787/admin/` — 9 operational controls only (watchlist + paper $ amounts), confirm-required,
audited, strategy/execution keys permanently denied. [`docs/ADMIN.md`](docs/ADMIN.md).

## 10. Startup / status / shutdown

```powershell
.\scripts\start_talonx_supervised.ps1          # START
python -m talonx_ops.supervisor status         # STATUS
# Ctrl+C in the supervisor console             # controlled shutdown + EOD
```

See [`docs/OPERATIONS.md`](docs/OPERATIONS.md).

## 11. Backtesting & research

`python -m talonx_backtest --data examples\data\sample_AAPL_1m.csv --symbol AAPL --tz America/New_York --out results\sample`
replays the **frozen** live strategy. Datasets, methodology contract, and how to add a materially
new hypothesis safely: [`docs/BACKTESTING.md`](docs/BACKTESTING.md).

## 12. Data sources

Free only. Live: yfinance (+ optional Polygon WS); SEC EDGAR (`TALONX_SEC_USER_AGENT` required).
Research datasets: Alpaca **SIP** (account-entitled), Wikipedia point-in-time S&P membership.
`PAID_DATA_SPEND = £0`. Catalog: [`docs/DATA.md`](docs/DATA.md).

## 13. Safety boundaries

No shorts · no real capital (`talonx_piv` raises `PaperGuardError` on `real_capital=True`) · no
paid data by default · no runtime AI/ML on the trading path · frozen strategy settings ·
structural Experimental external-send block. [`docs/SAFETY_BOUNDARIES.md`](docs/SAFETY_BOUNDARIES.md).

## 14. Current limitations

- The Original strategy is highly selective and **unproven** — zero published signals over long
  stretches is expected behaviour, not a bug.
- The free intraday structural-long alpha research lane is **CLOSED** (no robust net edge found —
  [`docs/RESEARCH_STATUS.md`](docs/RESEARCH_STATUS.md)).
- One real-RTH live operational qualification (Task 103) is **pending**.
- `:8770` and `:8501` are retained for residual capability (see `docs/COMPATIBILITY.md`).

## 15. Repository layout

`talonx_*` packages (above) · `dashboard_web.py` + `dashboard_web_static/` (`:8787`) ·
`run_talonx.py` (Original orchestrator) · `scripts/` (start/stop; `start_talonx_supervised.ps1`
is primary) · `talonx_backtest/` + `research/scripts/` (backtest & research) · `tests/` ·
`examples/data/` (sample inputs) · `docs/` · `results/` (task artifacts — `task55…88` tracked,
`task9*+` local-only). Run everything from the repo root.

## 16. Development / testing

```powershell
python -m venv .venv ; .venv\Scripts\activate
pip install -r talonx_ingest\requirements.txt
copy .env.example .env         # set TALONX_SEC_USER_AGENT
.venv\Scripts\python.exe -m pytest tests/ -q
```

**Task journal** (added Task 118, 2026-09-11): any task that materially
changes running behavior, touches production state, or is itself a
research/audit deliverable should record an entry under
`docs/task_journal/entries/<date>_task<N>_<short-slug>/` (`request.md`,
`outcome.md`, `record.md` — see `docs/task_journal/TEMPLATE.md`) and add one
row to `docs/task_journal/TASK_INDEX.md`. This indexes and links the
existing `docs/audits/*`/`docs/research/*` evidence bundles rather than
replacing them — see `docs/task_journal/README.md` for the full convention.

## 17. Historical research conclusions

Tasks 93-95K + 97 + 101A/B: **no robust, cost-survivable free intraday structural-long alpha**
(intraday drift ≈ 5 bps ≈ round-trip cost across all regimes / 6.6 years). The product decision
(`95J`) reframed TalonX as a descriptive risk & event intelligence system. Full index:
[`docs/RESEARCH_STATUS.md`](docs/RESEARCH_STATUS.md); append-only history:
[`docs/research/TALONX_RESEARCH_LEDGER.md`](docs/research/TALONX_RESEARCH_LEDGER.md).

## 18. Roadmap / pending

- Run the pending Task 103 live operational qualification on a real trading day.
- After it passes: physically retire `:8770`.
- Build safe replacements for `:8501`'s destructive resets + long-term research views, then
  retire `:8501`.
- Backtest infrastructure remains available for a **materially new** hypothesis class (paid
  point-in-time consensus, options, non-price information) under a separate authorised mandate —
  not a parameter sweep of a closed lane.
