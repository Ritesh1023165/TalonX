# Task 124 — bounded intraday data feasibility and next economic decision

Reads and carries forward `docs/research/TASK123_OVERNIGHT_ATTENTION_RESULTS.md`
unchanged (see §0). Investigates whether existing free data access can
supply the missing intraday coverage that limited Track B's actionable
test to N=31. No strategy return is computed in this task.

## Part 0 — carrying forward Task 123's decision, with the Task 122
   causal-timing wording fix carried further

- Track A remains **`ASSOCIATION_SUPPORTED`**, qualified (non-actionable
  by construction; materiality band only partially cleared).
- Track B remains **statistically inconclusive with a negative point
  estimate** (95% CI [−2.14%, +1.21%], N=31) — **not** reinterpreted as
  proof the hypothesis is false, and Track A's association is **not**
  reinterpreted as evidence of an actionable edge. Both stand exactly as
  Task 123 reported them.
- Product decision `NOT_SUPPORTED_UNDER_TESTED_CONTRACT` (i.e.
  DO_NOT_ADVANCE the tested actionable contract) stands.
- **Correction (this task)**: Task 123's "genuinely causal, executable"
  wording is further corrected — Track B used **causally-timed reference
  fills**; actual execution quality (spread-crossing, slippage, fill
  probability) was never established. This is the same correction
  already applied to `TASK123_TIMING_CORRECTION.md` and the Task 123
  journal outcome, restated here as the carried-forward, current
  description.

## Part 2 — existing-data inventory (before requesting anything new)

Full machine-readable manifest: `docs/research/evidence/task124/coverage_manifest.json`
(built by `research/scripts/task124_data_manifest.py`, snapshot taken
2026-09-13). Summary:

| | n |
|---|---:|
| Configured tickers | 48 |
| **Active** (live snapshot, today) | 43 |
| **Paused** | 5 (ASML, PATH, PLTR, RIG, SMCI) |
| Active with existing **daily** coverage | 38 |
| Active with **no** local daily coverage | 5 (BABA, BLSH, SHOP, SKHY, SPCX) |
| Active with existing **1-minute** coverage | 12 |
| Active with **no** local minute coverage | 31 |

**Current watchlist membership is explicitly NOT treated as historical
point-in-time membership** — this is a snapshot of today's
active/paused status only, used to scope which symbols' price HISTORY
is worth checking; it makes no claim about what was configured or
tradable at any past date.

**Files already available locally** (three directories, all previously
inventoried by Tasks 121A/122/123, re-confirmed here):
`results/task95g_broad_cross_sectional/_daily` (Alpaca SIP,
`adjustment=all`), `results/task107a_form4_feasibility/_prices` (Alpaca
SIP, `adjustment=all`), `results/task93_alpha_foundation/_canonical_data`
(Alpaca, UNADJUSTED, 1-minute). Zero symbol overlap between the two
daily directories (precedence rule stated, never actually invoked, same
finding as Task 123).

**Data verified retrievable through existing access** (this task's own
probes, §3) vs. **availability merely claimed by documentation**: the
manifests' own claimed provider/adjustment fields were independently
re-verified against a live API response (Part 3), not merely re-read
from a prior task's text.

## Part 3 — probe evidence (data verification only, no returns inspected)

All probes reuse the exact request/credential pattern already
established by `research/scripts/task63r_probe_alpaca_feeds.py` (same
`data.alpaca.markets/v2/stocks/{symbol}/bars` endpoint, same header
convention, credentials loaded via `.env` and never printed). Full raw
output: `docs/research/evidence/task124/alpaca_feed_probe.json`.

| probe | purpose | result |
|---|---|---|
| 1. Already-covered period (AAPL, 2025-02-05, feed=sip) | confirm feed identity/timestamp semantics of already-downloaded data | HTTP 200, `DATA_PRESENT` |
| 2. Older period (AAPL, several dates 2020–2024, both feeds) | historical minute-data retention | HTTP 200, **substantial bar counts back to at least 2020-03-02** (851 bars/day, SIP) — retention is NOT the binding constraint |
| 3. Missing active ticker (SPCX, 2025-06-02) | does Alpaca have ANY bars for a currently-uncovered name | SIP: HTTP 200, **only 16 bars for the whole session** (~4% of possible minutes) — genuinely, extremely thin trading, not an entitlement gap; IEX: empty |
| 3b. Missing active tickers (SHOP, BABA, 2023-03-01) | same question for two OTHER missing names | SIP: HTTP 200, **571 and 819 bars respectively** — real, substantial coverage available, just never downloaded |
| 4. Corporate-action interval (JPM, ex-div ~2025-04-04, raw vs. all) | verify `adjustment=all` actually performs dividend back-adjustment | **Confirmed directly**: the raw/all price ratio shifts from ≈0.97056 (Mar 31–Apr 3) to ≈0.97654 (Apr 4–Apr 9) — a clean, single-step discontinuity exactly at the ex-dividend date, proving `adjustment=all` is genuine total-return back-adjustment, not merely asserted from documentation |

