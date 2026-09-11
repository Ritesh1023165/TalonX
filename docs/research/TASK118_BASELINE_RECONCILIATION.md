# Task 118 Part 2 — V2 baseline reconciliation (2026-09-11)

Reconciles `docs/research/TASK118_BASELINE_A_RESULTS.md` (Task 118 Deliverable
A, executed earlier the same day) against its own raw artifacts. **No
re-simulation, no parameter change** — this document re-derives every number
from the already-committed replay outputs (`results/task118_profitability/`,
gitignored, hashes below) plus one new, separately labelled diagnostic
(§C.3). Reproducible via
`results/task118_profitability/reconcile.py` (checked in).

## A. Reproducible runtime and data

### A.1 Runtime modules actually exercised (fingerprint equality alone is insufficient)

| module | role | md5 (this worktree) | matches release? |
|---|---|---|---|
| `talonx_v2/service.py` | `V2Service.tick()` — entry/exit/scope/sizing orchestration | `8dfa40ffafff65065736cef45f9711fb` | **yes**, byte-identical (verified against `C:\workspace\TalonX\talonx_v2\service.py` this run) |
| `talonx_v2/form4_source.py` | Form-4 code-P adapter, dissemination-slack window | `ab1b7c4c7f6ea56d58b6aabedc496a57` | **yes**, byte-identical |
| `talonx_v2/store.py` | ledger schema (positions/trades/cooldowns/intents) | `1a06c8da2df674622f685efe187d7e62` | **yes**, byte-identical |
| `talonx_v2/calendar.py` | XNYS session calendar | `c4afa539a5f65615d7f4ec48922e3900` | yes (already identical since worktree fork, unchanged) |
| `talonx_v2/schemas.py` | frozen strategy dataclasses | `d94c20651c94fb31e4447535818a8886` | yes (frozen-file set) |
| `talonx_v2/config.py`, `cluster_engine.py`, `liquidity.py`, `quant_bridge.py`, `brain_bridge.py` | frozen strategy rule (5-file fingerprint set) | fingerprint `11107198c5b81237` | yes — checked by the script itself before running (aborts otherwise) |
| `talonx_v2/pricing.py` | live `composite-yf` pricing adapter | **absent in this worktree** | **N/A — out of scope for this run.** The baseline uses `pricing_mode="csv"` (local historical bar CSVs), matching Task 116's own methodology. The live adapter is a different code path exercised only by the running paper session, not by this offline replay; its absence here is not a compatibility gap **for this run**, but it does mean this baseline says nothing about `composite-yf`-specific behavior (staleness handling, provider fallback) — that is out of scope, not silently assumed equivalent. |
| `talonx_research/replay_engine.py` | drives `V2Service.tick()` chronologically; hard-refuses the live `v2_lane.db` | `97544210f7b50fc93acf5966e1f45a64` | research-only infra, not part of the release fingerprint |

The `service.py`/`form4_source.py`/`store.py` byte-copy (from the earlier
Task 118 Deliverable A run) is re-verified here, not merely asserted:
md5s taken independently in both worktrees this session are identical.

### A.2 Manifest and resolution

39-name manifest, resolved 2026-09-11 via `python -m talonx_ops.watchlist_coverage`
(read-only `intelligence.service.scope.resolve_watchlist`), unchanged since
`docs/research/TASK118_INVENTORY.md`. **Historical membership limitation**:
the manifest reflects **today's** watchlist configuration, applied
retrospectively to 2024-09-01→2026-03-31 history — a
`DIAGNOSTIC — RETROSPECTIVE WATCHLIST`, not a survivorship-controlled
historical universe. Whichever names were added to or dropped from the
underlying watchlist config across that ~19-month window are invisible to
this replay; it sees only the frozen 39, at every historical date, as if
they had always been the active scope. This is unchanged from, and
explicitly disclosed in, the original Deliverable A report.

