# Task 126 — product-fit selection between the two remaining Task 122 candidates

## Part 1 — closing Task 125 without another rerun

Corrections appended (stored-artifact-only, no rerun) to
`docs/research/TASK125_OVERNIGHT_ACTIONABLE_RESULTS.md` and
`docs/task_journal/entries/2026-09-13_task125_extended_intraday_evaluation/outcome.md`
— reproduced here for completeness:

- **Statistical verdict remains `INCONCLUSIVE`; product verdict remains
  `DO_NOT_ADVANCE`.** Neither is reopened by this task.
- **"Confirmed negative edge" is unsupported and is withdrawn** as a
  description of Task 125's result. Every cohort's 95% CI (Cohort A:
  [−0.7946%,+0.3458%]; B: [−0.4970%,+1.0535%]; C: [−0.6333%,+0.3531%];
  D: [−2.1445%,+1.2090%]) includes zero. The expanded, feed-verified
  test **retained negative point estimates** across a materially
  larger sample (3,201 vs. 579 observations, 542 vs. 100 distinct
  dates, 3 calendar years vs. 7 months) **without establishing a
  statistically negative underlying expectancy** — repeated,
  larger-sample testing failed to find supporting evidence for a
  positive effect; it did not prove a negative one.
- **The ±50% extreme-return guard is not complete corporate-action
  handling.** It correctly caught the one AVGO/NVDA split-driven
  overnight-return discontinuity in-sample, but two related
  limitations remain: (1) a stock split also distorts the same-time-
  of-day cumulative-volume TRIGGER for the ~20 sessions surrounding
  it (already noted in `TASK125_FROZEN_EXTENSION_PROTOCOL.md` §3, not
  repeated prominently enough in the results document), and (2)
  **dividends are not adjusted for at all** under the raw-price
  convention Task 125 used — an ex-dividend overnight return is
  reported as a real gain/loss of that magnitude, uncorrected; the
  guard does nothing to address this (a dividend-sized move is far
  too small to trip a ±50% threshold).
- **Eligible dates, trigger dates, and bootstrap resampling blocks are
  three different counts.** For Cohort A: 3,201 eligible observations
  span 542 distinct calendar dates (the bootstrap's resampling-block
  count — ALL eligible dates, trigger or not, since the control
  population is drawn from the same dates); of those 542 dates, only
  117 are trigger dates. `n_dates=542` in the machine-readable output
  is the eligible-date count, not the trigger-date count.

The overnight-attention actionable contract **stays closed**. No part
of Task 125 was rerun to produce these corrections.

---

## Part 2 — product-fit gate applied to both remaining candidates

Read: `docs/research/TASK122_CANDIDATE_DECISION.md` Part 3 (Hypotheses
2 and 3), `docs/RESEARCH_STATUS.md`'s "not reopened" list, the George &
Hwang (2004) and McConnell & Xu (2008) primary sources (as characterized
in Task 122's own citation work — abstracts/methodology re-verified via
the same citation search this program already performed, not
re-litigated with a new literature review), and
`docs/research/PRODUCT_STATUS.md`'s current stated objective:
*"configured tickers with intraday and short/long-horizon alerts, and
attributable local paper portfolios."*

### Candidate A — 52-week-high proximity (George & Hwang 2004, JF 59(5))

