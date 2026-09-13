# Task 122 — close Experimental evaluation, select one new candidate

## Part 1 — closing Task 121B (no rerun)

### Two separate verdicts

**Statistical verdict**: `INSUFFICIENT_EVIDENCE` — under Task 121B's own
predeclared, symmetric ±$1.25/trade materiality rule, the 95%
issuer-block bootstrap CI on `EXPERIMENTAL_RELAXED_V1`'s net $/trade
(**[−$8.94, +$1.06]**, N=227, 35 issuers) does not clear the band in
either direction. The rule is **not rewritten after seeing this
result** — it was fixed in `TASK121B_EXTENDED_PROTOCOL.md` before the
full-Segment-A run executed, and it stands exactly as written.

**Product verdict**: **`DO_NOT_ADVANCE_CURRENT_EXPERIMENTAL_CONTRACT`**
— a separate, additional conclusion, not implied automatically by the
statistical one. Reasoning:

- **Negative gross and net observed results**: gross P&L was
  **−$612.92** — negative BEFORE any modeled cost — and net was
  **−$896.44**. A contract whose raw signal geometry loses money before
  transaction costs are even applied is not a credible promotion
  candidate regardless of where a resampling confidence interval's edge
  happens to fall.
- **Adequate observed activity, no convincing economic edge**: 227
  trades across all 35 available symbols over 6.7 months is a real,
  substantial sample — this is not a "wait for more data" situation.
  The frequency question is answered (activity is adequate); the
  economics question is answered in the negative-leaning direction
  (PF 0.764, win rate 19.4%, mean −$3.95/trade), just not decisively at
  95% confidence.
- **The specific numeric fact**: the CI's upper bound, **+$1.06/trade**,
  sits **below** the predefined **+$1.25/trade** useful-edge threshold —
  meaning even the MOST OPTIMISTIC end of the 95% confidence interval
  does not reach the bar this research program itself set for "an
  effect large enough to plausibly survive real-world costs beyond the
  modeled 5bps spread." This is conditional on the issuer-block
  bootstrap estimator and its own assumptions (35 independent groups,
  resampling with replacement) — stated as a conditional fact, not an
  absolute one.
- **Failing the formal REJECT rule is not promotion license**: the CI
  also does not clear the bar for a clean statistical reject (its lower
  bound, −$8.94, does clear −$1.25, but the interval as a whole still
  touches slightly positive territory) — this asymmetry is reported
  honestly as `INSUFFICIENT_EVIDENCE` at the statistical level. It is
  **not**, however, license to keep re-running or promoting this exact
  contract: the product-level judgment above stands on the weight of
  the point evidence (negative gross P&L, PF<1, 19% win rate) rather
  than requiring the statistical bar to be crossed in either direction.
  Repeated re-evaluation of the SAME contract on the SAME now-exhausted
  dataset would not change this.

### Two reporting corrections (applied without a rerun)

1. **Execution sensitivity relabelled.** Task 121B's results called the
   next-bar-close fill sensitivity "chronologically propagated." That
   overstated the computation: shares/P&L were genuinely recomputed
   from the delayed price (not a constant subtraction), but the exit
   price/reason was held fixed and no downstream occupancy/cooldown
   effects on later candidates were re-derived. Corrected in
   `TASK121B_EXTENDED_EXPERIMENTAL_RESULTS.md` and
   `TASK121B_EXTENDED_PROTOCOL.md` to **"repricing sensitivity"** — the
   numbers (−$927.91 total, sign unchanged) are unaffected; only the
   characterization changes.
2. **Daily marked drawdown was never supplied.** `TASK121B_EXTENDED_EXPERIMENTAL_RESULTS.md`
   now states this explicitly: ending equity ($99,155.10) is a single
   point-in-time balance, not a peak-to-trough drawdown series, and must
   not be read as one. No drawdown figure is claimed anywhere for this
   study.

