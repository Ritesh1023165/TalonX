# Task 118 Part 5 — decision table and recommended next experiment (2026-09-11)

## Decision table

| lane | available evidence | economic result | limiting factor | next experiment | promotion requirement |
|---|---|---|---|---|---|
| **V2 (`INSIDER_BUY_CLUSLE_V2`, full scope)** | Task 116 (N=170, same window), Task 112R G2b (N=756, 2019–2026) | +2.196% / PF 2.228 (Task 116); +1.013% / PF 1.335, win 56.1% (Task 112R) — both CIs > 0 | **none identified yet** — the one candidate that cleared the paper bar; currently live at $300k | none needed — continue live paper observation | already frozen/live; further promotion (real capital) is explicitly out of scope for any research task |
| **V2 (39-name execution scope, today's diagnostic)** | Task 118 Deliverable A + reconciliation, N=10, same window/method | −2.926% / PF 0.315, win 30% (net-negative, entirely driven by MSTR 64% of abs. P&L) | **sample size** — N=10 is a retrospective, non-representative watchlist subset, not an independent test | none — do not re-slice this subset further or drop MSTR to force a positive number | not applicable — this is a diagnostic of the *live scope*, not a candidate strategy of its own |
| **Original intraday** | `suppression_counts`, 5 sessions, ~76.8k gate events; live 1m-buffer state | 0 published signals on every recent day (`ZERO_ACTIVITY_BY_DESIGN`) — no trades to measure | **selectivity by design** (volatility gate, ≥99.8% of rejections, correct units, matches Task 93/94/95A's already-closed no-edge finding) **plus** an unresolved pre-open 1m-buffer warm-up gap (4/43 ready) whose live-session impact is an evidence gap, not yet a demonstrated lost-opportunity cost | **none proposed** — the underlying no-edge result (Task 95A, 25.8M bars) is not being reopened without a new hypothesis; the warm-up gap is an operational item for the operator, not a research experiment |promotion not applicable — 9 free-data alpha spaces already closed (Task 95J synthesis) |
| **Experimental (paper, informational)** | 5 open positions, `check_exits`/`flatten_all` never invoked live (code-cited) | **unmeasurable** — 0 of 5 positions have ever closed, so no realized P&L exists to evaluate; unrealized ≈ −$334 gross on stale (yesterday's) prices, 2 of 5 already past their recorded stop | **lifecycle defect** — the exit mechanism exists but the live process never calls it; not a data or strategy-selectivity problem | **fix is out of scope for a research task** (no production code changes were made); recommend the operator wire `check_exits`/`flatten_all` into `talonx_signals/run.py`'s loop before drawing any Experimental profitability conclusion | never — Experimental delivery is explicitly informational-only and structurally blocked from external send; no promotion path exists |

## Is the main limitation opportunity, data/readiness, delivery, selectivity, or negative economics?

**It differs by lane, and no single answer covers all four:**

- **V2 (full scope)**: none of the above — it is the one working result. The
  limiting factor for *learning more* is simply accumulating more live
  paper-session days; today's controlled activation is exactly that.
- **V2 (39-name scope)**: **sample size**, not economics — N=10 is too
  small to conclude the scope is worse or better than the full panel; the
  −2.93% figure is real but not yet informative about the scope's true
  expectancy.
- **Original intraday**: **strategy selectivity** (the volatility gate is
  working exactly as designed and correctly implemented — confirmed by
  unit trace, §Part 3) is the primary, already-closed limiting factor. A
  secondary, *not yet resolved*, **readiness** question exists (the 4/43
  pre-open warm-up gap) but has not been shown to cost qualified
  evaluations during an actual regular session — that specific causal link
  is an evidence gap, not a demonstrated cause.
- **Experimental**: **delivery/lifecycle**, concretely — a real code path
  (`check_exits`/`flatten_all`) exists and is simply never invoked. This is
  the cleanest, most actionable, most certain finding in this entire task:
  it is not a data gap, not a strategy question, and not a negative-
  economics result — it is an un-wired function call.

## Recommended single next experiment

**Continue live V2 paper observation at the current 39-name scope
(already running, `results/prospective_2026-09-11`) and accumulate real
forward trading days**, rather than launching any new backtest research
space tonight. Rationale, ranked:

1. The 39-name-scope question ("does today's watchlist perform differently
   from the full panel?") cannot be resolved by re-slicing more of the
   *same* already-inspected 2024-2026 history — every additional cut of
   that window is still retrospective. The only way to add real evidence is
   **forward, causal, live observation** — which the running paper session
   already provides, at zero additional research cost.
2. It requires no new code, no new data collection, no new hypothesis
   registration — it is the natural continuation of today's controlled
   activation (Task 117), already authorized and already in progress.
3. Every free-data alpha-discovery space that *could* justify a new
   backtest research track (Original intraday, swing, earnings-event,
   cross-sectional, filing-event, risk-filter, catalyst-displacement) is
   already closed per the Task 118 inventory (§3) with no new evidence
   presented here that reopens any of them.

**This does not resemble a prior rejected experiment** — it is not a new
backtest at all, it is continued operation of the one candidate that
already cleared the paper bar (Task 107B/109/112R/115/116).

**What would cause rejection of this recommendation (i.e., what would
justify running something else instead)**: if, after a materially larger
number of live 39-name-scope trading days (a specific number is not
committed here — that threshold should be set with the same
discovery/holdout discipline as Task 107B/109, not picked post-hoc), the
accumulated live sample continued to show negative net expectancy with a
confidence interval that excludes zero on the positive side, that would be
new, forward, non-retrospective evidence the 39-name scope specifically
underperforms the broader validated panel — at that point, re-examining the
scope's composition (not the strategy rule itself) would be justified by
genuinely new evidence, not by re-slicing the same 19 months of history
again.

**Separately, and not competing for research priority**: two items belong
to the operator, not to a new research track — (a) the Experimental
exit-lifecycle gap (§Part 4) should be fixed in the live codebase before
any Experimental profitability claim is attempted, and (b) the Original
pre-open warm-up gap (§Part 3) should be watched during today's actual
regular session to determine whether it is a live-session-relevant defect
or a self-resolving pre-open transient — neither requires a new backtest.

## Explicitly not promised

No win-rate or profitability figure is promised for any lane. No strategy
is promoted from the small (N=10) or previously-inspected (Task 116/112R
window) samples examined in this task. The Task 117 controlled activation's
successful Telegram delivery (message IDs 720/721) is a **product** result
(delivery works) — it is not, and is not presented here as, a **trading**
result.
