# TalonX — Dashboards

## `:8787` — primary unified cockpit (`dashboard_web.py`)

Read-only. `python dashboard_web.py` (default `--host localhost --port 8787`), or started by the
supervisor. Six primary sections + legacy tabs.

| section | shows | authoritative source |
|---|---|---|
| **OVERVIEW** | runtime health (overall / original / experimental / intelligence / telegram send+receive / forward outcomes / EOD); market health (feed state, last-event age, cadence, configured/selected symbols, coverage, provider + Redis failure/reconnect counters); alert health (official generated/sent/failed/held; Experimental external boundary = `BLOCKED`, live sends = 0); a **source-status** table with the semantic state per domain (the false-zero guard) | `DashboardReadModel.overview()` over `AuthoritativeReadModel` + `MarketHealth` |
| **PREMARKET** | earnings radar (T-7/T-2/T-0), persisted gaps / bullish-bearish watch / `ABNORMAL_VOLUME` / coverage (from `premarket_state.db`), event context (overnight SEC events) | `watchlist.db`, `experimental/premarket/premarket_state.db`, `ingestion_ledger.db` |
| **ORIGINAL QUANT** | the funnel: bars observed, suppressions by reason + %, published Quant signals, Quant→Brain handoffs, Brain reports, official alerts, local paper trades. `quant_state = "ACTIVE / NO SIGNALS PASSED"` when published = 0 and suppressions > 0. `brain_state = "ACTIVE / NO INPUT"` when Quant published nothing. | `quant.db`, `brain.db`, `dispatch_audit.db`, `paper_trading.db` |
| **VALIDATION** | mandatory `INTERNAL VALIDATION — NOT OFFICIAL TRADING SIGNALS` banner; `external_boundary = BLOCKED`, `live_external_sends = 0`; frozen profile 0.10/1/1.0; directional alerts (bounded), WOULD_PASS/WOULD_REJECT, reject reasons, Experimental trades; forward outcomes (+30m/+60m/EOD/+1D, MFE, MAE, pending); Original-vs-Experimental funnel comparison ("validation-only, not a profitability claim") | `experimental/{exp_alerts,experimental_paper,forward_outcomes}.db` |
| **INTELLIGENCE** | descriptive summary: service status, freshness, latest events, significance-ranked (band + score), counts; deep links to `:8760`. No forward-return or directional claim. | `ingestion_ledger.db` via `AuthoritativeReadModel.intelligence()` |
| **PAPER / EOD** | three **separate** panels — Original local paper / Experimental validation paper (internal, simulated) / PIV Alpaca PAPER (`positions`/`orders` = `NOT_CHECKED`) — never one merged number; plus the EOD reconciliation row | `paper_trading.db`, `experimental_paper.db`, `eod_reconciliation.db` |

Legacy tabs (kept): **Live pipeline** (Redis channel counters + bar-buffer warm-up), **Original
(raw)** / **PIV** / **Compare** (Task 83 `talonx_compare` views), **Domain status** (the Task
100A `AuthoritativeReadModel.snapshot()` table).

Endpoints: `GET /` (page) · `GET /ws` (live WS for the Live-pipeline tab) · `GET /api/sections` ·
`GET /api/section/{name}` · `GET /views/{original,piv,compare}` · `GET /piv/status`. All GET,
read-only, TTL-cached. Responsive (single column < 640 px, wide tables scroll their own
container).

### False-zero semantics

Every section exposes a semantic status. `ACTIVE` = live + genuine activity; `ZERO_ACTIVITY` =
live + a real zero; `NO_ACTIVE_PRODUCER` = the producing process isn't running; `STALE` = old
data / poll recency; `SUPERSEDED` = a newer source owns this domain; `UNKNOWN` = store missing.
An operator never has to read raw Redis to know whether a `0` is meaningful.

## `:8787/admin/` — local admin

See `docs/ADMIN.md`.

## `:8760` — intelligence deep evidence (retained)

`python -m talonx_ingest.intelligence.dashboard --port 8760`. Full forensic viewer: Today feed,
Watchlist attention ranking, Company pages, Filings + comparison drill-down, Evidence / claim
policy page. The `:8787` INTELLIGENCE section summarises and deep-links here rather than
duplicating it.

## `:8770` — legacy validation dashboard `[COMPATIBILITY]`

Embedded in `python -m talonx_signals.run`. **Not started by the supervisor.** `:8787`'s
VALIDATION section reached 5/5 offline feature parity (Task 100C). Physical removal is pending one
real live row-level parity session (Task 103). See `docs/COMPATIBILITY.md`.

## `:8501` — Streamlit `[COMPATIBILITY, residual]`

`python -m streamlit run talonx_dispatch/app.py`. Retained only for: destructive intraday +
long-term paper-portfolio resets, starting-balance edits, and the long-term valuation/research
views. Routine config editing has moved to `/admin/`. See `docs/COMPATIBILITY.md`.