Both corrections are recorded as dated addenda to the existing Task 121B
documents (originals preserved) and in this task's own journal entry —
no part of the ~11.3-hour replay was rerun to produce them.

### Archival

`EXPERIMENTAL_RELAXED_V1`'s exact, unchanged, verified-wired contract
(entry at signal-bar close, `check_exits`-sampled stop/target-only exit,
no EOD flatten, no bearish-close — Task 121A/121B) is archived as an
**internal research baseline**: `docs/research/{TASK121A_PROVENANCE_AND_CONTRACT,
TASK121B_EXTENDED_EXPERIMENTAL_RESULTS}.md`, N=227/6.7-month result. It
is not deleted, not promoted, and not scheduled for further backtesting
on this exhausted dataset (per Task 121B's own named blocker). No
production component (the live Experimental lane, its external-send
gate, or any config) is touched by this research-only task.

---

## Part 2 — what a replacement candidate must achieve

**Product requirement (unchanged, from `PRODUCT_STATUS.md`)**:
configured tickers by horizon → timely, useful trading alerts →
attributable local paper portfolios → measurable economics after costs.
V2 (`INSIDER_BUY_CLUSTER_V2`) remains a sparse supplementary strategy
(39-name live scope, N=57, CI includes zero — Task 120A-C); Intelligence
remains informational (no BUY/SELL claim, ever). Neither substitutes for
a working trading-alert mechanism.

### Candidate contract template (applied to each shortlisted hypothesis
   in Part 3)

| field | requirement |
|---|---|
| Intended horizon and user action | Stated explicitly — e.g. "EOD alert, hold overnight, exit at next open" is a **different** user action from an intraday alert; must not be conflated. |
| Long-only entry and explicit exit | A concrete, falsifiable rule for BOTH — "buy when X" is not a contract without a matching, equally concrete "sell when Y." |
| Information available before the decision | Must be genuinely known at decision time (no same-bar/future leakage) — stated explicitly per candidate. |
| Expected opportunity frequency | Estimated FROM DATA (trigger counts, not intent) on the actual 48-name configured universe — not asserted as a requirement to invent a quota. |
| Data and execution requirements | Named exactly — which existing dataset, what resolution, what's missing. |
| Costs and practical economic materiality | Same discipline as Task 121B: a modeled cost + a predeclared materiality threshold BEFORE outcomes. |
| Falsification | What observation would show the mechanism does NOT hold for TalonX's configured universe/period — stated up front, not invented after a result. |

**Explicitly not accepted as "materially different"**: a changed
threshold, a removed loser, an added indicator, or a favorable
subperiod of an already-tested mechanism. Every hypothesis below is
checked against this bar in its own "exact substantive difference"
field.

---

## Part 3 — shortlist (at most three)

Cross-referenced against `docs/RESEARCH_STATUS.md`'s "What is NOT
reopened" list: free intraday structural-long price/volume alpha
(cost wall, Tasks 93-101B); broad price/volume cross-sectional ranking
(momentum inversion, Task 95E/95G); swing-horizon price/volume patterns
(Task 95B); free earnings-reaction alpha (mean-reversion, Task 95C-D);
deterministic filing-text alpha (Task 95H-I); risk-exclusion filtering
(Task 95K); catalyst-displacement (Task 97/106A). Reopening any of these
requires "a materially new data or feature class... not a parameter
sweep" (`RESEARCH_STATUS.md`, verbatim).

### Hypothesis 1 (highest-ranked) — overnight (close-to-open) return,
    conditioned on same-day abnormal volume as a free retail-attention
    proxy

