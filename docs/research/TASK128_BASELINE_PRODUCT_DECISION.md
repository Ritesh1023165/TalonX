# Task 128 Part 7/8 — user-visible product specification and bounded decision

## Part 7 — the smallest faithful paper-alert journey (specification only, nothing implemented)

Described AS THE ACTUAL TESTED CONTRACT (monthly formation, up to 6
concurrently-open, non-differentiated, equal-weighted 6-month cohorts
across the full eligible universe) — **not** silently simplified into
a single buy-and-hold or a monthly-rebalanced portfolio, which would be
a different, unvalidated contract (per this task's own explicit
instruction).

- **What causes an initial allocation recommendation**: at each
  calendar month-end, the eligible universe is recomputed (≥252
  trading days of own history, price ≥ $5, from the configured active
  tickers). If ≥15 names are eligible, ONE new-cohort recommendation
  fires: "allocate 1/6 of the paper budget, equal-weighted across
  these N eligible names, at tomorrow's — the first trading day of
  next month's — open."
- **What prompts a scheduled review**: **none, by the frozen
  contract's own design.** This is a fire-and-forget 6-month hold with
  no interim review, rebalance, or stop-loss trigger. This is stated
  plainly rather than inventing a review mechanism the tested contract
  does not have — adding one would be a materially different,
  unvalidated product.
- **What causes a rebalance or exit**: purely calendar-driven — each
  cohort exits automatically at the open of the first trading day
  exactly 6 months after its own entry. No price- or news-triggered
  exit exists in this contract.
- **Expected alert frequency (from the frozen schedule)**: once ramped
  (after ~13 months), approximately **one entry-batch event and one
  exit-batch event per calendar month** — roughly 24 batch events per
  year. Each batch event concerns MULTIPLE tickers at once (the full
  eligible set on entry, one cohort's own selected names on exit), not
  one alert per ticker — how to present a ~30-name batch (one summary
  message vs. per-ticker line items) is an open UX question this
  specification does not resolve.
- **What information each alert would contain**:
  - Entry batch: the list of eligible symbols, the per-symbol
    allocation notional, the reference entry price used (an observed
    subsequent open, not a guaranteed fill).
  - Exit batch: the specific cohort's symbols, entry vs. exit
    reference prices, realized gross/net P&L for that cohort, holding
    period completed (always exactly 6 months by construction).
- **How the paper portfolio/dashboard would represent it**: as up to 6
  concurrently-tracked monthly "vintage" sub-portfolios, each with its
  own entry date, basket, and maturity date, plus one blended aggregate
  view (cash + marked value across all open cohorts = total equity) —
  structurally similar to how the existing V2 dashboard already tracks
  multiple concurrent entries, grouped here by monthly vintage instead
  of by insider-cluster episode.

**This is a scheduled allocation/rotation mechanism, not a
bullish/bearish forecast.** No entry or exit carries any directional
conviction about a specific name — every eligible ticker receives the
identical treatment every month. Presenting a calendar-driven batch
allocation as if it were an evidence-based "we believe this ticker will
outperform" signal would misrepresent the mechanism; this specification
explicitly does not do that anywhere.

### Assessment

- **Does this help the user manage configured long-term tickers?**
  Partially. It provides a mechanical, diversified, disciplined entry/
  exit schedule for the configured universe — but it does NOT tell the
  user which tickers are more or less attractive right now (there is
  no selection at all in this specific contract; every eligible name
  is treated identically). It is closer to a "systematic rotation
  tracker" than a differentiated alert.
- **Is it materially more useful than a simple portfolio tracker?**
  **Marginal, and the evidence argues against it.** Part 5's fair,
  same-capital comparison showed Benchmark B1 underperforms simply
  buying and holding SPY with the identical starting capital by
  roughly **4.7 points of annualized return** (12.77% vs. 17.44%). The
  overlapping-cohort machinery's added complexity is not clearly
  earning its keep relative to the simplest possible alternative.
- **Is the multi-month holding commitment and drawdown visible?** Yes,
  and now precisely quantified: a real, bounded, RECOVERED −19.58%
  drawdown over a 528-day recovery window (Part 4). Any real
  implementation would need to surface this drawdown/recovery profile
  prominently, not just a headline return figure.
- **Can it coexist with the still-unresolved intraday goal without
  being presented as its solution?** Yes — this is an entirely
  separate product surface (a multi-month paper allocation tracker,
  not an intraday trading signal) and must never be presented as
  solving or substituting for the still-open intraday objective
  (Original/Experimental both remain `INSUFFICIENT_EVIDENCE`/archived).

## Part 8 — bounded product decision

> **`USEFUL_AS_TRACKING_BENCHMARK_ONLY`**

**Reasoning, keeping historical economic evidence separate from
product usefulness**:

- **Historical evidence**: genuinely positive absolute economics over
  the one exploratory window tested (+12.77% annualized, a real,
  bounded, recovered drawdown) — but this is not evidence of a
  differentiated edge; it is consistent with broad market exposure
  during a strong bull run (Part 1 correction), and it materially
  UNDERPERFORMS the simplest passive alternative available with the
  identical capital (SPY, same dates: +17.44% annualized).
- **Product usefulness**: Benchmark B1 has **no selection mechanism by
  its own design** — it is, and was always intended to be, the
  "no-selection" CONTROL against which Task 127's actual candidate
  (tercile selection) was judged. It is not, and does not become
  through this task's more rigorous accounting, a standalone
  differentiated alert product: it does not identify which configured
  tickers deserve more or less attention, and it does not beat the
  simplest alternative a user could take instead.
- This does **not** meet the bar for `BASELINE_READY_FOR_FORWARD_PAPER_VALIDATION`
  (that would require it to be a credible standalone candidate for
  eventual activation review — it is not, given the SPY gap and the
  complete absence of differentiation).
- This is **not** `DO_NOT_ADVANCE` in the sense of being discarded
  entirely — the corrected, now-daily-marked, now-cash-reconciled
  chronological implementation built in this task IS genuinely useful,
  specifically as the reusable, trustworthy benchmark construct for
  judging any FUTURE long-term-horizon candidate (exactly the role it
  already played for Strategy A in Task 127, now on firmer accounting
  footing).
- This is **not** `BLOCKED_BY_SPECIFIC_ACCOUNTING_OR_DATA_LIMITATION`
  — the accounting itself is now verified and trustworthy (4 passing
  fixture tests, the one insufficient-cash guard firing correctly on
  real data, cash never negative, drawdown/recovery correctly computed
  from the actual daily marked-equity path).

### One next action

Continue using this task's corrected, daily-marked, cash-reconciled
`run_chronological_portfolio_daily` implementation (reused, not
rebuilt) as the standard no-selection benchmark for any future
long-term-horizon candidate evaluation in this research program — this
IS the useful outcome of this task. Do **not** productize Benchmark B1
itself as a standalone user-facing paper-alert offering, and do **not**
advance it to forward paper validation as a strategy in its own right.
No new parameter search, no new literature shortlist, and no
indefinite live-observation programme are proposed — this is a
methodological reuse decision, not a new hypothesis.
