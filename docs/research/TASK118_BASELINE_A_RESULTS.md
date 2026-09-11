# Task 118 Deliverable A — exact 39-name V2 baseline (executed 2026-09-11)

**Verdict: BASELINE_COMPLETE (small-sample, does not support further conclusions).**
Measurement only. No parameter tuning, no promotion, no strategy change. V2
fingerprint verified `11107198c5b81237` before running (would have aborted
otherwise).

## Runtime compatibility (fingerprint equality alone was insufficient)

The 5 frozen strategy files matched the release by fingerprint already
(`docs/research/TASK118_INVENTORY.md`), but a file-by-file check of the
**relevant service/source-adapter/pricing/sizing/execution/accounting paths**
found the research worktree's `talonx_v2/service.py`, `form4_source.py`, and
`store.py` were pre-Task-117 vintage — missing `execution_allowlist`
(needed for exact-scope enforcement), the Task 117 Phase 0 F3
dissemination-slack-window fix in `form4_source.py`, and the delivery-related
tables in `store.py`. `talonx_v2/pricing.py` (the `composite-yf` live pricing
adapter) does not exist in the research worktree at all. `calendar.py` and
`schemas.py` were already identical.

**Fix:** narrow byte-copies of `service.py`, `form4_source.py`, `store.py`
from the release worktree (same pattern as the earlier 5-file fingerprint
fix — not a branch merge). `pricing.py` was deliberately **not** copied —
the baseline uses the frozen `pricing_mode="csv"` default (matching Task
116's own methodology), so the live `composite-yf` adapter is out of scope
for this offline replay and its absence is not a compatibility gap for this
run.

## Method

- Engine: `talonx_research.replay_engine.run_chronological_replay` — drives
  the REAL `talonx_v2.service.V2Service.tick()` one XNYS session at a time
  ("as if living through time"), using the SAME frozen strategy files as
  production. Physically refuses to open the live `v2_lane.db` (a hard,
  tested guard).
- Scope: a `records_provider` restricted the Form-4 code-P universe to the
  **frozen 39-name manifest** (resolved 2026-09-11) at every tick, using the
  same 45-day rolling causal window `V2Service._records()` uses live — no
  additional relaxation.
- Data: `talonx_ingest`'s historical research parquet
  (`results/task107a_form4_feasibility/_build/form4_open_market_txn.parquet`)
  + local bar CSVs (`task95g_broad_cross_sectional/_daily` +
  `task107a_form4_feasibility/_prices`) under `C:\workspace\TalonX\results\`
  — static, frozen, read-only historical artifacts (not the live production
  databases; no network calls, no rate-limit contention with the live
  session).
- Window: **2024-09-01 → 2026-03-31** — the Task 116 "usable" window (the SEC
  Form-4 bulk parquet coverage ends 2026-03-31; a later end date was not
  requested here for the same reason).
- Cost convention: **20 bps round-trip** (Task 107B/112R/116 preregistered
  convention).
- Sizing: replay `starting_cash=$10,000,000` (Task 116's research
  convention, for comparability with the broader validated population) —
  **not** the live $300,000 / 20-slot campaign; per-position sizing is the
  frozen equal-notional `TALONX_V2_ALLOCATION_USD` default ($10,000/position)
  regardless of starting cash, so dollar P&L figures are on that fixed
  notional.
- Chronological split: this cut is measurement-only; the formal
  discovery/holdout statistical split, bootstrap CIs, and week-cluster
  dependence machinery (present in `talonx_research.validation` for the
  full-panel case) were **not** extended to an arbitrary symbol subset
  tonight — out of scope for this bounded session (see Remaining blockers).

### Previously inspected?

**Yes, in aggregate.** The Sep 2024–Mar 2026 window and the underlying
insider-cluster episodes were already covered by Task 116's full ~620-name
survivorship-panel replay (N=170). This 39-name cut is a **new aggregation of
previously-inspected data**, not an unseen holdout — it must not be treated
as an independent out-of-sample test.

## Data coverage

- 39/39 names have Form-4 code-P coverage in the parquet (the ingestion
  source is universal; the manifest only restricts which symbols the
  strategy considers).
- Price-panel coverage: **38/39** names have a local bar CSV
  (`task95g_broad_cross_sectional/_daily` or
  `task107a_form4_feasibility/_prices`). **SHOP is uncovered by either bar
  directory** — any SHOP cluster in-window could be detected but not priced
  (would surface as a `SKIPPED_*`/unpriced disposition, not a trade). No SHOP
  entries occurred in this window regardless.

## Results

| metric | value |
|---|---:|
| episodes detected (all dispositions) | 17 (10 ENTERED + 2 liquidity-gate SKIPPED_CLOSE + 5 SKIPPED_ENTRY_STALE) |
| BUY / SELL | 10 / 10 |
| closed round trips | 10 |
| exit-unresolved / open-at-end | 0 / 0 |
| net expectancy (mean, 20 bps) | **−2.93%** per 10-td trade |
| profit factor | **0.315** |
| win rate | **30%** |
| max drawdown (equal-weight running return) | −42.7% |
| top-issuer share of total **absolute** P&L | **65.6% — MSTR** |
| drop-top-1-issuer (MSTR) sensitivity | N=6, mean flips to **+1.12%** |

By issuer (net return sum, 20 bps, equal-weight units): ACHR −4.7%, **MSTR
−36.0%** (4 trades, all losses), UNH −1.4%, ADC +5.9% (2 trades), ABT +3.7%,
IBM +3.1%.

## Comparison with the broader validated population (same window/method)

| population | N | net@20bps | PF | win rate |
|---|---:|---:|---:|---:|
| Task 116 full ~620-name panel, same window | 170 | +2.196% | 2.228 | — |
| Task 112R G2b, full survivorship panel 2019–2026 | 756 | +1.013% | 1.335 | 56.1% |
| **This — 39-name scope, same window** | **10** | **−2.93%** | **0.315** | **30%** |

**Interpretation:** the 39-name execution scope (today's curated mega-cap /
blue-chip watchlist) produces a much smaller, noisier, net-**negative**
sample over the identical window and method. This is consistent with the
manifest being a retrospective, non-representative diagnostic subset — it
was never selected for backtested insider-cluster frequency — not a
refutation of the broader-panel result, and **not** a basis for a
39-name-specific profitability claim in either direction at N=10.

## Whether the sample supports further conclusions

**No.** N=10 is far too small for any statistical claim. A single issuer
(MSTR, 4 of 10 trades) determines the sign of the entire-sample result.
Dropping it flips the mean from −2.93% to +1.12% on the remaining N=6 — also
too small to conclude anything. No bootstrap CI / discovery-holdout / drop-CI
robustness check was computed for this specific cut.

## Retrospective-watchlist diagnostic label

Per the research contract, applying **today's** 39-name watchlist to
**historical** episodes is a `DIAGNOSTIC — RETROSPECTIVE WATCHLIST`
(selection/survivorship bias: the watchlist was not chosen based on backtested
performance, but its composition today still reflects hindsight about which
names matter now). This result is not inherited as a claim about the
broader-panel/full-universe strategy performance, and the broader-panel
result is not inherited as a claim about this 39-name scope.

## Remaining blockers / not done tonight

- Deliverable B (Original intraday selectivity) and C (Experimental separate
  accounting) — not started; next in the contract's ordering.
- Formal discovery/holdout split, bootstrap issuer-block/week-cluster CIs,
  and drop-top-N robustness for this 39-name-scoped cut specifically — the
  machinery exists in `talonx_research.validation` for the full-panel case
  only; extending it to an arbitrary symbol subset needs a small, reviewed
  code change, not attempted tonight.
- CIK-level cross-reference for the manifest (ticker-level scoping was
  sufficient for this run since `V2Service`/`form4_source` key off symbol).

## Evidence files

`results/task118_profitability/` (gitignored, local only):
`run_baseline_a.py` (the script), `baseline_a_replay_result.json` (raw
trades/episode dispositions from the real chronological replay),
`baseline_a_summary.json` (this document's computed metrics), 
`replay_v2_lane.db` (the isolated replay ledger — never the live one).