- **Mechanism**: retail order flow concentrates near the open; stocks
  that recently attracted retail attention (proxied here, for free, by
  abnormally high same-day volume) show a systematic **positive
  overnight return** that partially **reverses intraday** — Berkman,
  Koch, Tuttle & Zhang (2012), *"Paying Attention: Overnight Returns and
  the Hidden Cost of Buying at the Open,"* **Journal of Financial and
  Quantitative Analysis, 47(4), 715–741** — U.S. common stocks, effect
  concentrated in high-attention, hard-to-value, high-sentiment-period
  names. Related: Lou, Polk & Skouras (2019), *"A Tug of War: Overnight
  versus Intraday Expected Returns,"* **Journal of Financial Economics,
  134(1), 192–213** — documents that for LARGE stocks specifically,
  momentum profits are earned almost entirely overnight, with an
  offsetting intraday reversal — directly relevant since TalonX's
  configured universe is large/mega-cap.
- **Why it could apply here**: the configured 48-name universe is
  overwhelmingly large-cap, liquid, well-covered names (AAPL, MSFT,
  NVDA, JPM, etc.) — exactly the population both papers study, not an
  extrapolation to an untested universe.
- **Signal availability/timing**: same-day volume vs. a trailing
  average, fully known BY THE CLOSE of the trigger day (causal) — an
  EOD alert product fits this exactly ("buy at/near close, hold
  overnight, sell at next open").
- **Holding/exit**: fixed, short (overnight only — sell at next
  session's open, or on a stop if adverse pre-market/opening move
  exceeds a predeclared bound).
- **Existing data coverage**: `results/task95g_broad_cross_sectional/_daily`
  (Alpaca SIP daily bars, `adjustment=all`, free/entitled, 2019-06-03 →
  2026-08-14) already has OPEN and CLOSE for **35 of 48** configured
  tickers — sufficient to compute both the trigger AND the overnight
  return with **zero new data acquisition**. Missing: ABCL, ACHR, ADC,
  AGNC, ASML, BABA, BLSH, MSTR, PATH, RIG, SHOP, SKHY, SPCX (13 names;
  6 of these — ABCL/ACHR/ADC/AGNC/MSTR/RIG — DO have coverage in a
  second existing dataset, `results/task107a_form4_feasibility/_prices`,
  not used in this bounded check but available for a later, wider run).
- **Closest previous TalonX experiment**: Task 95B (swing, 3-10 day
  daily price/volume patterns) and Task 95E/95G (cross-sectional
  momentum, close-to-close). **Exact substantive difference**: neither
  prior study DECOMPOSED returns by session (overnight vs. intraday) —
  both used blended close-to-close or multi-day returns. Lou/Polk/
  Skouras's own finding that large-cap momentum profits concentrate
  overnight, offset by intraday reversal, gives a specific, literature-
  grounded reason a session-decomposed signal could show a sign/
  magnitude the BLENDED construction (Task 95G, which inverted negative)
  could not detect. This is not a re-parameterization of momentum — it
  isolates a different return component with a different documented
  economic driver (retail attention/order-flow timing, not price-trend
  continuation).
- **Main reason it may fail**: TalonX's product needs an intraday-alert-
  compatible ACTION (buy near the close) which is a narrower window
  than most retail trading tools support well; the effect could also be
  arbitraged away/weaker in the post-2012-publication, post-2019 sample
  (out-of-sample decay is a known risk for published anomalies —
  disclosed explicitly per this task's own instruction that published
  success does not establish TalonX performance).
- **Estimated effort**: SMALL — reuses existing daily bars, a simple
  trigger rule, and a straightforward overnight-return computation; no
  new backtest engine needed (see Part 6).

### Hypothesis 2 — 52-week-high proximity (anchoring-based momentum,
    distinct from generic past-return momentum)

- **Mechanism**: investors anchor on a stock's 52-week high as a
  reference point; stocks trading near their 52-week high continue to
  outperform, and this measure DOMINATES generic past-return momentum
  as a predictor — George & Hwang (2004), *"The 52-Week High and
  Momentum Investing,"* **Journal of Finance, 59(5), 2145–2176** — U.S.
  common stocks, ranked by price-to-52-week-high ratio, **held 6-12
  months** in the original study.
