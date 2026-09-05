# TalonX — Data Catalog

No secrets or tokens appear here or anywhere in the repo (`.env` is gitignored; only
`.env.example` is tracked).

## Live market data (runtime)

| dataset | source | coverage | frequency | symbols | purpose | location |
|---|---|---|---|---|---|---|
| live BAR/TRADE/QUOTE stream | yfinance polling + (optional) Polygon WS | rolling live | ~30-60 s poll / 1-min AM bars | watchlist | feeds Original + Experimental scanners | Redis `talonx:market:stream` (ephemeral) |
| pre-market quotes | `run_talonx.py` `PreMarketPoller` (`fetch_quotes_vectorized`) | 04:00-09:30 ET | ~5-min | watchlist | authoritative pre-market price/volume | Redis stream + `premarket_state.db` |
| bar buffers | `talonx_quant` `RollingBarBuffer` | current warm-up window (120×1m / 200×15m) | per bar | watchlist | indicator warm-up; **rolling, not a history store** | `~/.talonx/quant.db` `bar_buffer` |

## SEC / intelligence data (runtime)

| dataset | source | coverage | purpose | location |
|---|---|---|---|---|
| 8-K / 10-Q / 10-K filings + item taxonomy | SEC EDGAR (`acceptanceDateTime`, XBRL first-filed) | watchlist, live | event detection + "what changed" | `~/.talonx/ingestion_ledger.db` |
| Form 3/4/5 insider transactions | SEC EDGAR bulk TSV + ownership XML | watchlist, live | insider aggregation | same |
| deterministic significance | computed (`information-significance-v1`) | per event | human-attention band | same (`event_significance`) |

Requires `TALONX_SEC_USER_AGENT` (an email string SEC's fair-access policy mandates). No paid
feed.

## Live SQLite stores (`%USERPROFILE%\.talonx\`, gitignored)

`quant.db` (funnel, bar buffers) · `brain.db` (report counts) · `dispatch_audit.db` (official
alerts) · `core_state.db` · `paper_trading.db` (Original paper) · `watchlist.db` (config —
editable via `/admin/`) · `ingestion_ledger.db` (intelligence) · `eod_reconciliation.db` ·
`admin/config_audit.db` · `experimental/{exp_alerts,experimental_paper,forward_outcomes,exp_quant}.db`
· `experimental/premarket/premarket_state.db` · `intelligence/{service.heartbeat.json,service.lock,service.metrics.json}`.

## Research / backtest datasets (local-only, gitignored)

See `results/task105_repository_cleanup/backtest_preservation_manifest.md` §3 for the full table.
Summary:

| dataset | source | coverage | freq | symbols | location (local) |
|---|---|---|---|---|---|
| Task 93 canonical | Alpaca **SIP** | 2025-01→2026-08 | 1-min | 35 | `results/task93_alpha_foundation/` (~611 MB) |
| Task 95A expanded regime | Alpaca **SIP** | 2020→2026 | 1-min + features | 35 | `results/task95a_regime_expansion/` (~5 GB) |
| Task 95B swing daily | 95A source, split-adj | 2020→2026 | daily (51,922 bars) | 35 | `results/task95b_swing_foundation/` |
| Task 95F point-in-time universe | Wikipedia MediaWiki API (£0) | 2019→2026 | change events | 644 unique | `results/task95f_historical_universe/` |
| Task 95G broad panel | `fja05680/sp500` + Alpaca SIP `adjustment=all` | 2019→2026 | daily (1.06M rows) | 620 | `results/task95g_broad_cross_sectional/` |
| Task 95C/D/H/I event datasets | SEC EDGAR | 2020→2026 | per-event | 35 | `results/task95c_*` / `95d_*` / `95h_*` / `95i_*` |
| Task 101A/B backtest evidence | derived from 95A | 2020→2026 | per-candidate | 35 | `results/task101a_event_first/` (~123 MB), `results/task101b_trend_gate/` (~34 MB) |

Each dataset dir carries a `*_manifest.json` (source, window, symbol list, content hash).
`PAID_DATA_SPEND = £0` for the entire research programme.

## Tracked research evidence (git)

`results/task55…task88/**` — Task 55-88 diagnostic/PIV/qualification artifacts (committed before
`/results/` was gitignored). Referenced by `research/scripts/*` and by `talonx_piv` /
`talonx_compare` runtime path defaults — **do not move**.

## Not data

`examples/data/sample_*_1m.csv` are checked-in **sample INPUTS** for the backtest quick-start and
tests — not generated output.
