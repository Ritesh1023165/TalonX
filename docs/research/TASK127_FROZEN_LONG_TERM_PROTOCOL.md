# Task 127 — frozen long-term 52-week-high protocol

Written and committed BEFORE `research/scripts/task127_52wk_high_evaluation.py`
is run against any real return outcome. Only the data-availability
probes cited in §1/§4 (symbol coverage, date ranges, split-continuity —
no return, no trigger, no P&L) were inspected before this freeze.

## Part 2 — source verification (George & Hwang 2004) and prior-research comparison

**Primary-source-grounded methodology**, verified via the publisher
record (Wiley, *Journal of Finance* 59(5), 2145–2176) and corroborating
searches of the paper's own reported design (not inherited from Task
122/126's paraphrase without re-checking):

- **Ranking measure**: `nearness = close_t / max(close over the trailing
  252 trading days, inclusive of t)` — the "52-week high" ratio.
- **Portfolio construction**: **TERCILE**, not decile — the paper sorts
  stocks into thirds; the top 30% (nearest to their own 52-week high)
  form the equal-weighted "Winner" portfolio, the bottom 30% form the
  "Loser" portfolio, headline result is the long-short spread.
  **Correction to Task 122/126's inherited description**: those
  documents called this a "decile" sort — verified here to be a
  **tercile (30%)** sort; corrected in this task's own contract below.
- **Formation frequency**: **monthly**, with Jegadeesh-Titman
  (1993)-style **overlapping portfolios** — in any given calendar
  month, the realized return is the average across the (up to) 6
  cohorts formed in that month and the preceding 5 months, each still
  within its own 6-month hold.
- **Holding period**: **6 months** is the paper's headline, most-cited
  reported test (other horizons are examined but 6 months is the
  standard J-T-style K=6 report and the one carried forward here — not
  chosen from a menu after seeing any TalonX result).
- **Universe/filters**: NYSE/AMEX/NASDAQ common stocks; **price ≥ $5**
  at formation (a microstructure filter, explicitly reused below).
- **Weighting**: equal-weighted within each portfolio.
- **Headline magnitude**: an average ~2.99% return over 6 months for
  the long-short (Winner-minus-Loser) SPREAD.
- **What the published result actually establishes**: that 52-week-high
  proximity, as a cross-sectional ranking variable across a broad,
  liquid multi-thousand-stock universe, dominates and subsumes the
  forecasting power of ordinary past-return momentum for the SPREAD
  between near-high and far-from-high stocks. **It does not, by
  itself, establish that the long (Winner) leg outperforms a passive
  long-only benchmark of the same universe** — the paper's headline
  number is a spread, and this task does not assume that magnitude, or
  even its sign, transfers to a long-only comparison. That comparison
  is what this task's own benchmark step (§6 of the results document)
  computes directly, not what is assumed from the citation.

**Prior TalonX research — genuine comparison, not a re-citation**:
`results/task95b_swing_foundation/momentum_analysis.md` (release
worktree, read directly this task) tested, among 9 Family-A momentum
cuts, **"within 2% of the prior 20-DAY high"** at a **3–5 TRADING DAY**
forward horizon, and found it the WORST-performing cut in the family:
net excess **−26.6 to −36.6bps**, explicitly logged as "proximity-to-
breakout underperforms." This is the closest existing TalonX finding
to a 52-week-high candidate, and it is taken seriously here, not
waved away — but it is **not the same measure at the same horizon**:
(a) a 20-trading-day high (~1 month) is a fundamentally different,
much noisier reference point than a 252-trading-day (~1 year) high —
George & Hwang's own central claim is specifically that the LONG
(52-week) anchor dominates shorter/generic momentum measures, which is
exactly what Task 95B's short-window cut was NOT testing; (b) a 3–5
trading-day hold is a different economic regime (short-horizon mean
reversion, which Task 95B's own broader results independently confirm
across its momentum family) from a 6-CALENDAR-MONTH hold. This is a
genuinely distinct, not-yet-tested hypothesis at this specific
anchor-window/horizon combination — not an "economically equivalent
contract already evaluated," so it is not reused as a decision without
running the actual test.