| field | finding |
|---|---|
| Exact mechanism the source studies | Cross-sectional **decile-sorted, long-short** portfolios ranked by `price / 252-trading-day rolling high`; the TOP decile (closest to its own 52-week high) outperforms the BOTTOM decile; this measure dominates generic past-return momentum as a predictor. |
| Shorting / cross-sectional ranking / different universe | **Requires all three** in the published construction: the headline effect is a long-short SPREAD, computed via decile rank across the FULL NYSE/AMEX/NASDAQ common-stock universe (thousands of names), rebalanced monthly. |
| Signal availability / earliest causal entry | Trivial and fully causal: a 252-trading-day rolling max of (adjusted) close, known at each day's own close — no lookahead risk in the SIGNAL itself. |
| Intended holding period (published) | **6–12 months**, formation-then-hold, monthly rebalance. |
| Ticker-specific alerts vs. common calendar exposure | Genuinely ticker-differentiating — each name's own distance from its own 52-week high is independent information, not a calendar-wide signal. |
| Distinction from previously tested/rejected TalonX contracts | Behaviorally distinct from Task 95B's short-horizon (3–10 day) breakout study (anchoring to a salient REFERENCE price vs. generic recent-return momentum) — genuinely a different construct, not a re-parameterization. **However**, Task 95B's own finding — short-horizon price/volume breakout patterns are NEGATIVE-excess, mean-reverting at 2–3 days — is a specific, on-point reason to doubt any SHORT-horizon compression of this mechanism would survive, precisely because the published edge has never been validated below 6 months. |
| Existing-data coverage / corporate-action requirements | Full: `task95g_broad_cross_sectional/_daily` (Alpaca SIP, `adjustment=all`) covers 35/48 configured tickers with the full history needed for a 252-day rolling high; `adjustment=all` already handles the split/dividend consistency a raw rolling-high computation would otherwise corrupt. |
| Appropriate simple benchmark | Equal-weighted buy-and-hold of the same 35-ticker covered universe (or SPY) over the same window. |
| Implementation changes needed to translate into a long-only configured-ticker product | **Two independent, unvalidated adaptations, not one**: (1) replacing cross-sectional decile-rank-across-thousands-of-stocks with an ABSOLUTE proximity threshold (e.g. "within X% of the 252-day high") — a defensible, disclosable simplification for a 48-name universe, but not what the source paper measured; AND (2) inventing an entirely new, TalonX-specific SHORT holding period and exit rule, since the source specifies none below 6 months. |

**Gate result**: FAILS on holding-period compatibility. TASK126's own
instruction is explicit: *"If a candidate requires an unsettled
horizon choice, make that an explicit product decision rather than
inventing a convenient shorter holding period."* This candidate
requires exactly that unsettled choice — `PRODUCT_STATUS.md`'s
"short/long-horizon alerts" phrasing is NOT read here as already
authorizing a 6–12-month, capital-locked holding commitment (per this
task's own explicit warning against that exact silent redefinition).
No existing TalonX strategy (Original, Experimental, V2 at 10 trading
days, or the now-closed overnight-attention candidate) holds anything
close to 6–12 months. Compressing the horizon to fit would be
inventing an unvalidated hypothesis, not testing the published one —
and would revisit the specific short-horizon mean-reversion finding
Task 95B already established as a rejection risk in this exact zone.

### Candidate B — turn-of-month calendar effect (McConnell & Xu 2008, FAJ 64(2))

| field | finding |
|---|---|
| Exact mechanism the source studies | Aggregate market/index returns (CRSP value- and equal-weighted, and 31/35 countries examined) are abnormally concentrated in the ~4 trading days around each calendar month's turn (last trading day of month through the 3rd trading day of the new month, per the paper's own window definition) — an AGGREGATE, market-wide effect, explicitly shown NOT explained by month-end fund flows or volume. |
| Shorting / cross-sectional ranking / different universe | **Requires none of these** — the mechanism is a pure calendar-timing rule (be long during the TOM window, flat/out otherwise), applicable per-instrument without any relative ranking or short leg. This is the most direct long-only translation of any of the three shortlisted hypotheses. |
| Signal availability / earliest causal entry | Trivial and fully causal — calendar dates are known arbitrarily far in advance; zero lookahead risk. |
| Intended holding period (published) | Short and well-specified: ~4 trading days per month — compatible with TalonX's existing short/swing-horizon product shape, unlike Candidate A. |
| Ticker-specific alerts vs. common calendar exposure | **Fails this dimension structurally.** The source mechanism is, by its own construction, a single calendar rule applied identically across an entire portfolio/index — translated to the 48 configured tickers, it fires on the SAME ~4 days, for EVERY name, EVERY month, with zero ticker-specific differentiation. Applying it to 48 specific tickers uses none of those tickers' own individual information; the same signal would apply equally to any diversified basket. |
| Distinction from previously tested/rejected TalonX contracts | Genuinely novel feature class (calendar, not price/volume/text/insider) — zero overlap with any item on `docs/RESEARCH_STATUS.md`'s "not reopened" list. |
| Existing-data coverage / corporate-action requirements | Full and trivial — needs only existing daily close-to-close bars (`adjustment=all`) for the configured universe; no special corporate-action risk beyond the standard total-return-proxy convention already used throughout this program. |
| Appropriate simple benchmark | Same tickers' own non-TOM-day daily returns, or a buy-and-hold benchmark. |
| Implementation changes needed to translate into a long-only configured-ticker product | Mechanically trivial — the calendar window is exactly and unambiguously specified by the source (no threshold to invent, no horizon to compress). The only "change" needed is deciding whether a common, non-differentiating exposure is an acceptable alert TYPE for this product — a product-shape question, not an implementation one. |

