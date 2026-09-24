# TalonX — Current Architecture

*The single authoritative description of TalonX as it stands after Task 104 (SHA `de7fe12`), updated for S14 (2026-09-24):
Continuous Opportunity Engine added, Experimental lane RETIRED from active startup.*
Older architecture notes under `docs/` describe the pre-consolidation six-module layout and are
superseded by this document — see `docs/README.md` for their status.

TalonX is a **descriptive, human-in-the-loop event-driven trading & risk-intelligence system**.
It ingests live US-equity market data and SEC filings, runs one frozen selective intraday
strategy (Original), continuously discovers broad-universe research opportunities across every
supported market phase (Continuous Opportunity Engine, S14), produces deterministic event/risk
intelligence, runs the frozen V2 paper strategy, and surfaces everything on a single read-only
operator cockpit. **It makes no profitability claim, executes no real capital, and takes no short
positions.**

## Boundary legend

`[OFFICIAL]` external-eligible · `[INTERNAL]` never leaves the process · `[READ-ONLY]` ·
`[MUTABLE-ADMIN]` local-only writes · `[PAPER-ONLY]` simulated ledger, no broker ·
`[COMPATIBILITY]` deprecated, kept for rollback

## Runtime supervision

```
                       talonx_ops.supervisor            [READ-ONLY launcher]
                       start · health · restart · stop
                       `python -m talonx_ops.supervisor run|status`
          ┌──────────────────┬──────────────────────┬──────────────────┐
          ▼                  ▼                      ▼                  ▼
   ORIGINAL CONTROL   INTELLIGENCE SERVICE     V2 COMPANION (opt)   :8787 COCKPIT
   run_talonx.py      -m talonx_ingest.        -m talonx_v2.run     dashboard_web.py
   [OFFICIAL]         intelligence.service     [PAPER-ONLY]         [READ-ONLY]
   MANDATORY          [READ-ONLY] OPTIONAL     OPTIONAL             OPTIONAL

   SEPARATE PROCESS SET (research lane, its own launcher, independently restartable components):
   python -m talonx_opportunity up   ingestion · discovery · evaluator:{INTRADAY,SAME_DAY,SHORT_TERM,LONG_TERM}
                                     · notifier · outcomes · reporting            [INTERNAL / RESEARCH]
```

- Original crashing is fatal to runtime readiness; Intelligence / V2 / dashboard crashing is
  `DEGRADED` only — Original keeps running (Task 100B failure-isolation matrix).
- The Experimental lane (`talonx_signals.run`) is **RETIRED** from active startup (S14): reported as
  `RETIRED`, never as a failure; it refuses a live start unless `--allow-retired`.
- Bounded run for the pending live qualification:
  `python -m talonx_ops.supervisor run --tick 15 --max-ticks 240` (~60 min, self-stops).

## Market data → authoritative market path

- Single publisher: `talonx_ingest.market_data` inside `run_talonx.py` → Redis
  `talonx:market:stream` (BAR/TRADE/QUOTE events carrying `volume`).
- Pre-market: `run_talonx.py`'s `PreMarketPoller` is the sole authoritative pre-market price/
  volume source; the continuous yfinance poller suppresses its own BAR publication in the
  pre-market window to avoid a second disagreeing source.
- **One authoritative health accessor**: `talonx_ops.market_health.MarketHealth` — feed state
  (`HEALTHY`/`IDLE`/`STALE`/`DISCONNECTED`/`UNKNOWN`), last-event age, cadence, configured vs
  selected symbols, coverage, provider + Redis failure/reconnect counters.
  `AuthoritativeReadModel.market()` consumes it (does not re-derive).

## Original Control `[OFFICIAL]`

`talonx_quant.consumer.QuantScanner` → `talonx_brain.consumer.ResearchAgent` →
`talonx_core.consumer.DecisionEngine` → `talonx_dispatch.consumer.DispatchAgent` →
`talonx_paper.consumer.PaperTradingEngine`.