### A.3 Filing/price datasets, coverage, hashes

| dataset | path | role |
|---|---|---|
| Form-4 code-P parquet | `C:\workspace\TalonX\results\task107a_form4_feasibility\_build\form4_open_market_txn.parquet` | filing-side source (frozen, static) |
| daily bar CSVs (panel 1) | `C:\workspace\TalonX\results\task95g_broad_cross_sectional\_daily\*.csv` | price-side source |
| daily bar CSVs (panel 2) | `C:\workspace\TalonX\results\task107a_form4_feasibility\_prices\*.csv` | price-side source (fallback) |

Coverage: **38/39** names have a local bar CSV in panel 1 or panel 2.
**SHOP is uncovered by either panel.** Filing-side coverage is universal
(39/39) — the ingestion source itself is not scope-restricted, only the
`records_provider` filter is.

**Did missing SHOP prices block an otherwise-eligible episode?** Checked
directly against the 17-row `processed_episodes` table (§B): **no SHOP
episode occurred in this window at all** — SHOP never produced a ≥2-distinct-
insider code-P cluster in the 39-name-filtered Form-4 feed over
2024-09-01→2026-03-31. Missing SHOP prices therefore had **zero observed
effect** on this specific run's episode count — but this is a fact about
*this window's filing history*, not a structural guarantee: had a SHOP
cluster occurred, it would have surfaced as an unpriced
`SKIPPED_*`/undetermined-price disposition rather than a silent drop, and a
different window could expose the gap. "No SHOP trades" alone would not
have established "no impact" without this direct episode-table check.

### A.4 Chronological replay settings

- Engine: `talonx_research.replay_engine.run_chronological_replay`, one
  XNYS session at a time, driving the real `V2Service.tick()`.
- `records_provider(as_of)`: 45-day rolling causal window (same as
  `V2Service._records()` live), filtered to the 39-name manifest — no
  additional relaxation beyond scope.
- Liquidity rule: the frozen $5 minimum-close gate (`SKIPPED_CLOSE_x_LT_5.0`
  dispositions below).
- Sizing: fixed equal-notional $10,000/position (`TALONX_V2_ALLOCATION_USD`
  default), independent of starting cash.
- Cost: 20 bps round-trip, applied **once**, post-hoc by the reconciliation
  script — not inside `V2Service`'s own ledger (§C.1).
- Window: 2024-09-01 → 2026-03-31 (Task 116's usable window; SEC Form-4 bulk
  parquet coverage ends 2026-03-31).

## B. Trade-level reconciliation

Full sanitized data: `results/task118_profitability/reconciliation/episodes.csv`
(17 rows) and `results/task118_profitability/reconciliation/trades.csv` (10
rows). Summary below.

### B.1 All 17 episode dispositions

| disposition | count | detail |
|---|---:|---|
| `ENTERED` | 10 | became a closed round trip (§B.2) |
| `SKIPPED_CLOSE_2.23_LT_5.0` (ABCL, 2025-03-12) | 1 | frozen $5 liquidity gate — close $2.23 |
| `SKIPPED_CLOSE_3.61_LT_5.0` (ABCL, 2026-03-02) | 1 | frozen $5 liquidity gate — close $3.61 |
| `SKIPPED_ENTRY_STALE` | 5 | second/later cluster within `max_entry_staleness_sessions=3` of a prior episode on the same issuer — see per-row detail in the CSV |

By issuer: ACHR 1, ABCL 3 (2 SKIPPED_CLOSE + later folded into the running
count), MSTR 6 (4 ENTERED + 2 SKIPPED_ENTRY_STALE), UNH 1, ADC 3 (2 ENTERED +
1 SKIPPED_ENTRY_STALE), ABT 1, IBM 1. (17 total — see CSV for exact per-row
issuer/date attribution; this table's ABCL/MSTR/ADC counts are the sum of
their rows in `episodes.csv`.)