**Gate result**: FAILS on ticker-specific-alert product fit. The
product's own stated purpose is *configured TICKERS with... alerts* —
implying the point of naming 48 specific tickers is that alerts
differentiate between them. A mechanism that, by construction, treats
every configured ticker identically every month is not using any
ticker-specific information at all; it is a portfolio-level calendar
rule expressed as 48 simultaneous, identical alerts. This is the same
concern Task 122 already flagged as this candidate's primary weakness
("does not match 'timely, useful ALERTS' per ticker in any
differentiating sense") — re-examined here in full per this task's own
instruction, not merely re-cited, and confirmed on the same structural
grounds: this is a genuine, disclosed, non-performance-based product-
fit failure, not an implementation detail that a simplification could
route around without inventing a new (out-of-scope) hybrid mechanism.

---

## Part 3 — selection

### Selection matrix (mechanism, product fit, prior-research overlap, data feasibility — before any return was inspected)

| criterion | A. 52-week-high | B. turn-of-month |
|---|---|---|
| Mechanism transfers to long-only without shorting/cross-sectional-ranking-across-thousands | Requires adaptation (absolute threshold, novel) | Transfers directly |
| Ticker-specific, differentiating alert | Yes | **No — common calendar exposure** |
| Holding period compatible with an EXISTING, already-authorized TalonX horizon | **No — published 6–12mo, no TalonX product mandate for that** | Yes — ~4 days, matches existing short-horizon shape |
| Zero overlap with previously rejected TalonX work | Partial (adjacent to Task 95B's rejected short-horizon zone specifically because THIS candidate would need a short horizon) | Yes — new feature class |
| Existing-data coverage adequate | Yes | Yes |
| Translatable WITHOUT inventing an unvalidated design choice | **No — needs both a new ranking construction AND a new, unvalidated holding period simultaneously** | Yes — calendar window is exactly specified, no tuning needed |

Candidate A fails on the two hardest-to-work-around dimensions
(holding period AND ranking-construction, stacked); Candidate B fails
on exactly one, but that one — ticker-specific differentiation — is
the core structural premise of a "configured-ticker alert" product,
not a peripheral detail.

### Decision: **`NO_CANDIDATE_PASSES_PRODUCT_AND_DATA_GATES`**

Neither candidate is selected for evaluation in this task.

- **Candidate A (52-week-high)** is **BLOCKED_BY_SPECIFIC_PRODUCT_OR_DATA_REQUIREMENT**:
  it requires an explicit product decision — whether TalonX will
  support a long-hold (multiple-month), capital-locked alert type, a
  materially different commitment than any strategy this program has
  ever tested (Original/Experimental: intraday; V2: 10 trading days;
  overnight-attention: overnight-only) — which this research-only task
  is not authorized to invent on its own, per this task's own explicit
  instruction against silently redefining "short/long-horizon" as a
  six-to-twelve-month mandate. **Smallest requirement that must
  change**: a product decision, made outside this research task,
  either (a) authorizing a defined long-hold alert horizon (with its
  own capital/UX implications disclosed), which would then let a
  future task test the published 6–12-month construction faithfully,
  or (b) explicitly accepting that any shorter-horizon version is a
  genuinely NOVEL, unvalidated-by-literature hypothesis, to be
  disclosed as such rather than presented as a literature-grounded
  test.
- **Candidate B (turn-of-month)** is **`DO_NOT_ADVANCE`** on product-fit
  grounds alone, before any economic computation: it does not produce
  ticker-specific alerts, only a common calendar-wide exposure across
  the entire configured universe — a structural mismatch with the
  product's own stated purpose, not a data or mechanism defect.
  **Smallest requirement that must change**: a product decision to
  accept a non-differentiating, scheduled full-book exposure toggle as
  a valid "alert" type for this product; absent that, this mechanism
  does not serve the product as currently defined.

Per this task's own instruction, no third hypothesis is invented, no
broad literature discovery is started, and no indefinite live-waiting
recommendation is made. This is a credible decision to stop, on
mechanism/product-fit/data grounds, consistent with the "credible
decision to stop is preferable to another unsupported candidate"
standard this research program has applied throughout.