**Distinguishing outcomes precisely, per this task's own instruction**:
every probe above returned a real HTTP 200; "no entitlement" was never
observed; "empty response" (genuinely 0 bars, not an error) occurred
only for probe 2's initial holiday-date mistake (2024-01-15 = MLK Day,
corrected to an ordinary trading day) and for IEX on SPCX/2020 (that
single exchange saw no quotes, not a request failure). No "request
error" (4xx/5xx) occurred on any probe.

**One earlier date was accidentally chosen ON a market holiday
(2024-01-15) for probe 2** — this HTTP-200-zero-bars result was
correctly NOT treated as a retention limit; the probe was re-run on an
ordinary trading day and produced full coverage. Recorded here as a
transparent self-correction within this task, not hidden.

## Part 4 — contract compatibility

Task 123 Track B's frozen decision rule (15:50 ET cutoff,
same-time-of-day cumulative-volume trigger, 2-minute delay, next-open
reference exit, 5bps cost) is **unchanged** by this task. What this
task establishes is that the DATA needed to run that SAME contract over
a materially longer window, and/or more symbols, is retrievable:

- **Complete historical reference windows for volume**: confirmed
  available (SIP minute bars exist well before the current 2025-01-24
  start, for multiple symbols).
- **Bar timestamp semantics / availability timing**: unchanged from
  Task 123's own verified understanding (each 1-min bar's own close is
  the causal reference point) — the SAME Alpaca `/v2/stocks/{symbol}/bars`
  endpoint and bar-timestamp convention, re-confirmed by probe 1
  matching the already-downloaded data's own semantics.
- **Entry after decision+delay / next-session open**: unaffected by an
  extension — this is adapter logic (`task123_overnight_diagnostic.py`),
  not a data-availability question.
- **Early-close handling**: NOT separately re-verified this task
  (bounded scope) — any acquisition task must explicitly check early-
  close sessions against the actual XNYS schedule before assuming a
  uniform 15:50 ET cutoff applies on those days, exactly as Task 123's
  own protocol already required for the existing window.
- **Missing-bar handling**: unchanged — Task 123's adapter already
  excludes (never fills) a missing cutoff/entry/next-open bar; the SAME
  logic applies unmodified to any newly acquired data.

**Feed comparability — the one real incompatibility risk identified**:
SIP and IEX report MATERIALLY DIFFERENT bar/volume counts for the SAME
symbol/date (e.g., AAPL 2024-03-01: 849 SIP bars vs. 390 IEX bars — SIP
captures far more of the tape). **The already-downloaded
`task93_canonical_v1` dataset's own manifest does not explicitly record
which feed was used** (recorded as `"Alpaca (unspecified feed in
manifest)"` in this task's own coverage manifest — a genuine
provenance gap, not assumed away). If a data-extension task pulls NEW
minute bars via `feed=sip` and appends them to time series whose
ORIGINAL feed identity is unconfirmed, that would risk silently
concatenating two different volume conventions into one series — **this
task does NOT do that**; it flags the gap and requires the next task to
either (a) confirm `task93_canonical_v1`'s original feed before
extending it, or (b) treat any extension as a clearly-labelled,
separate-feed series, never silently merged.

No material contract or feed CHANGE is being proposed — the existing
`feed=sip` convention (already used by every daily dataset in this
program) is available and would be reused, pending the feed-identity
confirmation above.

## Part 5 — feasibility measurement (not profitability)