**`docs/RESEARCH_STATUS.md`'s "not reopened" clause** (broad
price/volume cross-sectional ranking, "signal wall") requires "a
materially new data or feature class... and a separate authorised
mandate — not a parameter sweep" to reopen. Task 127's own explicit
authorization — *"This task authorizes a research-only multi-month
holding contract"* — is read here as exactly that separate mandate:
every prior closed TalonX price/volume study (93–101B, 95B, 95E/95G)
tested short/swing/intraday horizons; none tested a 6-CALENDAR-MONTH
hold. The horizon itself, grounded in George & Hwang's own specific
published design, is treated as the materially new dimension — stated
explicitly here as the basis for proceeding, not silently assumed.

**Changes needed for a configured-universe, long-only implementation**
(and why each remains a coherent hypothesis, not an arbitrary
departure):
1. **Drop the short leg** — TalonX is long-only by product design
   (Part 1 correction #4/updated contract). This tests only the
   Winner-portfolio-vs-benchmark comparison the source paper's own
   spread construction does not directly answer — a real, disclosed
   narrowing of the claim, not a re-parameterization.
2. **38 covered names instead of thousands** — the tercile RANKING
   CONSTRUCTION itself is preserved unchanged (top 30% by the same
   ratio, equal-weighted); only the population size shrinks. A ~38-name
   pool's top 30% is ~11–12 names, still a meaningful cross-section for
   a tercile sort (not compressed to an ad hoc absolute threshold, the
   alternative Task 122 had speculated might be needed) — chosen here,
   before outcomes, as the SOURCE-GROUNDED choice per this task's own
   "select one using the source and product simplicity" instruction.
3. **No adjustment to the 6-month holding period** — reused exactly as
   published, per this task's explicit instruction not to shorten it
   for faster feedback.

## Part 3 — the frozen contract

### Universe, snapshot, and historical-membership limitation

- **38 configured, currently-ACTIVE tickers** with existing daily-bar
  coverage (identical set to Task 123's `ACTIVE_COVERED_38`,
  re-verified this task): AAPL, ABCL, ABT, ACHR, ADC, ADP, AFL, AGNC,
  AMAT, AMD, AVGO, BAC, BLK, C, CSCO, CVX, DELL, GOOGL, IBM, INTC, JNJ,
  JPM, KO, MA, MCD, MSFT, MSTR, NUE, NVDA, ORCL, PG, PYPL, STX, TSLA,
  UNH, V, VRT, WMT.
- **Snapshot**: today's (2026-09-13) `watchlist_coverage` active/paused
  status — used only to scope which symbols' historical series are
  relevant to check, **not** a claim that these 38 names were
  configured or tradable at any past date. This is a REAL,
  MATERIAL survivorship limitation: the universe is "today's watchlist
  projected backward," not a true point-in-time historical universe —
  a name that would have been dropped from a hypothetical past
  watchlist for poor performance is invisible here by construction.
  Disclosed prominently, not a footnote.
- **Data source, precedence**: `task95g_broad_cross_sectional/_daily`
  (D1, checked first) — 33 of the 38, 2019-06-03→2026-08-14; fallback
  `task107a_form4_feasibility/_prices` (D2) — 5 of the 38 (ADC, AGNC,
  MSTR: full range 2019-01-02→2026-08-31; **ABCL, ACHR: shorter
  history, starting 2020-12-11 and 2020-12-18 respectively** — genuine
  later listings, not a data gap, handled by the eligibility rule
  below, never backfilled).
- **Adjustment**: Alpaca SIP `adjustment=all` (split+dividend
  back-adjusted, a total-return proxy) — the SAME convention used for
  both the selected-portfolio prices and the benchmark prices, so
  dividends are embedded once, consistently, on both sides (verified
  in §4).
- **Benchmark data**: SPY, `task107a_form4_feasibility/_prices/SPY.csv`
  (same provider/adjustment convention), 2019-01-02→2026-08-31.

### Signal, ranking, eligibility

- **Formula**: `nearness_t = close_t / max(close_{t-251..t})` (252
  trading days inclusive of t) — causal, uses only information through
  and including day t's own close.
- **Eligibility filter** (per symbol, per formation date): at least
  252 trading days of the SYMBOL'S OWN available history as of that
  date, AND `close_t >= $5.00` (reusing George & Hwang's own
  microstructure filter exactly).
- **Minimum eligible population**: at least **15** eligible symbols
  required to form a cohort that month; if fewer, that month is
  skipped and recorded (`insufficient_eligible_population`), never
  filled with an ineligible name.
- **Selection**: TERCILE — rank eligible symbols by `nearness_t`
  descending; select the top 30% (rounded to nearest whole symbol,
  minimum 1), equal-weighted within the cohort.

### Decision schedule, causal entry, holding, exit

- **Decision date**: the LAST trading day of each calendar month —
  information available: all OHLCV through and including that day's
  own close, for every eligible symbol.
- **Earliest causal reference entry**: the OPEN of the FIRST trading
  day of the FOLLOWING calendar month — never the same month-end close
  the ranking was computed from (no same-close execution on
  information finalized at that close).
- **Holding/review period**: **6 calendar months**, reused exactly
  from George & Hwang's own headline test — not shortened, not
  searched.
- **Exit**: the OPEN of the first trading day of the calendar month
  that is 6 months after the entry month (e.g., entry month M → exit
  at the open of month M+6's first trading day).
- **Overlapping cohorts**: a new cohort forms every month; each holds 6
  months, so up to **6 cohorts** may be concurrently open. This is the
  source's own J-T-style overlapping-portfolio design, reused exactly
  — reported explicitly, not collapsed into a single non-overlapping
  backtest.
- **Repeat selection**: a symbol selected in consecutive months
  appears in multiple concurrently-open cohorts independently — no
  special-casing, matching the source's own treatment (this is a
  standard, disclosed feature of overlapping-portfolio momentum
  studies, not a bug).

### Position sizing and capital budget

- **Total paper capital budget**: $100,000 (a simple, round figure
  consistent with the order of magnitude used elsewhere in this paper-
  trading research program).
- **Allocation**: 1/6 of the total budget per concurrently-open cohort
  SLOT (whether or not all 6 slots are yet filled — during the first 5
  months of the evaluation window, fewer than 6 cohorts exist yet;
  this ramp-up is disclosed, not hidden or backfilled with invented
  early cohorts).
- **Within a cohort**: equal-weighted across that cohort's own selected
  names.

### Costs and adverse-cost sensitivity

- **Base cost**: 5bps round-trip (`apply_spread`'s existing formula, the
  SAME convention used in Tasks 120–126), applied exactly once per
  entry+exit pair.
- **Predeclared adverse-cost sensitivity**: **15bps round-trip** (3× the
  base — a plausible additional-friction scenario), reported alongside
  the base-cost result, not chosen after seeing it.

### Missing data, splits, dividends, delisting

- **Missing bars**: a symbol lacking a required decision/entry/exit bar
  on its exact date is excluded from that specific cohort/period and
  counted by cause — never forward-filled or substituted.
- **Splits**: verified (§4) to be handled correctly by `adjustment=all`
  — no separate correction applied; the eligibility/ranking computation
  uses the same continuous adjusted series throughout.
- **Dividends**: embedded via `adjustment=all`'s total-return
  back-adjustment, identically for the strategy and both benchmarks —
  not separately added, not double-counted.
- **Delisting**: **this panel has no delistings by construction** — it
  is today's currently-active 38 names, not a historical point-in-time
  universe. This is exactly the survivorship limitation disclosed
  above, not a separate mechanism needing handling; a genuinely
  point-in-time-correct version of this study is out of scope for this
  task (it would require the broader delisting-aware panel Task 95F/G
  already built for a DIFFERENT, closed hypothesis — reusing that
  panel for this new hypothesis is not attempted here to keep this one
  contract source-grounded and bounded, and is named as a limitation,
  not silently worked around).

### Benchmarks and primary estimand

- **Benchmark 1 — eligible-universe equal-weight**: the same monthly
  eligibility rule (252-day history, price ≥ $5), but WITHOUT the
  tercile selection — every eligible symbol equal-weighted, same
  6-month overlapping-cohort construction. Isolates whether SELECTION
  (proximity to 52-week high) adds anything beyond simply being long
  the eligible universe.
- **Benchmark 2 — SPY buy-and-hold**: SPY's own realized return over
  the SAME calendar windows as each cohort. A simple external market
  comparison.
- **Primary estimand**: mean 6-month realized NET portfolio return of
  the selected (top-30%) strategy, across all cohorts with a COMPLETE
  (realized) 6-month forward window, compared incrementally against
  Benchmark 1 over the identical windows.

### Uncertainty and materiality

- **Uncertainty method**: **non-overlapping 6-month block bootstrap** —
  the full evaluation window is divided into non-overlapping,
  consecutive 6-calendar-month macro-blocks; the REALIZED
  (overlapping-cohort-blended) portfolio return achieved during each
  block is treated as ONE dependent unit; these block-level returns are
  resampled with replacement (5,000 reps, seed **127127**, 95%
  percentile CI). This explicitly acknowledges that individual cohort
  trades are NOT independent observations (they share holding-period
  market dates and overlapping stock membership) — the number of
  monthly cohorts is not the number of independent observations; the
  number of non-overlapping macro-blocks is the honest count.
- **Materiality**: **±10bps** on the incremental (selected-vs-Benchmark-1)
  6-month estimate — 2× the 5bps round-trip base cost, the SAME
  doubling convention used throughout this program (Tasks 121B, 123,
  125), applied here to the incremental 6-month figure. Disclosed as a
  SMALL band relative to plausible 6-month return volatility at this
  horizon — appropriate for cost-plausibility, not a claim that the
  full 6-month spread must be "real friction."

### Statistical and product acceptance criteria (fixed before outcomes)

**Statistical**:
- `SUPPORTS_PREDECLARED_EFFECT` — the incremental 95% CI excludes zero,
  entirely positive, AND the point estimate clears the ±10bps
  materiality band.
- `DOES_NOT_SUPPORT_PREDECLARED_EFFECT` — the incremental 95% CI
  excludes zero, entirely negative.
- `INCONCLUSIVE` — the CI includes zero, OR excludes zero but does not
  clear materiality.

**Product** (requires BOTH the statistical verdict above AND an
absolute-return check, per this task's own explicit instruction that
"positive absolute returns during a rising market alone do not justify
a more complex selection strategy" and the converse — a positive
incremental riding on negative absolute economics is not sufficient):
- `ADVANCE_TO_FURTHER_VALIDATION` — statistical `SUPPORTS_PREDECLARED_EFFECT`
  AND the selected portfolio's own absolute mean net 6-month return is
  positive and economically non-trivial (clears the same ±10bps band
  on an absolute basis).
- `DO_NOT_ADVANCE` — statistical `DOES_NOT_SUPPORT_PREDECLARED_EFFECT`,
  OR `SUPPORTS_PREDECLARED_EFFECT` without a positive, economically
  credible absolute return.
- `BLOCKED_BY_SPECIFIC_EVIDENCE_REQUIREMENT` — used only if the
  eligibility funnel or corporate-action verification reveals a
  specific, named defect preventing a trustworthy estimate — not for a
  merely small or inconclusive sample.

### Exploratory-vs-unexamined status

The full available window (2019-06 warmup-adjusted onward) has NOT been
examined for THIS specific hypothesis (52-week-high tercile selection,
6-month hold) in any prior TalonX task — Task 95B's closest test used a
different anchor window (20-day, not 252-day) and horizon (3–5 day, not
6-month). This remains a single, EXPLORATORY frozen run — consistent
with this program's standing convention, no train/confirmation split is
claimed, and no untouched confirmation window exists within this same
dataset.

### Stopping rule

Run once, this exact frozen contract, over the full available window.
No search over ranking fraction, holding period, formation frequency,
or ticker subset within this task.
