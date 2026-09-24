# Legacy manifest: repository and runtime relevance audit (S14, 2026-09-24)

This manifest was written with the Continuous Opportunity Engine (S14-01..S14-06). Evidence is in `docs/research/evidence/SESSION04_MISSED_OPPORTUNITY_FORENSIC.md`.

**Removal rule.** Nothing was deleted unless a replacement exists, references are proven absent, and V2 / shared utilities / historical reproducibility do not need it. Historical evidence is never deleted.

## Dispositions

| Disposition | Meaning |
|---|---|
| **KEEP_ACTIVE** | Part of today's active runtime. |
| **KEEP_SHARED_UTILITY** | Imported by active code (V2, ops, the opportunity engine), even though its original lane may be retired. |
| **MIGRATE** | Behaviour moved or changed in this work (see "done"). |
| **KEEP_HISTORICAL** | Kept for evidence and reproducibility. Not started by any active launcher. |
| **DEPRECATE** | Retired from active use. The code stays, but it refuses or is excluded from active startup. Removal is a later task, once the listed references are migrated. |
| **REMOVE** | Deleted or removed from the active path in this work. |
| **UNKNOWN** | Not proven either way. Listed so it is not forgotten. |

## Runtime processes and packages

| Component | Disposition | Evidence and reason |
|---|---|---|
| `run_talonx.py` (Original stack: yfinance feed → Quant → Brain → Core → Dispatch → Paper) | **KEEP_ACTIVE** | MANDATORY supervisor component. It hosts the **only** Telegram `getUpdates` poller (`/ping`, owner commands, reply-for-details) and official dispatch. It cannot be retired until that listener is migrated, which needs a separately authorised task. The CONTROL strategy's edge is unproven (Task 93), and it produced 0 signals on 09-24; retirement is an owner decision. |
| `talonx_quant` | **KEEP_ACTIVE** | Frozen Original V1 strategy files (fingerprinted). Also used by backtests. |
| `talonx_brain`, `talonx_core` | **KEEP_ACTIVE** | Subscribed to `talonx:signals:quant` on 09-24. They receive 0 when CONTROL gates everything, which is correct behaviour. |
| `talonx_dispatch` | **KEEP_ACTIVE** | Telegram listener, `/ping`, official dispatch. |
| `talonx_paper` | **KEEP_ACTIVE** | Original local paper ledger; EOD lane accounting reads it. |
| `talonx_ingest.market_data.yfinance_poll` | **KEEP_ACTIVE** (legacy feed) and **MIGRATE** (metrics) | The only price source for the Original CONTROL lane. V2, Research and Intelligence do not use it. Incident accounting was fixed (one upstream throttle = one incident). It will be deprecated together with Original. |
| `run_talonx.PreMarketPoller` (yfinance) | **KEEP_ACTIVE** | Pre-market price for the CONTROL lane only. |
| `talonx_ingest.intelligence.service` | **KEEP_ACTIVE** and **MIGRATE** | Stale-at-enqueue guard added and DIGEST_DISABLED made visible. The digest default is unchanged. |
| `talonx_v2` (release companion, gate, ledger) | **KEEP_ACTIVE** (frozen) | Strategy `e2acf6454789217e`, provider `ac5e51aa3599d6c9`, campaign V2-PAPER-RC1. Untouched. |
| `talonx_v2/bus.py` and `talonx:v2:{signal,decision,alert,trade}` | **KEEP_HISTORICAL** | Task 110/111 wire. Not imported by the release path (verified: no importer outside `bus.py`). |
| **`talonx_signals.run` (Experimental lane process)** | **DEPRECATE** (retired from active startup) | Its directional consumer never subscribed on 8 of 9 starts since 09-15, and silently lost every signal on those days. Superseded by the Continuous Opportunity Engine, and never sent externally. It now refuses a live start (exit 4) unless `--allow-retired`. |
| Supervisor `experimental` ComponentSpec | **REMOVE** | Removed from `default_talonx_components`. Health, the read model and the dashboard report **RETIRED**, never a failure. |
| `talonx_signals.{external_boundary, market_sessions, premarket_store, reply, config}` | **KEEP_SHARED_UTILITY** | Imported by `talonx_ops.official_dispatch`, `paper_performance`, `prospective.checkpoint/preflight`, `dashboard_read` and `run_talonx` (D/X/R/E resolver). The external-send boundary is still enforced. |
| `talonx_signals.{directional, dispatcher, experimental_paper, telemetry, intelligence_bridge, premarket, relaxed_profile, dashboard, renderers, alert_store, schemas, eod_attribution}` | **KEEP_HISTORICAL** | Used only by the retired lane and its regression tests. Removing them needs test and doc migration first. |
| Experimental `:8770` dashboard | **DEPRECATE** | It was served only by the retired lane process (already COMPATIBILITY-only since Task 102). |
| `talonx_premarket` package | **KEEP_SHARED_UTILITY**, with `run` **KEEP_HISTORICAL** | features / scoring / alerts / catalysts / outcomes / alpaca_data / universe are imported unchanged by `talonx_opportunity`. The pre-market-only `run` canary is superseded but stays for replay and history of `PREMARKET_RESEARCH_V1` (`62ba413daf85e674`). |
| `talonx_opportunity` | **KEEP_ACTIVE** (new) | Continuous engine, run as its own process set (`python -m talonx_opportunity up`). |
| `talonx_piv`, `talonx:piv:*`, `talonx:gateway:alpaca:*` | **KEEP_HISTORICAL** | Opt-in PIV lane (Task 92). Not started by any active launcher. |
| `talonx_compare` | **KEEP_HISTORICAL** | Task 83 passive comparison layer. Not supervised. |
| `talonx_watchlist` | **KEEP_SHARED_UTILITY** | `watchlist.db` (Original watchlist and earnings radar). |
| `talonx_backtest` | **KEEP_SHARED_UTILITY** | Reproducibility fingerprints and research. |
| `dashboard_web.py` (`:8787`) | **KEEP_ACTIVE** and **MIGRATE** | New Opportunity Engine tab. The Validation tab is labelled as the retired Experimental view. |
| `dashboard.py` (Streamlit `:8501`) | **KEEP_HISTORICAL** | `8501_RETAINED_RESIDUAL` (Task 104 decision, unchanged). Not supervised. |

