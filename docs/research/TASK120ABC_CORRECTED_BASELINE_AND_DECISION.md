# Task 120A–C — corrected chronological baseline and economic decision

Supersedes (does not delete) `TASK120_ECONOMIC_DECISION.md` and
`TASK120_PROTOCOL_39NAME_SCOPE_REPLAY.md`. Corrections appended as
blockquotes to those files; the authoritative account is this document.

> **Correction (Task 121, 2026-09-12):** the B3 `equity_final.equity`
> figure below ($296,307.36) is **gross of the 20bps research cost
> convention**, not "cost-adjusted equity" — it is V2's own paper ledger's
> `ending_cash` (V2 models zero cost internally), while `net@20bps` is a
> SEPARATE per-trade research adjustment that never flows back into that
> ledger figure. The correct cost-adjusted ending equity is **$295,167.37**
> (starting $300,000.00 + gross P&L −$3,692.63 − explicit cost adjustment
> −$1,140.00, verified exactly = 57 trades × $10,000 avg notional × 20bps).
> Full reconciliation, and the "properly powered" wording withdrawal (the
> B verdict below is a completed, correctly-engineered computation whose
> inference strength is separately, and more modestly, described), are in
> `docs/research/TASK121_TASK120_ACCOUNTING_CORRECTIONS.md`. The headline
> decision (CI including zero) is unchanged.

## TASK A — corrections to Task 120

**A1 — historical/live confusion, corrected.** The N=10, −2.93% figure
(Task 118 Deliverable A) is a **historical chronological replay**,
2024-09-01→2026-03-31, driving the real `V2Service.tick()` via
`talonx_research.replay_engine.run_chronological_replay`. It is **NOT**
ten live trades from 2026-09-08 onward. The live V2 ledger's actual
Friday (2026-09-11) state was **zero trades**, $300,000 cash, confirmed
repeatedly this session (Task 118H/119/120 all correctly stated this
separately — the confusion was specifically in how Task 120's own
protocol/decision doc *described the N=10 figure's origin*, calling it
"live prospective," which was wrong). Every doc that used the wrong
label has a dated correction blockquote appended (not rewritten).

**A2 — episode study vs. chronological replay, corrected.** Task 120's
own script (`task120_39name_scope_replay.py`) used
`t112rp.runtime_episodes()` + `t107b.build_returns()`/`evaluate()` — an
**episode-return study**: it detects episodes and computes horizon
returns directly from price data, with **no position-limit, cooldown, or
capital-constraint enforcement**, and no actual BUY/SELL pairing through
the paper engine. This is materially different from, and less rigorous
than, the **chronological portfolio replay** Task 118 Deliverable A used
(`run_chronological_replay`, driving the literal frozen `V2Service.tick()`
step by step). Task 120's N=27 result is **relabelled**:
`EPISODE_RETURN_STUDY_NOT_CHRONOLOGICAL_REPLAY` — informative as a
secondary cross-check, but not the authoritative product diagnostic.
**Withdrawn** from Task 120's claims: "first properly powered" (false —
Task 118 Deliverable A already used the correct engine at N=10; and no
formal power calculation was performed for either N=10 or this task's own
N=57 result — "properly powered" was never a supported description of
either, only "correctly engineered" is supported for B3),
"fully representative" (the coverage claim behind it was itself wrong —
see A4), and any implied exact-runtime-parity claim (the episode-study
method does not exercise the runtime's position/cooldown/capital logic at
all).

**A3 — scope frozen.** `docs/research/SCOPE_MANIFEST_39NAME.json` — the
same static 39-symbol list `run_baseline_a.py` already used, with
resolution date/method/provenance recorded, used identically (not
re-resolved) by both the B2 and B3 runs below. Retrospective-watchlist
limitation retained verbatim from Task 118 Deliverable A.

**A4 — six-name coverage, corrected.** See
`docs/research/TASK120A_COVERAGE_RECONCILIATION.md` (full table). Task
120 checked only `results/task95g_broad_cross_sectional/_daily` and
wrongly concluded 6 names (including MSTR) had no price history. The
already-successful Task 118 Deliverable A checks **two** directories
(`_daily` **and** `results/task107a_form4_feasibility/_prices`); ABCL,
ACHR, ADC, AGNC, and **MSTR** are all present in `_prices` (Alpaca SIP,
`adjustment=all`, 2019-01-02 onward — verified directly this task, not
assumed). **Only SHOP is genuinely uncovered by either directory** — the
exact, unchanged finding Task 118 Deliverable A already made eleven hours
earlier. No data was retrieved (none was needed for the 5 corrected
names; SHOP's gap is unchanged and has produced zero would-be trades in
every run to date, so it affects nothing computed here).