- **Why it could apply here**: same large-cap U.S. universe; but the
  ORIGINAL holding period (6-12 months) does not match TalonX's
  intraday/swing product at all — any TalonX test would necessarily use
  a much shorter holding period than the published evidence, which must
  be disclosed as a genuine departure, not merely "the same anomaly at
  a different scope."
- **Signal availability/timing**: trivial — 252-trading-day rolling max
  of close, known causally at each day's own close.
- **Holding/exit**: would need a NEW, TalonX-specific short-horizon
  exit rule (e.g., N-day hold or ATR stop) — not specified by the
  source literature, an additional design decision this task does not
  make.
- **Existing data coverage**: same `task95g_broad_cross_sectional/_daily`
  panel, same 35/48 coverage.
- **Closest previous TalonX experiment**: Task 95B (swing breakout
  patterns) tested breakout-style triggers over 3-10 days and found
  breakout/momentum **NEGATIVE-excess, mean-reverting at 2-3 days**.
  **Exact substantive difference**: George/Hwang's 52-week-high
  anchoring is a specific behavioral construct (distance from a salient
  REFERENCE price), not a generic "recent breakout" pattern — but the
  overlap risk with Task 95B's already-rejected short-horizon breakout
  finding is real and must be weighed: Task 95B's finding of 2-3 day
  mean-reversion is a genuine reason to expect a SHORT-horizon 52-week-
  high test to fail even if the LONG-horizon (published) version works.
- **Main reason it may fail**: the published edge is a 6-12 MONTH
  phenomenon; compressing it to a TalonX-compatible short holding period
  is not validated by the source literature at all, and Task 95B's own
  short-horizon breakout finding is a specific, on-point reason to
  expect it not to survive the compression.
- **Estimated effort**: SMALL for the trigger/feasibility check (same
  data); MEDIUM for a full evaluation given the un-specified exit rule
  needs its own design (a source of potential post-hoc tuning risk that
  would need to be predeclared carefully).

### Hypothesis 3 (lowest-ranked, likely fails the frequency/
    single-name-actionability bar quickly) — turn-of-month calendar
    effect

- **Mechanism**: equity returns are abnormally concentrated in the few
  trading days around each calendar month's turn — McConnell & Xu
  (2008), *"Equity Returns at the Turn of the Month,"* **Financial
  Analysts Journal, 64(2), 49-64** — documents the effect in 31/35
  countries examined, 1926-2005 aggregate U.S. equity data, NOT
  specifically a single-stock cross-sectional predictor; explicitly
  found not to be explained by month-end volume/fund flows.
- **Why it could apply here**: unclear at the SINGLE-TICKER level — the
  source literature studies broad indices/portfolios, not individual-
  name predictability, which is what a per-ticker alert product needs.
- **Signal availability/timing**: trivial (calendar dates only).
- **Existing data coverage**: full (dates require no market data at
  all).
- **Closest previous TalonX experiment**: none directly — no calendar-
  seasonality hypothesis has been tested in this research program.
  Genuinely a new feature class (calendar, not price/volume/text/
  insider), which favorably distinguishes it from the "NOT reopened"
  list — but likely fails on FREQUENCY/ACTIONABILITY grounds specific
  to a per-ticker alert product (the same 3-5 calendar days apply to
  EVERY ticker simultaneously — this is a market-timing signal, not a
  configured-ticker-differentiating one).
- **Main reason it may fail**: weak or absent single-stock cross-
  sectional differentiation — the effect's own literature is about
  AGGREGATE market timing, and a strategy that fires on ALL 48
  configured tickers on the SAME ~4 days/month does not match "timely,
  useful ALERTS" per ticker in any differentiating sense.
- **Estimated effort**: TRIVIAL to check feasibility, but ranked lowest
  and not carried into Part 4's feasibility check given the frequency/
  actionability concern is apparent without running any data.