## Redis channels

Checked against the actual 09-24 subscription log lines.

| Channel | Disposition | Notes |
|---|---|---|
| `talonx:market:stream`, `talonx:signals:quant`, `talonx:quant:rejected`, `talonx:reports:brain`, `talonx:alerts:dispatch`, `talonx:paper:trades`, `talonx:alerts:longterm`, `talonx:paper:trades:longterm`, `talonx:reports:longterm`, `talonx:signals:fundamental`, `talonx:filings:events`, `talonx:fundamentals:events`, `talonx:news:events` | **KEEP_ACTIVE** | Original chain. Every one had its intended subscriber on 09-24. |
| `talonx:exp:signals:quant`, `talonx:exp:quant:rejected`, `talonx:exp:paper:trades`, `talonx:exp:alerts` | **DEPRECATE** | Their only producer and consumer, the Experimental lane, is retired. No active startup publishes to or subscribes to them (tested). |
| `talonx:v2:*`, `talonx:piv:*`, `talonx:gateway:alpaca:*`, `talonx:compare` | **KEEP_HISTORICAL** | Not in any active startup path. |

## Metrics and operator surfaces

| Item | Disposition | Change |
|---|---|---|
| Shared `metrics:{date}:quant:*` (CONTROL and Experimental both wrote it) | **MIGRATE** | With the Experimental lane retired, CONTROL is the only writer. `/ping` labels it CONTROL and no longer infers "never reached Brain". |
| `/ping` provider failure counts | **MIGRATE** | Upstream incidents (throttle or hard) are shown separately from isolated per-symbol failures. |
| `/ping` Opportunity Engine line | new | Read-only via `talonx_ops.opportunity_read`. |
| Intelligence queue breakdown | **MIGRATE** | Shows `DIGEST: DIGEST_DISABLED, N pending will not be sent`. |
| Premarket tab "Premarket watch" (43 names, written by the retired lane into `premarket_state.db`) | **DEPRECATE** | Shown with `producer_retired` and `superseded_by: opportunity_engine`. Its rows are historical. |

