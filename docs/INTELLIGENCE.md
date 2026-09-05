# TalonX — Risk & Event Intelligence

A **descriptive, deterministic, human-in-the-loop** layer over SEC data. It detects, classifies,
causally timestamps, and explains filings / earnings / insider activity for the watchlist and
ranks them for human attention. **It carries no forward-return input and no direction — it is not
predictive and not a signal.**

## Package

`talonx_ingest/intelligence/` — an isolated subpackage. AST-enforced tests fail the build if any
significance code imports `talonx_quant` / `talonx_core.decision` / `talonx_paper` / `talonx_piv`
or a backtest module.

| subpackage | what it does |
|---|---|
| `intelligence/` (domain) | `TextEvent` / `AlertCard` frozen pydantic models; deterministic `event_id` / `card_id` / `source_hash`; 8-K item taxonomy → event type; BMO/RTH/AMC/NON_TRADING_DAY sessions via `exchange_calendars`; `EventStore` (additive tables in `ingestion_ledger.db`) — Task 96A |
| `intelligence/comparison/` | deterministic "what changed" for 10-Q/10-K: prior-filing match, HTML normalise, section find (RF / MD&A / Liquidity), whole + per-section diff (`1 − SequenceMatcher.quick_ratio()`), frozen keyword lexicon (counts only), first-filed XBRL YoY/QoQ deltas; frozen material-change thresholds; `FilingComparisonStore` — Task 96C |
| `intelligence/insider/` | SEC Form 3/4/5: P/S = the only open-market discretionary class; content-addressed `transaction_id` (bulk TSV ↔ ownership XML converge); rolling P/S net over 10/30/90 calendar days; officer/director subsets; `InsiderStore` — Task 96D |
| `intelligence/significance/` | frozen ruleset `information-significance-v1`: additive integer fixed-point score → clamp `[0,12]` → band `LOW`/`MEDIUM`/`HIGH`/`CRITICAL`; structural floors (CRITICAL needs ≥ 5 substantive pts / ≥ 2 families); every non-zero rule hit = one reason, `Σ reason.points == score`; XBRL uses `abs()` (direction-neutral), insider buy == sell; `input_fingerprint` excludes wall-clock; `SignificanceStore` — Task 96E |
| `intelligence/service/` | the continuous poller: `python -m talonx_ingest.intelligence.service poll --with-backfill`. Singleton-locked, 24/7, freshness-driven cadence (FRESH → 180 s, STALE → 300 s, DOWN → 900 s), never gated on market hours. `SingletonLock.is_stale()` lets the supervisor report a crashed instance without `--force-lock`. |
| `intelligence/dashboard/` | the `:8760` deep-evidence viewer (Today / Watchlist / Company / Filings / Evidence pages), claim-safety scanned |

## Delivery

96F Telegram delivery renders ranked, band-tagged, evidenced `AlertCard`s via the one official
dispatch path. It is **dormant / dry-run** by default (`--send` double-gated). Approved Task 96
intelligence/RADAR families may join the one official external path **only where a locked contract
already authorises**; the router (`talonx_ops.official_dispatch.OfficialExternalRouter`) is the
single decision point.

## Supervision

Run as an independent process under `talonx_ops.supervisor` (Task 100B Option D — a thin external
supervisor, unbounded restart with capped backoff). A `DEGRADED` / `FAILED` Intelligence service
never affects Original or Experimental. If there is simply no new SEC event, `ZERO_ACTIVITY` is
the correct state — not a defect.

## Wording rules (CI-linted)

No predictive language. No forward-return or probability field. No trade direction. The band
means "how much human attention this deserves", nothing more.
