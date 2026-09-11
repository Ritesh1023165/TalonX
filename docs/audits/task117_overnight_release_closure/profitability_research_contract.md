# Profitability Research Contract — TalonX (prepared 2026-09-11, Task 117 §7)

**Status:** DRAFT CONTRACT for tomorrow's work. Nothing in this file has been
executed. No parameter optimisation was run tonight.

**Isolation:** all research runs in the dedicated worktree
`C:\workspace\TalonX-task118-profitability` on branch
`research/talonx-profitability-2026-09`, **created from
`research/talonx-strategy-validation-framework` (`a3b6f58`)** — that branch
carries the permanent validation infra (`talonx_research/`: immutable
`StrategyRegistry`, 20 bps paper-candidate gate, `replay_engine` that drives the
real `V2Service.tick()` chronologically and *physically refuses to open
`v2_lane.db`*, `promotion_allowed` always `False`). The release branch
`research/talonx-strategy-validation` does **not** contain `talonx_research/`.

**First step in the worktree:** merge/cherry-pick the accepted Task 117 release
commit so the frozen `talonx_v2/` strategy files match production exactly
(fingerprint `11107198c5b81237`), then verify the fingerprint before any run.

The worktree **must not** be merged back into `research/talonx-strategy-validation`
and **must not** change any frozen strategy input. Keep the `replay_engine`
`v2_lane.db` refusal intact.

**Prime directive:** measure what the three lanes have actually produced under
their *frozen* rules. This is a measurement exercise, not a search for new
signals. Promotion criteria (below) are fixed **before** any new tuning and do
not move.

---

## 1. Scope — three separate deliverables

### A. Exact 39-name V2 historical baseline under frozen rules
- Strategy: `INSIDER_BUY_CLUSTER_V2@1`, fingerprint `11107198c5b81237`, config
  frozen (cluster window 10 td, ≥2 distinct code-P owners per issuer, next
  XNYS-session-open entry, 10-td hold, `max_entry_staleness_sessions=3`, 5-td
  cooldown, equal-notional, $300,000 campaign, membership-OR-liquidity
  eligibility). **No knob changes.**
- Universe: the **exact 39 effective watchlist CIKs** used by the live service
  (`talonx_ingest/intelligence/service` scope resolution), enumerated and
  frozen into the contract run as an explicit list with the resolution date
  stamped. Do **not** silently inherit "whatever the watchlist is on run day".
- Window: SEC Form 4 history available in the isolated ingestion copy. Parquet
  price history currently **ends 2026-03-31** — the baseline horizon ends there;
  state that limit, do not extrapolate past it.
- Output per episode: entry/exit dates, entry/exit price basis, holding period
  actually realised (including `EXIT_UNRESOLVED` / fall-forward ≤5 sessions),
  notional, gross and net return at 20 bps round-trip, SPY-excess.
- Portfolio metrics: trade count, net expectancy per 10 td, profit factor,
  max drawdown, and **concentration** (largest issuer / largest month share of
  P&L, Herfindahl on issuer).
- Chronological holdout: re-state the Task 107B / 112R prereg split
  (discovery ≤ freeze, holdout > freeze) and report both, plus the post-freeze
  out-of-sample subset separately (Task 116 showed the window is pro-cyclical —
  keep that caveat visible).

### B. Original intraday selectivity — is the filtering doing anything?
- Units / timeframe: state exactly what an "evaluation" is (one candidate ×
  one decision tick) and the bar timeframe.
- Count **unique** evaluations (distinct issuer × session), not repeated
  intra-session re-evaluations of the same candidate.
- Rejection distribution across the **five real gates only**
  (`volatility`, `us_session`, `opening_blackout`, `confluence`, `trend`) —
  there is no throttle/cooldown/revalidation gate (Task 117 §4 accounting
  correction); do not invent one to balance a funnel.
- Question to answer with evidence, not opinion: **does the available history
  support the claim that these filters improve outcomes** vs. a
  filter-free baseline on the same candidate stream? Report the counterfactual
  (what the rejected candidates would have returned) with CIs.