## Scripts, schedulers and config

| Item | Disposition | Notes |
|---|---|---|
| `scripts/start_talonx_supervised.ps1` | **KEEP_ACTIVE** | Comment updated: Experimental retired; the opportunity engine is a separate process set. |
| `scripts/start_talonx.ps1`, `scripts/stop_talonx.ps1` | **DEPRECATE** | Marked LEGACY since Task 102. Left unchanged. |
| `scripts/register_scheduled_tasks.ps1` | **DEPRECATE** | Registers Windows tasks that launch the legacy `start_talonx.ps1`. **No `TalonX*` scheduled task is registered on the host** (verified 2026-09-24). |
| `scripts/start_dashboard_web.ps1`, `stop_dashboard_web.ps1` | **KEEP_ACTIVE** | Standalone dashboard utilities. |
| `docker-compose.yaml` (Redis) | **KEEP_ACTIVE** | Needed by the Original chain. |
| `.env` / `.env.example` `TALONX_YF_*` | **KEEP_ACTIVE** | Legacy feed tuning. |
| `TALONX_EXPERIMENTAL_EXTERNAL_SEND_OVERRIDE` | **KEEP_SHARED_UTILITY** | The boundary is still enforced, and the close assert checks that it is inactive. |
| `TALONX_NOTIFY_RESEARCH_*`, `TALONX_OPP_*`, `TALONX_INTEL_DELIVER_DIGEST_ENABLED` | **KEEP_ACTIVE** | Documented in `.env.example`; opt-in only. |
| The 43-stock watchlist assumption | **KEEP_ACTIVE** (Original only) | The continuous engine has no 43-name assumption; it scans the broad eligible universe (about 5.6k names). |
| Session gates in `talonx_quant/session.py` (US/UK) | **KEEP_ACTIVE** (Original only, fingerprinted) | The continuous engine uses its own XNYS phase model and never a global session gate. |
| Root `send_test_signal.py`, `send_test_report_pair.py`, `generate_eod_report.py` | **UNKNOWN** | Manual utilities. No active launcher references them. Kept. |
| `scripts/*task25*`, `*task56*`, `*task83*`, `run_historical_regimes.py`, `download_historical_1m.py`, `research/`, `archive/`, `examples/` | **KEEP_HISTORICAL** | Evidence reproduction. |

## Stores

| Store | Disposition |
|---|---|
| `v2_release_rc1.db`, `v2_release_rc1_notifications.db` | **KEEP_ACTIVE** (protected; the research lane refuses to open them) |
| `notifications.db` (legacy shared outbox), `v2_lane.db` (legacy $300k campaign) | **KEEP_HISTORICAL** (protected) |
| `~/.talonx/experimental/{exp_alerts, experimental_paper, forward_outcomes, exp_quant}.db`, `premarket/premarket_state.db` | **KEEP_HISTORICAL** (EOD lane accounting reads them; evidence) |
| `results/premarket_research/**` | **KEEP_HISTORICAL** (V1 canary evidence) |
| `results/opportunity/**` | **KEEP_ACTIVE** (new; gitignored) |

## Verification

- `tests/test_legacy_cleanup_continuous.py`: the retired lane is absent from active startup, refuses a live start, and reports RETIRED without degrading health; `/ping` metrics are un-mixed; yfinance incident semantics; Intelligence guard; DIGEST_DISABLED visibility.
- `tests/test_continuous_opportunity_engine.py::test_frozen_release_does_not_import_the_opportunity_lane`.
- `tests/test_continuous_opportunity_engine.py::test_this_branch_still_passes_the_v2_frozen_release_check`.
- A search for `talonx_signals.run` in active code (verified) returns only intentional references:
  - retirement notes in `talonx_ops/supervisor.py` and `scripts/start_talonx_supervised.ps1`;
  - process-detection markers, so a leftover or manual copy of the retired process is still detected and cleaned up: `authoritative_read_model.py` (`RUNNING_DESPITE_RETIREMENT`), `prospective/preflight.py` (stale-process check) and `prospective/proc.py` (residual-process cleanup);
  - the allowlist entry in `prospective/preflight.py`;
  - the lane's own package docstrings;
  - historical docs and tests.