### B.2 All 10 closed trades

See `reconciliation/trades.csv` for entry/exit dates, entry/exit prices,
shares, gross/net return, and net dollar P&L per trade, keyed by
`episode_id` (joins directly to `episodes.csv`). Aggregate:

| metric | value |
|---|---:|
| closed round trips | 10 |
| wins / losses | 3 / 7 |
| net expectancy (mean, 20bps) | −2.926% |
| net P&L (sum, $10k notional/position) | **−$2,926.15** |

### B.3 Explaining the trade-count differences

**"Earlier reported three trades in the watchlist-restricted replay"**: a
targeted search of this repository's tracked history (git log across both
`docs/research/TASK118_INVENTORY.md` and
`docs/research/TASK118_BASELINE_A_RESULTS.md` on every commit, plus a
full-text search of `docs/` on both branches for "watchlist-restricted",
"3 trades", and "N=3" in a V2/insider-cluster context) found **no prior
report of a three-trade, 39-name-scoped V2 replay**. The only "3" figures
present in this repository's history are (a) an unrelated Original-strategy
backtest lineage (Task 8, `docs/research/TALONX_RESEARCH_LEDGER.md`,
2-symbol AAPL+STX smoke test, a completely different strategy and engine),
and (b) "3 PENDING" Intelligence-card backlog survivors from the Task 117
activation (`docs/audits/task117_controlled_activation_2026-09-11/`), which
counts SEC-filing cards awaiting Telegram delivery, not V2 trades. **This
comparison point cannot be reproduced and is not reconstructed here** — if a
three-trade figure exists, it was not committed to either branch's history
under a discoverable name; state precisely what is missing rather than
inventing a reconciliation.

**Current ten executed trades**: this is Task 118 Deliverable A itself
(§B.2 above) — the only 39-name-scoped V2 replay actually executed and
committed to date.