**A5 — costs reconciled.** `research/scripts/task120b_chronological_baseline.py`
applies **20bps total round-trip cost, once**, computed directly as
`gross_return - 0.0020` per closed episode (verified: `entry_cost_bps=10`,
`exit_cost_bps=10`, `total_cost_bps=20`, published per-trade in
`trades_table` alongside `gross_return_pct` and `net_return_pct_20bps` —
gross/entry-cost/exit-cost/total-cost/net are all explicit columns, not
collapsed). Headline metrics and the bootstrap CI both read from the SAME
`net_return_pct_20bps` column — verified by construction (one function
computes both). This is the **same convention** Task 107B/112R/116/118A
already used (20bps round-trip) — **not** a per-side 20bps convention
from any older study, which would not be directly comparable and is not
conflated here. Cross-check: the B2 overlap run's net expectancy
(−2.9261%) and profit factor (0.31539...) reproduce the stored Task 118
Deliverable A artifact to 4+ significant figures (see B2 below) —
confirming the cost math executes identically in both scripts.

## TASK B — chronological baseline (the actual replay engine, not a new one)

**B1 — engine reuse, versions.** `talonx_research.replay_engine.run_chronological_replay`
(unchanged, reused verbatim — SHA256 `84d69a54671dab1d...`). Drives
`talonx_v2.service.V2Service.tick()`. File hashes recorded (research
worktree, this task): `service.py 53b1871ee33951a7`, `form4_source.py
5fc8bf8df35160d0`, `store.py 77e87cacda807458`, `config.py
6fa678eeef61af35` — **byte-identical to the release worktree** (diffed
directly, zero content difference). `calendar.py` and `paper.py` hash
*differently* between worktrees (`a693c5a8.../56dfe9cc...` vs.
`1521226c.../44b2b180...`) — **diffed directly, content is
byte-identical; the hash difference is CRLF vs. LF line endings only**,
confirmed by `diff` showing zero logical differences. No narrow
synchronization was needed (unlike Task 118's own earlier 5-file
byte-copy, which remains in place and unchanged). No branch merge
performed.

**B2 — overlap regression.** Re-ran Task 118 Deliverable A's EXACT
config (39-name scope, 2024-09-01→2026-03-31, $10,000,000,
`records_provider` with the same 45-day causal rolling window) with the
SAME script pattern, fresh, this task:

| | stored (Task 118 Deliverable A) | fresh (this task) |
|---|---:|---:|
| N | 10 | 10 |
| net@20bps | −2.9261% | −2.9261% |
| profit factor | 0.31539598833195015 | 0.31539555755202126 |

**EXACT MATCH** (N identical, net expectancy identical to 4 decimal
places, PF differs only in the 7th significant figure — floating-point
summation-order noise, not a methodological difference). This is a real,
verified reproducibility proof, not an assumed one — `results/task120b_chronological_baseline/b2_overlap_reconciliation.json`
(local). **The expanded/corrected pipeline is authoritative** for
everything below; nothing was tuned to force this match — it matched on
the first run.