- **Frozen thresholds**: `min_atr_pct = 0.25`, `confluence_score_min = 2`,
  `min_risk_reward_ratio = 1.5`. Quant→Brain ordering is frozen.
- Long-only. `SELL` / `EXIT` closes an existing long. `BEARISH` is informational only.
- Official alert eligibility is decided by Original's own unchanged policy; the one
  routing-decision authority is `talonx_ops.official_dispatch.OfficialExternalRouter`
  (experimental families → `eligible = False`, structurally).
- Original local paper (`paper_trading.db`) is a `[PAPER-ONLY]` simulated ledger — no broker,
  no network.

## Continuous Opportunity Engine `[INTERNAL / RESEARCH]` (S14)

`talonx_opportunity` — continuous, phase-aware, **uncapped** broad-universe discovery (~5.6k eligible names).
Operator runbook: `docs/runbooks/CONTINUOUS_ENGINE.md`.

- Phases OVERNIGHT / PREMARKET / REGULAR / AFTER_HOURS (+ CLOSED) on the XNYS calendar; market phase changes
  data source, liquidity context and execution eligibility but never globally suspends discovery. Provider
  capability per phase is explicit: Alpaca SIP (15-min delayed, consolidated) for PREMARKET/REGULAR/AFTER_HOURS;
  OVERNIGHT fails closed (SIP has no overnight bars; BOATS single-venue recorded, disabled).
- Scoring/classification = frozen `PREMARKET_RESEARCH_V1` (`62ba413daf85e674`) embedded unchanged in the versioned
  `CONTINUOUS_RESEARCH_V1`; one identity per symbol/direction continues across phase boundaries.
- **Candidate detection and durable persistence are independent from notification limits.** The only attention
  budget is `LAB_NOTIFY_POLICY_V1` in the notification worker (Lab/RESEARCH destination, double opt-in).
- Each component is its own process and single writer of its own store; every start records a deployment
  boundary (classification + `affects_*`); reports segment statistics at material boundaries.
- Horizon evaluators (INTRADAY / SAME_DAY / SHORT_TERM / LONG_TERM) consume the same event stream via their own
  cursors; BUY/SELL require an authorizing strategy (none for the research lane). V2 remains the separate,
  specialised multi-session paper strategy.
- `talonx_premarket` (pre-market-only V1 canary) is SUPERSEDED for live use and kept for replay/history.

## Experimental Shadow `[INTERNAL]` — RETIRED from active startup (S14, 2026-09-24)

*Historical description kept for reproduction. Its directional consumer silently failed to subscribe on 8 of 9
starts since 2026-09-15 (Session-04 forensic §6); its research role is superseded by the Continuous Opportunity
Engine. Shared utilities (`external_boundary`, `market_sessions`, `premarket_store`, `reply`) remain in use.*

`talonx_signals.run.ExperimentalLane` — own `QuantScanner` with the frozen relaxed profile
`RELAXED_OVERRIDES` = `min_atr_pct 0.10 / confluence_score_min 1 / min_risk_reward_ratio 1.0`.

- Produces internal directional alerts (`BULLISH`/`BEARISH`), `WOULD_PASS` / `WOULD_REJECT`
  gate labels, Experimental BUY/EXIT into `experimental_paper.db`, and forward outcomes
  (MFE/MAE/+30m/+60m/EOD/+1D, Task 99G) into `forward_outcomes.db`.
- Persists the pre-market surface into `premarket/premarket_state.db` (Task 102): earnings radar,
  gaps, watch candidates, event context, and `ABNORMAL_VOLUME` (Task 104 — reuses Original's own
  validated `volume_surge_ratio` observed off the quant channels; informational only).
- **No external Telegram.** The `talonx_signals.external_boundary` module makes a real
  Experimental send require three independent conditions (flag + real transport +
  `TALONX_EXPERIMENTAL_EXTERNAL_SEND_OVERRIDE=i-understand`), or it raises. Default posture:
  structurally impossible.

## Intelligence `[READ-ONLY, descriptive]`