- This is descriptive. Tasks 93–101B already closed the free intraday
  price/volume structural-long lane; this deliverable does not re-open it, it
  quantifies the current selectivity.

### C. Experimental positions and outcomes — separately
- Enumerate every Experimental paper position and its outcome (entry, exit,
  realised P&L, still-open valuation at last mark), **including transaction
  costs**.
- Keep this lane in its own block. It is `EXPERIMENTAL / validation-only,
  simulated, no real capital` and must never be comingled with Original's
  official publication count or V2's ledger.

---

## 2. Datasets and prior-rejection inventory (do this first)

Before any run, produce an inventory:
- Which isolated datasets exist and their coverage windows
  (`results/task95*/…`, `results/task115*/…`, `task115b_daily_v1`,
  `task95d_earnings_events_v1`, `task95i_filing_events_v1`, the Form-4 panel
  from Task 111, the 2-yr replay from Task 116).
- The **prior rejection history** from `MEMORY.md` / the research ledger:
  Tasks 93, 94, 95A–95K, 97, 106A. A research family already rejected there is
  not re-run without a **new, written, justified hypothesis** that says what is
  different this time.

---

## 3. Method specification (fill in before running)

| item | commitment |
|---|---|
| historical window | Form-4 history in the isolated copy; price side ends 2026-03-31 (stated limit) |
| ticker membership | explicit frozen 39-CIK list with resolution date; no run-day drift |
| entry / exit model | frozen V2 contract for A; documented Original decision path for B; recorded Experimental fills for C |
| transaction costs | 20 bps round-trip baseline; also report 5 bps and 35 bps sensitivity |
| metrics | trade count, net expectancy / 10 td, profit factor, max drawdown, issuer & month concentration |
| holdout | chronological, prereg split re-stated; post-freeze OOS reported separately |
| incomplete positions | `EXIT_UNRESOLVED` and still-open marks reported explicitly, never dropped or zero-filled |
| missing data | rows with unestablished price/þíme basis are quarantined and counted, not silently excluded |
| promotion criteria | **set below, before any tuning** |

### Promotion criteria (fixed now)
A lane result is **promotable to a real-money proposal** only if *all* hold on
the chronological holdout (not just discovery):
1. net expectancy per 10 td ≥ +20 bps after 20 bps round-trip cost;
2. profit factor ≥ 1.3;
3. issuer-block and calendar-cluster 95 % CIs both strictly > 0;
4. max drawdown ≤ 1.5 × mean annual net;
5. largest single issuer ≤ 25 % of total P&L (no single-name artifact);
6. ≥ 30 independent episodes in the holdout.
Anything short of all six is **diagnostic only**, not a promotion.

### The retrospective-watchlist diagnostic
Applying today's watchlist to past history is **selection / survivorship
biased** and is labelled `DIAGNOSTIC — RETROSPECTIVE WATCHLIST` wherever it
appears. It is never the headline number.

---

## 4. Hard limits for tomorrow

- No broad parameter optimisation. No grid search. No AI/ML model added
  "because it is available".
- No repeat of a previously rejected research family without a new written
  hypothesis.
- Research reads **isolated copies** only and must not compete with the live
  paper session for SEC / price rate limits (run off cached parquet + the
  isolated ingestion DB; no live EDGAR polling from the research worktree while
  the live service is up).
- No change to frozen thresholds, holding periods, sizing, execution scope, or
  the strategy fingerprint.

---

## 5. First research action tomorrow

1. `cd C:\workspace\TalonX-task118-profitability`
2. Merge/cherry-pick the accepted Task 117 release commit; verify
   `v2_release_fingerprint()['fingerprint'] == "11107198c5b81237"`.
3. Produce the **dataset + prior-rejection inventory** (§2) as
   `results/task118_profitability/INVENTORY.md` — no runs yet.
4. Freeze the 39-CIK membership list with its resolution date.
5. Only then: run deliverable **A** (exact V2 39-name baseline) end-to-end
   through `talonx_research/replay_engine` driving the real `V2Service.tick()`
   chronologically, 20 bps costs, holdout split. Write results; do not tune.
