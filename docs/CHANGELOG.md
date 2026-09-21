# TalonX — Changelog

This is a **baseline**, not a reconstruction of every commit. The full chronological research
history is `docs/research/TALONX_RESEARCH_LEDGER.md`; per-task detail is under `results/task*/`.

## Current baseline — post-Task 105 (`research/talonx-strategy-validation`)

Repository hygiene + documentation reset. `docs/` re-authored to describe the current product
(this file, `CURRENT_ARCHITECTURE.md`, `OPERATIONS.md`, `DASHBOARD.md`, `ADMIN.md`,
`INTELLIGENCE.md`, `PAPER_TRADING.md`, `BACKTESTING.md`, `RESEARCH_STATUS.md`, `DATA.md`,
`SAFETY_BOUNDARIES.md`, `COMPATIBILITY.md`); root `README.md` rewritten. Pre-consolidation
`docs/*.md` classified (`docs/README.md`). No code behaviour changed; no research asset moved or
deleted. See `results/task105_repository_cleanup/final_report.md`.

## Task 104 — remaining P2 operational cleanup (`de7fe12`)

- `ABNORMAL_VOLUME` pre-market persistence — reuses Original's existing validated
  `volume_surge_ratio` + `premarket_volume_surge_ratio_threshold`, observed off the quant
  channels; no new feed.
- Dedicated loopback-only admin page `:8787/admin/` over the Task 102 `/admin/config` API.
- `:8501` audited → `8501_RETAINED_RESIDUAL`; `:8770` re-verified `DEPRECATED / COMPATIBILITY ONLY`.

## Task 103 — live operational qualification (pending)

Preflight passed; the session was **correctly blocked** (`TASK103_BLOCKED_MARKET_NOT_LIVE` — the
US market was closed). Re-run on a real trading day. Nothing about the architecture needs to
change first.

## Task 102 — operational finalization (`113b97f`)

- `PremarketStateStore` — durable pre-market projection written by the Experimental lane.
- `talonx_ops.admin_config` + loopback-gated `/admin/config` API — routine config editing moved
  off `:8501` (9 controls, denylisted, audited).
- `supervisor status` `answers` block; `scripts/start_talonx.ps1` marked LEGACY.

## Task 100 — architecture consolidation (`2fba02b` → `a657750`)

- **100A** — `AuthoritativeReadModel`: one truthful semantic status per domain (false-zero fix).
- **100B** — `talonx_ops.supervisor`: one supervision model; one Telegram `get_updates` owner;
  D/X/R/E resolver on that one listener; **structural** Experimental external-send boundary;
  `MarketHealth`; `EodReconciliationStore`; `OfficialExternalRouter`; independent Intelligence
  supervision.
- **100C** — `:8787` becomes the primary unified cockpit (6 sections); `:8770` →
  `DEPRECATED / NOT_STARTED_BY_DEFAULT`.

## Earlier

Task 96 (A-H) built the descriptive Risk & Event Intelligence product. Task 99 (A-L) restored and
hardened the live alert surface. Tasks 93-95K + 97 + 101A/B established that **no robust free
intraday structural-long alpha exists** and closed that research lane (`docs/RESEARCH_STATUS.md`).
Pre-90 tasks retired the FPRC_V1 / ORPB_V1 candidates. `talonx_piv` (Alpaca PAPER validation
harness) and `talonx_backtest` (frozen-strategy replay + cost model) date from that era and remain
in use.

## Frozen throughout

Original `min_atr_pct 0.25 / confluence_score_min 2 / min_risk_reward_ratio 1.5`; Experimental V1
`0.10 / 1 / 1.0`; Quant→Brain ordering; long-only; no shorts; no real capital; no paid data; no
runtime AI/ML.
