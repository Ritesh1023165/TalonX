# Task 127 Part 1 — correcting Task 126's product record

Task 126's original conclusions (`TASK126_CANDIDATE_SELECTION.md`,
`TASK126_ECONOMIC_DECISION.md`) are **not deleted**. The corrections
below are appended, dated, and this document is the authoritative
record of what changed and why.

## Corrections

1. **The absence of a current multi-month TalonX strategy is not a
   prohibition on long-term alerts.** Task 126's Candidate A analysis
   treated "no existing TalonX strategy holds anywhere near 6-12
   months" as evidence the horizon itself was unauthorized. That
   inference is withdrawn: an absent precedent is a gap to fill, not a
   rule against filling it. `PRODUCT_STATUS.md`'s own objective —
   *"configured tickers with intraday and short/long-horizon alerts"*
   — already names long-horizon alerts as in scope; what was missing
   was an actual long-horizon candidate, not permission for one. This
   task supplies that candidate.

2. **Paper positions do not lock the user's real capital — but
   allocation and opportunity cost inside the simulated portfolio
   still matter.** Task 126 did not make this error explicitly, but
   its framing ("a materially different commitment than any strategy
   tested") implicitly conflated capital-lockup risk with holding-
   period length. Corrected: a paper 6-month hold costs the user
   nothing in real capital. It DOES still need honest simulated-
   portfolio accounting — a paper dollar committed to a 6-month
   position cannot also be counted toward a second position, and the
   OPPORTUNITY COST of that paper allocation (what a benchmark would
   have returned over the same window) is exactly what this task's
   benchmark comparison measures. The capital-lockup language is
   withdrawn; the accounting discipline is not.

3. **Ticker-specific differentiation was never a stated user
   requirement — it was this research program's own inferred
   product-fit heuristic.** Task 126 treated turn-of-month's lack of
   per-ticker differentiation as an automatic, structural
   disqualifier. Re-reading the actual user objective
   (`PRODUCT_STATUS.md`: *"configured tickers with ... alerts ...
   attributable local paper portfolios"*), nothing in it explicitly
   requires every alert to differ by ticker — that was this program's
   own interpretive gloss, applied too rigidly. **This correction does
   NOT reopen or evaluate turn-of-month in this task** (explicitly out
   of scope per this task's own instruction) — it only withdraws the
   overstated certainty of Task 126's reasoning, for the record, so a
   future task is not blocked by an inference this task now disclaims.
   Turn-of-month's product verdict (`DO_NOT_ADVANCE`) itself is
   unchanged and unre-evaluated here.

4. **Task 126 asserted turn-of-month was rejected "not on statistical
   or economic evidence" — that framing is accurate and preserved.**
   For clarity and to prevent future misreading: turn-of-month was
   **never economically evaluated or disproven** by this research
   program. No return was computed for it in Task 122, 126, or here.
   Its `DO_NOT_ADVANCE` verdict is a product-fit judgment only, now
   itself qualified by correction #3 above — it remains closed for
   THIS task's purposes, but it is not evidence of the mechanism's
   economic failure, and must never be cited as such.

5. **"Full coverage" requires a named ticker population and date
   range — restated precisely here rather than left implicit.** Task
   122/126 used "full existing coverage (35/48 or 38/48)" loosely.
   This task names the exact set: **38 configured, currently-active
   tickers** with existing daily-bar coverage (union of
   `task95g_broad_cross_sectional/_daily`, D1-precedence, and
   `task107a_form4_feasibility/_prices`, D2-fallback — the SAME 38-name
   set Task 123 already used and named, re-verified this task, see
   `TASK127_FROZEN_LONG_TERM_PROTOCOL.md` §1), each with its own
   specific first/last available date — NOT a single blended range
   asserted for the whole universe.

6. **Corporate-action handling is verified in this task, not described
   as trivial.** Task 122's Hypothesis 2 writeup called corporate-
   action handling for this candidate "same data, no separate handling
   needed" without checking it. This task directly verified (not
   asserted) that Alpaca `adjustment=all` daily bars show a
   **continuous, non-discontinuous price series** through both of the
   two confirmed 2024 stock splits already found in this program's
   data (AVGO 2024-07-15, NVDA 2024-06-10 — see Task 125's
   `data_acceptance.json`) — the same `adjustment=all` convention used
   for both the strategy's selected names and its benchmark, so
   dividends are embedded consistently on both sides and not
   double-counted. See §4 of `TASK127_FROZEN_LONG_TERM_PROTOCOL.md`
   for the full verification.

## Updated product contract (concise)

- **Long-term opportunities may use a multi-month research horizon.**
  This is now an explicit, standing product allowance — not
  conditioned on an existing strategy already using one.
- **BUY/SELL alerts must have a defined decision, entry, holding/
  review, and exit policy.** Every candidate strategy — short or long
  horizon — states all four explicitly before any return is computed.
- **SELL closes an existing long; no short selling anywhere in this
  product.** Unchanged, reaffirmed.
- **An evaluation does not authorize live deployment or promise
  profitability.** A passing `ADVANCE_TO_FURTHER_VALIDATION` verdict
  means one further validation step — never activation, never a
  profitability claim, exactly as every prior task in this program has
  treated it.

Turn-of-month is **not** evaluated in this task, per explicit
instruction. This task proceeds to define and evaluate one
source-grounded, long-only 52-week-high candidate under the corrected
product contract above.