**Explicit non-inclusions**: no options-based signal (no free options
data source identified), no institutional 13F change signal (quarterly,
free-but-stale, poor timing fit), no analyst-estimate-based signal (no
free point-in-time consensus source — the SAME blocker Task 95C-D
already documented, not re-litigated here), no AI/ML overlay (no
specific, justified information advantage identified — the constraint
here is DATA/SIGNAL, not model class), no inverted version of Task 95G's
negative momentum finding (an opposite historical sign is not treated as
automatic evidence for an inverted strategy, per this task's own
explicit instruction), no re-framing of Task 95K's risk-filter family.

---

## Part 4 — ranking and bounded feasibility check

**Ranking (before inspecting any candidate's return/outcome data)**:

| | mechanism plausibility | data availability | runtime complexity | expected frequency | overlap w/ rejected work |
|---|---|---|---|---|---|
| 1. Overnight/attention | strong (2 independent papers, large-cap-specific) | full (existing daily bars, 35/48) | low | to be measured | low (session-decomposition, not tested before) |
| 2. 52-week-high | strong at published horizon, UNTESTED at TalonX's horizon | full (same data) | low (trigger) / medium (exit design) | to be measured | medium (adjacent to Task 95B's rejected short-horizon breakout) |
| 3. Turn-of-month | weak at single-stock level | full (trivial) | low | apparent low/non-differentiating without running data | low (new feature class) but likely fails on actionability |

**Hypothesis 1 (overnight/attention) ranks highest** — strongest,
most directly-applicable mechanism; lowest overlap risk; full existing
data coverage; lowest implementation complexity (a straightforward
exit rule, unlike Hypothesis 2's undefined one).

### Bounded feasibility check (Hypothesis 1 only, existing data only,
   `research/scripts/task122_overnight_feasibility.py`)

- **Static configured-universe mapping**: 35 of 48 configured tickers
  covered by `task95g_broad_cross_sectional/_daily`; 13 missing
  (ABCL, ACHR, ADC, AGNC, ASML, BABA, BLSH, MSTR, PATH, RIG, SHOP,
  SKHY, SPCX) — of these, 6 (ABCL/ACHR/ADC/AGNC/MSTR/RIG) have
  coverage in a SECOND existing dataset (`task107a_form4_feasibility/_prices`)
  not used in this bounded check. **7 names (ASML, BABA, BLSH, PATH,
  SHOP, SKHY, SPCX) have no existing free daily-bar coverage located in
  this task** — reported explicitly, not silently dropped.
- **Historical field availability/timestamps**: `date, open, high, low,
  close, volume, trades, vwap` — open and close both present for every
  covered symbol/day.
- **Point-in-time usability / revision risk**: Alpaca SIP EOD daily
  bars are settled, not subject to same-day revision once published;
  the causal trailing-volume-average computation used `shift(1)` so a
  trigger day's own volume never leaks into its own baseline —
  point-in-time correct by construction, verified by reading the
  script's own logic, not merely asserted.
- **Price/volume coverage/resolution**: daily resolution, sufficient
  for a close-to-open (overnight) construction — no 1-minute data is
  needed for THIS specific mechanism.
- **Event/setup counts by month and ticker** (trigger = same-day volume
  ≥ 2× its own trailing 20-day average; **no outcome return was read or
  used to pick dates**): **2,447 trigger-days** across 35 symbols over
  **86 calendar months** (2019-06 → 2026-08) — **0 data-quality issues**
  (no duplicate/out-of-order dates, no non-positive prices, no negative
  volume, any symbol) — **0 calendar months with zero triggers across
  the whole universe** (no long aggregate dry spells). Per-symbol
  totals range from 36 (TSLA, ≈0.42/month) to 246 (SMCI, ≈2.86/month);
  universe-wide average **≈0.81 triggers/symbol/month**, **≈28.5
  triggers/month in aggregate across the 35-symbol covered set** — a
  materially higher aggregate cadence than Original's ~0.15/month, and
  in the same broad order of magnitude as Experimental's observed
  ~34/month.