`talonx_ingest.intelligence.service` — polls SEC EDGAR (8-K item taxonomy, 10-Q/10-K, Form 3/4/5),
runs deterministic filing-comparison ("what changed"), insider aggregation, and an explainable
**Information Significance** band (`LOW`/`MEDIUM`/`HIGH`/`CRITICAL`) with **no forward-return
input and no direction** (AST-enforced). Writes `ingestion_ledger.db`. 24/7 freshness-driven
cadence (180/300/900 s). Independent of Original — a failure never affects the trading path.

## Ops `[READ-ONLY]`

- `talonx_ops.authoritative_read_model.AuthoritativeReadModel` — one truthful semantic status per
  domain (`ACTIVE` / `ZERO_ACTIVITY` / `NO_ACTIVE_PRODUCER` / `SUPERSEDED` / `STALE` /
  `UNKNOWN`) so a bare `0` is never misread.
- `talonx_ops.eod_reconciliation.EodReconciliationStore` — durable per-session EOD row
  (`eod_reconciliation.db`), read-only broker checks only, PIV = `NOT_CHECKED` unless an
  explicit reader is injected (never fabricated `0`).
- `talonx_ops.dashboard_read.DashboardReadModel` — assembles the `:8787` sections from the
  above (incl. the S14 Opportunity Engine section via `talonx_ops.opportunity_read`, which reads
  the research-lane stores `?mode=ro` without importing the lane). Physically read-only.

## UI

| surface | port | tag |
|---|---|---|
| **primary cockpit** — Overview / Opportunity Engine / Premarket / Original Quant / Active V2 / Broad Discovery / Validation (retired Experimental) / Intelligence / Paper·EOD + legacy Live/Original/PIV/Compare/Domain-status tabs | `:8787` `dashboard_web.py` | `[READ-ONLY]` |
| **local admin** — 9 operational controls (watchlist + paper $ amounts), confirm-required, audited, strategy/execution keys denied | `:8787/admin/` | `[MUTABLE-ADMIN]` loopback-only (403 otherwise) |
| **intelligence deep evidence** | `:8760` `python -m talonx_ingest.intelligence.dashboard` | `[READ-ONLY]` retained |
| **legacy validation dashboard** | `:8770` `python -m talonx_signals.run` | DEPRECATED — its only host (the Experimental lane) is RETIRED (S14) |
| **Streamlit** — destructive paper resets + starting-balance + long-term research views | `:8501` `talonx_dispatch/app.py` | `[COMPATIBILITY]` residual, retained |

## Telegram

- **One official external-send path**: `talonx_dispatch.telegram_client.TelegramClient` (one
  transport class), Original only.
- **One `get_updates` poller**: `TelegramReplyListener` inside `run_talonx.py`'s `DispatchAgent`.
- **D/X/R/E resolver**: the Experimental reply-for-details bridge is registered on that ONE
  listener via `extra_resolvers`, reading `exp_alerts.db` through a read-only (`?mode=ro`) handle
  — no second poller, no Experimental sender.
- Task 99H Markdown/entity escaping is preserved for every rendered alert.
- **Research (Lab bot, `RESEARCH` destination)**: only the research lanes' notification workers enqueue here,
  to their own outbox; never Signal/Sentinel, never a `TRADE_EVENT` (`docs/NOTIFICATION_CONTRACT.md`).

## PIV `[PAPER-ONLY, opt-in]`

`talonx_piv` — a separate Alpaca **PAPER-only** order-lifecycle validation harness for the
already-implemented strategy. Not one of the runtime components, not started by the supervisor or
the dashboard, structurally cannot route real capital (`PaperGuardError` on `real_capital=True`).
Never surfaced as Original local paper.

## PII / secrets

`.env` is gitignored; only `.env.example` is tracked. No API keys or tokens in the repo, in
`/admin/`, or in the audit log. `TALONX_SEC_USER_AGENT` (an email string SEC requires) is the one
mandatory config value.