**Task 116 episode counts vs. its 150 BUY/150 SELL pairs**: Task 116 ran
the **same engine, same window, same cost convention** but with **no
execution-scope restriction** — the full ~620-name survivorship panel. Its
own reported figures were N=170 **episodes entered** (its README's
"episodes" language) which produced exactly 150 closed BUY/SELL pairs (the
remaining 20 were open-at-end or exit-unresolved at the 2026-03-31 window
boundary — Task 116's own report documents this split). This 39-name run
has no open-at-end/exit-unresolved trades (0/0, §B.2) because at only 10
entries across 19 months, none happened to straddle the window boundary —
a sample-size artifact, not a methodological difference. **Task 112R's
window is materially longer** (full survivorship panel 2019–2026, vs. Task
116/this run's 2024-09-01→2026-03-31) and is not the same window — its
N=756/+1.013% figure is comparable only in *method*, not in *period*, and
is presented that way in §C.4, not as a same-window match.

## C. Correct economic measurement

### C.1 Costs applied once, under a clearly stated convention

`V2Service`'s own ledger does **not** deduct trading costs — its `SELL` leg
`realized_pnl_usd`/`realized_pnl_pct` fields are **gross**. The 20bps
round-trip convention is applied exactly once, post-hoc, by
`reconcile.py`/`run_baseline_a.py` (matching Task 107B/112R/116's own
convention). Verified by direct cross-check:

| quantity | value |
|---|---:|
| ledger gross P&L (`ending_cash − starting_cash`, no cost deducted) | **−$2,726.15** |
| total 20bps round-trip cost (10 trades × $10,000 notional × 0.20%) | **$200.00** |
| reported net P&L (gross − cost) | **−$2,926.15** |
| reconciles exactly | **yes**, gross − cost = net to the cent |

This $200.00/−$2,726.15/−$2,926.15 triangle is the authoritative check that
costs were applied exactly once, not zero times (the raw ledger) and not
twice (double-deducted).

### C.2 Win rate, profit factor, net expectancy — reproduced

Recomputed independently from `trades.csv`: **win rate 30% (3/10), net
expectancy −2.926%/trade, profit factor 0.315** — identical to the original
Deliverable A report (`baseline_a_summary.json`) to within float rounding.
No discrepancy found.

### C.3 Portfolio drawdown — the −42.7% figure is NOT a portfolio drawdown

The original report's `max_drawdown_equal_weight_running_return: −42.7%` is
a **cumulative trade-return running-sum**, in return-percentage-points,
computed by summing each trade's net-return-% in entry order (an
equal-weight "1 unit per trade" curve) — **it is not a dollar portfolio
equity curve and is not scaled by position sizing or book size.**

The **actual** chronological portfolio equity curve, built from
`portfolio_cash_after` on every trade against the real $10,000,000 book:

| metric | value |
|---|---:|
| real portfolio-equity max drawdown (dollars) | **−$23,042.30** |
| real portfolio-equity max drawdown (% of peak book value) | **−0.2304%** |
| published cumulative-trade-return running-sum | **−42.7%** |

These measure fundamentally different things: at only 10 trades of $10,000
each against a $10,000,000 (or even $300,000, §C.4) book, the strategy never
put more than a small fraction of capital at risk concurrently, so the real
portfolio never experienced anything close to a 42.7% drawdown. The 42.7%
figure describes how badly a hypothetical "always-in, one trade at a time,
unit-sized, non-compounding" return series drew down — a **trade-quality**
diagnostic, not a **capital-at-risk** diagnostic. Both are legitimate but
answer different questions; conflating them overstates the strategy's risk
to actual deployed capital by roughly two orders of magnitude.

### C.4 $10,000,000 research sizing vs. $300,000 live campaign — diagnostic re-run

Per-position sizing is a fixed $10,000/position **regardless of starting
cash** (`TALONX_V2_ALLOCATION_USD` default) — so the two sizings differ only
in *how many concurrent positions could be held before running out of cash*
($10,000,000 → 1,000 slots; $300,000 → 30 slots).

**Max concurrent notional exposure actually reached in this 10-trade
sample: $20,000** (at most 2 positions open at once) — far under both
budgets. A separately labelled diagnostic re-run
(`results/task118_profitability/run_baseline_a_300k_diagnostic.py`,
`starting_cash=$300,000`, otherwise byte-identical script) confirms this
directly: **identical 17 episode dispositions, identical 10 closed trades,
identical performance metrics** (net −2.926%, PF 0.315, win rate 30%,
max trade-return-drawdown −42.74%) to the $10,000,000 run. **The $300,000
live-campaign cash constraint was never binding for this scope/window at
this sizing** — this sample provides no evidence either way about what
would happen at a materially larger number of concurrent entries (e.g. a
broader scope or longer window), only that it did not bind here.

### C.5 Exposure, concurrency, issuer concentration

Max concurrent open positions: 2 (§C.4). Issuer concentration (share of
total **absolute** net P&L): MSTR 64.0%, ADC 12.9%, ACHR 8.4%, ABT 6.7%,
IBM 5.6%, UNH 2.4% (`reconcile.py` output; differs marginally in rounding
from the original report's 65.6% due to a since-noted `null`-on-negative-
total bug in the original script's `top_issuer_pnl_share` formula — both
numbers describe the same underlying fact: MSTR dominates). **The full
ten-trade result stays primary.** The MSTR-drop sensitivity (N=6,
+1.12%) remains a concentration diagnostic only, not a basis for excluding
MSTR from the reported baseline.

## Evidence

`results/task118_profitability/reconcile.py` (script, checked in),
`results/task118_profitability/reconciliation/{episodes,trades}.csv`
(checked in, sanitized — no account/API identifiers), `run_baseline_a_300k_diagnostic.py`
+ `baseline_a_300k_summary.json` (checked in / gitignored respectively —
raw JSON stays out of git per repo convention, script is tracked).
