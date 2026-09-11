# Task 71S-R1 -- Remaining Stabilisation Issues (NOT implemented in this task)

Per this task's explicit scope ("Do not begin EOD orchestration,
dashboards, Gemini, alerts/shadow work, long-only implementation or new
alpha work"), the following are retained for later, separately-scoped
tasks:

1. **No live suitability threshold was invented.** Per Phase B's own
   instruction ("Do not invent a suitability threshold... If no defensible
   threshold exists without strategy research, expose coverage metrics and
   remain fail-closed rather than guessing"), `FreshnessTracker` exposes
   `coverage_ratio`/`fresh_bar_count`/`quiet_tick_count` as OBSERVABLE
   metrics only -- no new auto-exclusion rule based on them exists. A
   future task, informed by actual strategy-side research into what
   coverage level a minute-driven decision genuinely needs, could add one;
   this task deliberately does not guess at that number.
2. **`EventBus._key`'s cross-symbol Telegram-dedup collision** (see
   `notification_dedup_evidence.json`) is a pre-existing characteristic of
   `talonx_piv/events.py` shared by many event types, not introduced by
   this task. This task's own new event avoids adding a NEW instance of it
   (by embedding the symbol in `reason`), but does not fix the underlying
   key design, which would require auditing every other event type's
   Telegram-dedup expectations -- out of scope here.
3. **Dashboard/EOD-report surfacing of coverage metrics** -- `freshness_report.json`
   now carries per-symbol coverage + session identity, but no dashboard or
   EOD report template has been updated to render it (explicitly out of
   scope: "Do not begin... dashboards... work").
4. **Cross-process/disk-persisted freshness state** -- unchanged from Task
   71S's own carried-forward item: `FreshnessTracker` (including the new
   rolling coverage counters) remains in-memory only; a process restart
   mid-session does not currently restore prior coverage counts.
5. **Premarket IEX coverage's own implications** -- this task's Phase B
   found premarket (04:00-09:29 ET) IEX-bar coverage is near-zero (0.0%-2.7%)
   for essentially the ENTIRE 35-symbol universe, including AAPL. This is
   presented as observed fact (see `iex_coverage_by_symbol.csv`) with a
   plausible, evidence-consistent explanation (Alpaca's `/v2/stocks/bars/latest`
   endpoint most likely omits a symbol entirely, rather than echoing a
   stale bar, until its first current-session trade prints) -- but this
   explanation was NOT independently verified by reconstructing the exact
   live tick sequence (that would require re-running a live session, which
   this task's constraints prohibit). A future task could verify this
   directly against Alpaca's own live-endpoint documentation or a
   controlled read-only smoke test of `/v2/stocks/bars/latest` itself
   (not just the historical `/v2/stocks/{symbol}/bars` endpoint used
   throughout this task).
6. **Trade-level (tick) data was never queried, by design.** Phase A's
   correction (`NO_IEX_BAR_OBSERVED`) is deliberately honest about this
   limitation rather than closing the gap by adding a trades-endpoint
   call -- doing so would be a meaningfully larger change (a new read-only
   endpoint integration) than this task's "smallest safe correction"
   scope, and the aggregate-bar evidence already gathered is internally
   self-consistent (see Phase B's coverage analysis) without it.
7. **EOD orchestration, Gemini, alerts/shadow work, long-only
   implementation, new alpha work** -- explicitly out of scope per this
   task's own instruction.
8. **`REQUIRED_1M_BARS`/`min_bars_required` decoupling** (carried over from
   Task 70S, still unresolved, still requires touching
   `talonx_quant/config.py`, still out of scope).