- **Corporate-action/listing-boundary handling**: Alpaca `adjustment=all`
  (split+dividend adjusted) — no separate corporate-action handling
  needed; listing boundaries are naturally truncated by each symbol's
  own first/last available row (checked, none pre-listing gaps found
  in the covered set for this period).
- **Realistic decision-to-entry timing**: the trigger is known at THAT
  DAY'S close (volume for the full day is final by end-of-day) — a
  same-day, at/near-close entry is causally valid; no lookahead.

**This is a coverage/frequency feasibility check only — no economic
outcome (the overnight return itself) was computed or inspected in this
task**, per Part 4's explicit instruction to rank/check feasibility
BEFORE looking at candidate returns.

> **Correction (Task 123, 2026-09-13):** the trigger-frequency counts
> above (2,447 events, etc.) remain accurate. What is withdrawn is the
> IMPLICIT assumption, carried into Part 5's fixed evaluation protocol
> below, that this daily-final-volume trigger could be acted on at
> session S's OWN closing price — final daily volume is only known at
> or after the close itself, making that a non-causal execution claim.
> Corrected into two explicit tracks (a non-actionable daily-data
> ASSOCIATION diagnostic, and a separately-specified, intraday-data-
> dependent ACTIONABLE pre-close candidate) in
> `docs/research/TASK123_TIMING_CORRECTION.md` and evaluated in
> `docs/research/TASK123_OVERNIGHT_ATTENTION_RESULTS.md`. Part 5's
> protocol below (same-day close entry) is superseded by that
> correction, not deleted.

---

## Part 5 — decision

**`ONE_CANDIDATE_READY_FOR_FIXED_EVALUATION`**

Hypothesis 1 (overnight/close-to-open return, conditioned on same-day
abnormal volume) has a specified, falsifiable long-only entry/exit
mechanism, full existing-data coverage for 35/48 configured tickers, a
measured, non-degenerate trigger frequency (2,447 events, 0 zero-
trigger months, 0 data-quality issues), and a documented, on-point,
literature-grounded reason to expect a result distinct from every
already-rejected price/volume study in this program.

### Fixed evaluation protocol (frozen now, not run in this task)

- **Universe**: the 35 configured tickers with existing daily-bar
  coverage (named explicitly above); the 13 uncovered names are
  excluded and reported as a coverage gap, not silently treated as
  "no signal."
- **Historical window**: full available history, **2019-06-03 →
  2026-08-14** (the existing dataset's own span) — this data has
  already been inspected once in this task (for trigger-frequency
  feasibility only, never for the overnight-return outcome). Label the
  evaluation **exploratory** on this basis — no untouched confirmation
  window exists within this same dataset. If a genuinely separate
  confirmation window is later wanted, it would need to come from data
  collected AFTER this task (out of scope here).
- **Signal**: same-day volume ≥ 2.0× its own trailing, causal 20-day
  average (unchanged from the feasibility check — no threshold tuning
  from this point).
- **Entry**: at that day's close (or the last available intraday price
  before close, if a future run uses intraday data — this fixed
  protocol uses the DAILY close as the entry reference, consistent
  with the feasibility check's own resolution).
- **Exit**: the NEXT trading day's open (fixed, one-session hold — no
  variant holding periods).