Based on probe throughput (single-day, single-symbol requests
completing in ~0.3–0.6s each in this task's own probes) and the
existing `task107a_prices.py` script's already-established rate-
limited pagination pattern (`next_page_token` loop, exponential
backoff on 429/5xx):

- **Tickers supportable**: up to all 43 active names (SIP has at least
  SOME coverage for every probed symbol, including the 5 currently
  "missing" ones) — not confirmed for all 43 individually in this
  bounded task, only sampled (AAPL, STX, SHOP, BABA, SPCX, JPM).
- **Covered calendar span**: at minimum 2020-03-02 → present for the
  probed symbols — a >5-year extension over the current 2025-01-24
  start, if fully pursued.
- **Expected download size / request count**: a full extension
  (43 symbols × ~5.5 years × 1 request/day, or chunked multi-day
  requests with pagination) is a **materially larger acquisition** than
  this bounded task's own ~10 probe requests — sized and estimated in
  Part 6 as its OWN acquisition task, not executed here.
- **Independence caveat, stated explicitly**: more observations from a
  longer window do NOT automatically create more INDEPENDENT evidence
  — Task 123's own date-block bootstrap methodology (resampling
  distinct trading DATES, not raw observation count) remains the
  correct dependence-aware approach for any extended dataset; a larger
  N is not by itself grounds to call a future result "properly
  powered."
- **Genuinely unexamined evaluation period**: **YES** — every calendar
  date before 2025-01-24 (for the already-covered 12 symbols) and every
  date for the 5 currently-uncovered active symbols (SHOP, BABA, SKHY,
  BLSH, SPCX — SPCX confirmed extremely thin, others not yet checked)
  would be genuinely new to this specific hypothesis test if acquired.

**Time budget**: this task's own investigation (inventory + 4 probes +
2 follow-up checks) took well under the ~90-minute bound; no provider
restriction was hit that required repeated retrying.

## Part 6 — data verdict

**`A. DATA_EXTENSION_FEASIBLE`**

Existing free Alpaca SIP access, already used and credentialed in this
research program, can provide a materially longer and/or broader
intraday dataset compatible with Task 123 Track B's frozen contract.

### One concrete acquisition-and-validation task (not executed here)

- **Exact symbols**: the 12 Track-B symbols already covered
  (AAPL, AMAT, AMD, AVGO, CSCO, GOOGL, INTC, MSFT, NVDA, PYPL, STX,
  TSLA), extended backward; PLUS the 5 currently-uncovered active
  symbols (BABA, BLSH, SHOP, SKHY, SPCX), fetched fresh — SPCX's
  extreme thinness (16 bars/day observed) should be re-confirmed before
  committing meaningful acquisition effort to it specifically.
- **Exact dates**: extend from the current 2025-01-24 start back to
  **2023-01-01** (a ~2-year extension, well within confirmed retention,
  conservative relative to the >5-year retention this task observed) —
  a fixed, predeclared window, not chosen after peeking at any return.
- **Feed and adjustment**: `feed=sip`, `adjustment=raw` (matching
  `task93_canonical_v1`'s own UNADJUSTED convention) — **contingent on
  first confirming `task93_canonical_v1`'s original feed identity**
  (the provenance gap named in Part 4); if that cannot be confirmed,
  the extension must be stored and labelled as a separate, distinctly-
  sourced series, not silently appended.
- **Quality acceptance rules**: reuse Task 123's own exclusion logic
  verbatim (ordered/unique timestamps, no non-positive prices/negative
  volume, `next_session_strictly_after`-verified session pairing, the
  same ±50% extreme-return guard) — no new rules invented.
- **Storage location**: a new, clearly-labelled local directory (e.g.
  `results/task124_intraday_extension/`, gitignored per this program's
  standing convention) — never overwriting `task93_canonical_v1`'s own
  files in place.
- **Estimated effort**: SMALL-to-MEDIUM — reuses
  `task107a_prices.py`'s existing pagination/backoff pattern; 17 symbols
  × ~2 years of 1-min bars is a bounded, well-understood acquisition
  size for this account's already-demonstrated access, not a bulk
  program requiring new infrastructure.
- **Exploratory vs. unexamined status**: the NEW date range and NEW
  symbols would be **genuinely unexamined** for this specific
  overnight-attention hypothesis (never inspected for this or any
  return in this research program); any RESULT computed from it should
  still be labelled exploratory on first look (consistent with this
  program's own standing convention — a single frozen run is not
  automatically "confirmatory" merely because the underlying dates are
  new), with a clean train/confirmation split reserved for a
  SUBSEQUENT task if this one shows a supported effect.

This verdict does **not** authorize running that acquisition or any
new backtest in this task, and does not authorize live deployment,
Telegram enablement, or any production change.