**B3 — longest supported window.** 2019-01-01→2026-03-31 (the full Form-4
parquet coverage; price bars in both directories extend further back and
forward, so the parquet's `filing_date` range is the binding constraint).
Same 39-name manifest, same causal 45-day lookback, same eligibility/
liquidity/cooldown/position-limit rules (unchanged frozen contract — zero
threshold edits). **$300,000 primary** (the live campaign sizing, per
this task's own instruction) **and $10,000,000 comparison** (to isolate
capital constraints):

| sizing | N closed | net@20bps | PF | win rate | ending equity |
|---|---:|---:|---:|---:|---:|
| **$300,000 (primary)** | **57** | **−0.8478%** | **0.766** | **49.1%** | **$296,307.36** |
| $10,000,000 (comparison) | 57 | −0.8478% | 0.766 | — | — |

**Capital was NOT binding** — both sizings produced the identical 57
trades (no entry was skipped for lack of cash at $300k that would have
been taken at $10M) — confirms the negative result is a signal/pricing
fact, not a campaign-sizing artifact.

**B4 — accounting.** `processed_episode_dispositions`: 57 `ENTERED`, 41
`SKIPPED_ENTRY_STALE`, 4 `SKIPPED_CLOSE_*_LT_5.0` (liquidity gate), 1
`SKIPPED_INSUFFICIENT_HISTORY`, 1 `SKIPPED_NO_PRIOR_BARS`, 2
`SKIPPED_IN_COOLDOWN`. 57 BUY / 57 SELL, 57 closed round trips, **0
exit-unresolved, 0 open-at-end** (the full window resolves cleanly with
the 20-session settle tail). Equity = cash + marked open-position value =
**$296,307.36** (0 open positions at window end, so equity = ending cash
exactly — not `portfolio_cash_after`, not a cumulative-return sum; the
formula is stated explicitly in the artifact). Full per-trade table
(symbol, entry/exit price and time, gross/cost/net) published in
`results/task120b_chronological_baseline/b3_full_300k_summary.json`
(local; a sanitized excerpt is committed — see evidence links). 19
distinct issuers; ADC is the single largest (17/57 = 30% of trades).
**Daily marked equity was NOT computed** for the full holding-period
between trade events — that would require pulling daily bars for every
open position across the whole multi-year window, out of this task's
bounded time budget; a trade-event-granularity cash curve is published
instead, explicitly labelled as such (not silently presented as
continuous daily equity).

**B5 — uncertainty.** Predeclared BEFORE running (issuer-block bootstrap,
5,000 reps, seed `118120`, 95% percentile CI — same convention as Task
95A onward): **95% CI = [−4.571%, +1.109%] — includes zero.** 19
distinct issuers is the effective independent-group count (not N=57) —
reported explicitly as the more relevant power measure. Drop-top-1
issuer (ADC, 17/57 trades) sensitivity: mean moves from −0.848% to
**−1.384%** (more negative, not less) — ADC's own trades were mildly
*positive*-contributing on net; excluding it does not flip the sign
either direction. **This history has already been investigated (Task
116's broader-panel replay covers the same underlying episodes) — this
is NOT relabelled an untouched holdout.** No threshold, scope, or sizing
change is made from this result. V2 is not promoted; the 39-name scope
is not expanded.

**Interpretation**: the 39-name live-scope, chronologically-replayed,
correctly-costed result — N=57 closed trades across 19 distinct issuers,
negative observed net expectancy — is **statistically inconclusive** (95%
issuer-block-bootstrap CI includes zero). Completion of the computation is
reported separately from the strength of the underlying inference: N=57 /
19 issuers is not described as "properly powered" or "adequately powered"
— no formal power calculation was performed, and 19 independent groups is
a small basis for such a claim either way. What is supported is only: a
materially tighter and more decisive CI than the withdrawn N=27
episode-study's [−7.51%, +2.31%], and computed with the actual runtime
engine rather than a proxy. It neither confirms nor refutes a real
39-name-scope-specific effect distinct from the broader 620-name panel's
positive result — those remain two different, non-comparable
populations, as already established.

## TASK C — Original/Experimental exact-contract evidence decision

**C1 — equivalence check.**

- **Original**: `talonx_quant`/`talonx_core`'s frozen strategy,
  `strategy_version` fingerprint `2ae6216bca70` — **verified unchanged
  today** (`talonx_ops.prospective.V1_FINGERPRINT_EXPECTED ==
  "2ae6216bca70"`, checked live this task, matches). **Task 93**
  (`results/task93_alpha_foundation/FINAL_REPORT.md`) evaluated this
  EXACT strategy version — confirmed via `git diff 848de0d..HEAD` over
  the four quant strategy files being empty at the time of that report —
  over 4,468,726 bars / 35–45 symbols / ~18.7 months (2025-01-24→2026-08-14).
  **Result: exactly ONE trade in the entire dataset** (PYPL, +5.99R at 0
  bps, statistically indistinguishable from a lucky random entry).
  Verdict there: `CURRENT_STRATEGY_EDGE_WEAK_OR_UNPROVEN` — not
  "rejected" (no negative-edge evidence), not "supported" (no sample).
  **This is an exact-contract match — cite it, do not rerun.**
- **Experimental** (`EXPERIMENTAL_RELAXED_V1`, relaxed vol-gate ≈0.10%,
  confluence≥1, R:R≥1.0): **no exact-contract historical backtest
  exists.** The closest existing evidence is Task 93's own Phase 7
  volatility-gate counterfactual (`parameter_stability.md`): at a 0.10%
  ATR floor, 1,071,478 bars pass (5.8× more than the 0.25% Original
  floor), and the Phase-7 counterfactual found those newly-admitted bars
  carry "~zero forward long edge." This is **strong, directly relevant,
  but not exact** — it isolates ONE of Experimental's three relaxed
  parameters (volatility), not the combined confluence≥1 + R:R≥1.0
  configuration together, and does not apply Experimental's own specific
  execution/session-exit mechanics or costs through a full chronological
  replay. Experimental's only economic evidence to date remains the live
  paper sample (4 recovery-affected exits + 1 open SPCX position,
  2026-09-09→11) — already correctly labelled, in every prior report
  this session, as not a track record.

**C2 — route selected.**
- **Original: ROUTE 1** — exact evidence exists (Task 93). Cited, not
  rerun.
- **Experimental: ROUTE 3** — a material gap exists (the combined
  three-parameter relaxed contract, with costs, through a full
  chronological replay, has never been run), but assembling that replay
  correctly (a dedicated 1-minute-bar historical dataset wired through
  `talonx_signals`' exact signal-generation code, not `talonx_v2`'s
  engine) is a genuinely new piece of research infrastructure, not a
  parameter change to something already built — explicitly out of scope
  for "do not build a new research framework overnight." **Smallest
  reproducible next action, not performed here**: reuse Task 93's own
  already-built, already-validated `task93_canonical_v1` dataset
  (4,468,726 bars, 0 structural defects, fingerprinted) and run
  Experimental's EXACT relaxed gate combination (vol≥0.10%,
  confluence≥1, R:R≥1.0) through the SAME Phase-3/7 replay machinery
  Task 93 already built and validated — no new data acquisition, no new
  framework, a parameter-set substitution into existing, tested code.
  Effort estimate (honest): **small-to-medium** (the dataset and harness
  exist; the work is wiring Experimental's specific gate combination into
  Task 93's existing evaluation code and running it once).

**C3 — product decision.**

# `INSUFFICIENT_EVIDENCE_WITH_ONE_SPECIFIC_NEXT_ACTION`

- **User requirement concerned**: "configured tickers, intraday and
  short/long-horizon alerts, and attributable local paper portfolios,"
  specifically the intraday/Original and Experimental lanes (V2's
  medium-horizon question is answered separately by Task B above —
  itself also inconclusive, CI includes zero).
- **Opportunity frequency and net economic evidence**: Original fires
  essentially never (1 trade / 18.7 months across 35–45 symbols) — a
  frequency problem, not a demonstrated negative-edge problem; no
  economic evidence exists at that frequency to evaluate. Experimental's
  relaxed gates fire far more often structurally (Task 93's own
  volatility-only counterfactual: 5.8× pass-rate at the 0.10% floor) but
  no costed, full-contract historical sample exists — only the tiny,
  already-labelled live sample.
- **What remains unknown**: whether Experimental's SPECIFIC combined
  relaxed contract (not just the volatility dimension alone) has a real
  edge, negative or positive, at a sample size larger than the live-only
  N=5.
- **Why the next action provides new information**: it directly answers
  that unknown using ALREADY-BUILT, already-validated infrastructure
  (Task 93's dataset + harness) — no new data collection, no new signal
  family, no framework construction.
- **Acceptance/rejection conditions** (predeclare for that future run):
  same convention as this task's own B5 — issuer/time-block bootstrap CI
  on net returns after realistic costs; CI clearly excluding zero on the
  positive side would support further validation; CI clearly excluding
  zero on the negative side would support rejecting the relaxed contract
  for live promotion; CI including zero (the modal outcome across nearly
  every study this session) would again be genuinely inconclusive, not a
  failure of the research.

**Explicitly not done**: no new volatility filter derived from the
concentrated Sept-11 ten-trade Experimental sample; no automatic
Experimental Telegram/external enablement; no claim that every possible
free-data strategy is exhausted (Experimental's specific relaxed-contract
question remains genuinely open, stated as such); no recommendation
consisting only of waiting years for more V2 entries (V2's own next
action, from Task 120, stands unchanged and is not repeated here as the
sole path).

## Product status page (small update)

New: `docs/research/PRODUCT_STATUS.md` — one page, linked from
`NEXT_SESSION_HANDOFF.md` (not a documentation-tree rewrite). States: user
objective is profitable configured-ticker alerts + attributable local
paper (unchanged); Intelligence is useful information, not trading
profitability; V2 is a sparse supplementary strategy, evidence
inconclusive both at 39-name (this task) and broad-panel scope; Original
essentially never fires under its current frozen gates (evidence exists,
cited); Experimental's exact relaxed contract is the one specific,
smallest, already-infrastructure-backed next research action.