- **Cost/execution assumptions**: apply the SAME 5bps round-trip spread
  convention (`apply_spread`'s real formula) used throughout this
  research program for consistency; commissions unmodeled (same
  disclosure as every prior task).
- **Benchmark/control**: the SAME symbols' own unconditional overnight
  return (i.e., every session's close-to-next-open return for the same
  35 tickers, NOT gated by the volume trigger) — isolates whether the
  volume-conditioning adds anything beyond the raw overnight effect
  itself.
- **Portfolio/concurrency constraints**: fixed $ allocation per
  triggered name per night (consistent with Original/Experimental/V2's
  own fixed-notional convention), a stated maximum concurrent overnight
  positions (to be set equal to the configured universe size, i.e. no
  additional capital constraint beyond what 35 potential simultaneous
  positions would require).
- **Primary metric**: mean overnight return (bps) net of the modeled
  5bps cost, for triggered vs. control populations.
- **Uncertainty**: issuer-block bootstrap (same convention/tooling as
  Tasks 120-121B), predeclared before running.
- **Predefined sensitivities**: (1) drop-top-1-issuer; (2) a stricter
  trigger multiple (e.g. 3.0× instead of 2.0×) computed on the SAME
  frozen population, reported alongside — not chosen after seeing the
  2.0× result.
- **Acceptance/rejection**: a materiality band analogous to Task 121B's
  (a specific bps-per-trade threshold reflecting realistic additional
  costs beyond the modeled 5bps) — to be finalized with the actual
  notional/sizing decision in the next task, not invented here without
  that context.
- **Missing-data/terminal-position treatment**: a triggered name with
  no next-session open available (e.g., trading halt, last day of
  history) is excluded from the closed-trade population and reported
  explicitly, never given an invented fill.
- **Fixed stopping rule**: run once over the full available window
  above; no automatic extension.

---

## Part 6 — making the next task executable

- **Reusable functions/revisions**: `talonx_backtest.data.load_ohlcv_csv`/
  `check_dataset_quality` (byte-identical, reused across this entire
  session) for loading/validating the daily CSVs; `talonx_paper.engine.apply_spread`
  (verified formula, Task 121A/B) for the cost model; the issuer-block
  bootstrap pattern already implemented in
  `research/scripts/task121b_reliable_replay.py`/`task120b_chronological_baseline.py`
  (reused as a pattern, not a shared library — matching this codebase's
  own "no internal library between modules" convention).
- **Minimal adapter work**: a new, SMALL script (NOT a new engine) that:
  (1) loads the 35 covered symbols' daily bars, (2) computes the causal
  trigger flag (already implemented and tested this task in
  `task122_overnight_feasibility.py` — reusable as-is), (3) computes
  each triggered day's overnight return with the 5bps cost applied,
  (4) computes the same for the unconditional control population,
  (5) runs the issuer-block bootstrap on both. No new backtest engine,
  no new data provider, no new position-lifecycle simulator — this is
  a vectorized daily-bar computation, not an event-driven replay.
- **Small causal event trace needed before the historical run**: a
  handful of hand-picked (symbol, date) rows with a KNOWN trigger/no-
  trigger status and a KNOWN correct overnight return, to prove the
  causal shift(1) trigger logic and the overnight-return date alignment
  (today's close → tomorrow's open, correctly ticker-and-date-matched,
  never leaking a later day's data) before trusting the full run — a
  handful of unit tests, not a new framework.
- **Estimated bar/event count and runtime**: ~63,049 daily rows across
  35 symbols (measured this task) — a vectorized pandas computation
  over ~63K rows completes in seconds, not hours; no profiling is
  necessary before this computation (it is not the per-bar
  indicator-recomputation bottleneck that made the Experimental
  replays multi-hour — this is a much smaller, embarrassingly
  vectorizable daily-bar calculation).
- **Output artifacts**: a trigger/control trade table (symbol, date,
  entry/exit price, gross/net overnight return), an issuer-block
  bootstrap CI, and a `TASK123_OVERNIGHT_ATTENTION_RESULTS.md` (or
  equivalent) report.
- **Exact economic decision the run will make**: whether the
  volume-conditioned overnight return, net of the modeled 5bps cost,
  clears a predeclared materiality band relative to the unconditional
  control — i.e. whether "buy at close on an attention spike, sell at
  next open" is a candidate worth a further (non-exploratory)
  confirmation test, using the SAME three-way decision framework
  (ADVANCE / REJECT / INSUFFICIENT_EVIDENCE) established in Tasks
  120-121B.

This task does **not** run that evaluation — Part 6 specifies it as the
next task's exact, bounded scope.
