# PRE-REG: TICKER\_SCORECARD\_V1 — multi-horizon ticker view

Nov 2, 2026 · @Ritesh

## Status and scope

**APPROVED by the owner on 2026-11-03.** Once approved, nothing in the sections below changes before the final verdict. Any change after approval voids the study and requires a new pre-registration.

**Purpose.** Test whether TalonX can give a useful bullish or bearish view on any given ticker at four horizons (1D, 1W, 1M, 3M), using free data only. Bullish means likely to beat SPY; bearish means likely to lag it.

**What this is not.** It is not a trading strategy, not a profitability claim, and makes no short positions. It does not reopen any lane closed in `RESEARCH_STATUS.md` by parameter sweep.

**Design principle: one pass, no repeats.** Every stage below runs exactly once on locked inputs, with a fixed run budget (see Run budget, failures and isolation). All outcomes are decided in advance (see Decision table), so no result can trigger a rerun, a re-tune or a second look at the holdout.

**Relation to open studies.** Drafted 2026-11-02, before the PDM endpoint (2026-11-17 22:00Z) and without reading any PDM output. It is a separate mandate, not a reaction to V2 or PDM results. Build work before 2026-11-18 is offline only (see Run budget, failures and isolation).

## Question and hypotheses

**Question.** Does a single locked composite rank, built from point-in-time free features, order stocks by their future return relative to SPY at each horizon, out of sample?

Each horizon is judged separately. A pass at one horizon never rescues a fail at another.

| ID | Horizon | Label window | H1 (skill exists) | H0 (no skill) | Prior expectation |
| --- | --- | --- | --- | --- | --- |
| H-1D | 1 day | close t → close t+1 | Rank IC > 0 and top–bottom decile spread > 0 | IC ≤ 0 or not distinguishable from 0 | Weak or none (cost wall, Tasks 93–95A) |
| H-1W | 1 week | close t → close t+5 | as above | as above | Possible, via short-term reversal |
| H-1M | 1 month | close t → close t+21 | as above | as above | Most likely to pass |
| H-3M | 3 months | close t → close t+63 | as above | as above | Possible; fewest independent periods |

**Bearish side.** Bottom-decile names count as bearish calls and are scored on the same footing as top-decile names. Metrics and gates tests each side separately.

**No LLM in this study.** Neither the composite nor the verdict uses an LLM. An LLM read of new filings is deferred to a separate pre-registration, to be drafted only after the HOLDOUT verdict. It would be scored forward-only, on filings accepted after the model's training cutoff, and would need its own approval.

## Universe and data

**Universe, rebuilt each rank date from data available that day.** US common stocks with as-traded close ≥ $5 and 20-day average dollar volume ≥ $20M, the DTU\_V2 floor. Delisted names stay in until their exit date (95F method). Target size about 2,000 names; whatever the floor yields is used, unchanged.

**Sample.** 2019-01-02 → 2026-10-30, split into three locked segments:

| Segment | Rank dates | Use |
| --- | --- | --- |
| TRAIN | 2019-01-02 → 2023-12-29 | Fit the composite weights once |
| VALIDATE | 2024-01-02 → 2024-12-31 | Read once; may only trigger the pre-declared fallback in the single-pass protocol |
| HOLDOUT | 2025-01-02 → 2026-06-30 | Read once; decides the verdict |
| FORWARD | from approval date | Live paper scorecard, never used to fit |

Label windows must end before the next segment starts, so the last TRAIN date for H-3M is 63 sessions before 2024-01-02. The gap is purged, not shifted.

**Data sources, all free.**

- Prices: Alpaca daily bars, split- and dividend-adjusted for returns, as-traded for the universe floor
- Fundamentals: SEC XBRL `companyfacts` bulk file, each value usable only from its filing acceptance time
- Insider activity: SEC Form 3/4/5 bulk sets (Task 107A pipeline)
- Filing changes: the existing deterministic comparison engine
- Sectors: SIC code from SEC submissions, mapped to 11 sector ETFs

**Point-in-time rules.** A feature value at rank date t uses only data accepted before 16:00 ET on t. Ranks are built after the close and labels start at the close of t, so an alert could act at the next open; Metrics and gates also reports next-open returns.

**Data gates, checked before any outcome is computed.** If any fails, the study stops with `DATA_NOT_READY` and nothing is fitted.

1. Split-adjustment check passes on every known split in the sample
2. At least 90% of universe-days have a price label at every horizon
3. At least 80% of universe-days have at least one fundamental value
4. No feature value carries a timestamp after its rank date (automated test)

## Labels and features

**Primary label.** Excess return over SPY for the horizon window: stock adjusted return minus SPY return over the same dates. **Secondary label** (reported, never decisive): excess over the stock's sector ETF.

**Locked feature list.** Twelve features in five families. Each is cross-sectionally ranked to 0–1 on every rank date, then winsorised at the 1st and 99th percentile. Nothing is added, dropped or redefined after approval.

| # | Family | Feature | Definition | Expected sign | Prior evidence |
| --- | --- | --- | --- | --- | --- |
| F1 | Reversal | 5-day return | close t ÷ close t−5 − 1 | negative | 95B, 95E, 101B: reversion at 2–3 days |
| F2 | Reversal | 21-day return, skipping last 5 days | close t−5 ÷ close t−26 − 1 | negative | 95E: relative momentum inverts |
| F3 | Trend | 12-month return, skipping last month | close t−21 ÷ close t−252 − 1 | positive | Untested at 1M–3M in TalonX |
| F4 | Risk | 60-day volatility | stdev of daily returns | negative | Untested |
| F5 | Quality | Gross profitability | TTM gross profit ÷ total assets | positive | Untested |
| F6 | Quality | Accruals | (TTM net income − TTM operating cash flow) ÷ total assets | negative | Untested |
| F7 | Value | Earnings yield | TTM net income ÷ market cap | positive | Untested |
| F8 | Value | Book-to-market | latest equity ÷ market cap | positive | Untested |
| F9 | Growth | Revenue growth | TTM revenue ÷ TTM revenue a year earlier − 1 | positive | 95C-D: no incremental info at the event |
| F10 | Insider | Net open-market buyers, 90 days | distinct code-P buyers minus distinct code-S sellers | positive | 107B, but V2 forward failed |
| F11 | Filing risk | Risk-factors change size | latest 10-K/10-Q risk-factor diff score, 0 if none in 120 days | negative | 95H-I: −67 bps at 5 days |
| F12 | Dilution | Share-count change | shares outstanding ÷ a year earlier − 1 | negative | Untested |

**Missing values.** A missing feature gets the cross-sectional median (0.5). A name missing more than 6 of the 12 features on a rank date is dropped from that date and counted in the coverage report.

**Sign checks.** Each feature's TRAIN IC sign is reported against its expected sign. A feature whose sign flips is kept with its TRAIN-fitted weight; it is not removed (removal would be a second fitting pass).

## Model and single-pass protocol

**Two locked candidates per horizon, no tuning grid.**

- **EQ (primary):** equal-weight average of the 12 ranked features, each flipped to its expected sign. Fits nothing.
- **RIDGE (challenger):** linear ridge regression on the 12 ranked features, penalty fixed at α = 1.0, fitted once on TRAIN per horizon. No grid search, no other model families.

**Calibration.** The chosen composite's rank is mapped to P(beat SPY) by isotonic regression fitted once on TRAIN, then frozen. Views: top decile = Bullish, bottom decile = Bearish, everything else Neutral.

**Execution order (each step runs once):**

1. Build the panel and run the four data gates. Fail → `DATA_NOT_READY`, stop.
2. Freeze the panel: write its SHA-256 and row counts to the study folder and commit.
3. Fit RIDGE and the calibration on TRAIN. Commit weights and fingerprint.
4. Read VALIDATE once. Per horizon, choose RIDGE only if its VALIDATE rank IC exceeds EQ's by at least 0.005; otherwise choose EQ. Commit the choice.
5. Read HOLDOUT once for the chosen composite at each horizon. Apply the Metrics and gates and the Decision table. Commit the verdict.
6. If at least one horizon passes, start the FORWARD paper scorecard with the chosen composite, unchanged.

**Code identity.** Backtest and live scorecard call the same `score(panel, date)` function in one module. The holdout run records that module's commit hash, and the forward scorecard must run the same hash. This closes the research/runtime gap that cut 107B from +1.69% to +1.01%.

**Forbidden after approval:** adding or dropping features, changing α, re-cutting segments, reading HOLDOUT twice, switching the label, or re-running any step because of its result.

## Metrics and gates

**Rank dates.** H-1D ranks every session. H-1W, H-1M and H-3M rank every Friday close (or the last session of the week). Overlapping label windows are handled with Newey-West standard errors, lag = horizon length in rank dates.

**Costs.** A Bullish call is valued as buy at the close and sell at the horizon end, minus 20 bps round trip (the project's standard). A Bearish call is valued as avoiding or exiting the name, minus 10 bps (one sell).

**Gates, evaluated on HOLDOUT, per horizon. All five must pass.**

| Gate | Test | Pass threshold |
| --- | --- | --- |
| G1 Skill | Mean Spearman rank IC vs SPY-excess label | > 0, and one-sided 95% lower bound > 0 |
| G2 Bullish value | Top-decile mean excess return minus 20 bps | > 0 |
| G3 Bearish value | Bottom-decile mean excess return | < −10 bps |
| G4 Stability | IC by calendar month; IC in each half of HOLDOUT | positive in ≥ 60% of months and in both halves |
| G5 Calibration | Hit rate of Bullish and Bearish calls; expected calibration error | Bullish beat-SPY ≥ 52%, Bearish ≤ 48%, error ≤ 5 points |

**Partial pass.** If G1, G4 and G5 pass but only one of G2 or G3 passes, that horizon passes **one-sided**: only the passing side is ever shown as a call.

**Power limit for H-3M.** HOLDOUT gives only about six independent 3-month windows. H-3M can therefore reach at most `PROVISIONAL`, never `PASS`, until 12 months of FORWARD data confirm it.

**Reported, never decisive:** sector-ETF-excess IC, next-open entry returns, results inside the S&P 500 subset, per-feature IC, turnover of the top and bottom deciles, and coverage.

## Decision table

Every outcome below is decided now, so no result needs a second run to interpret it.

**Per horizon (from HOLDOUT):**

| Outcome | Condition | Action |
| --- | --- | --- |
| `PASS` | G1–G5 all pass (not H-3M) | Show Bullish and Bearish views with probabilities in the forward scorecard |
| `PASS_ONE_SIDED` | G1, G4, G5 pass; only one of G2 / G3 passes | Show only the passing side; the other side reads "no view" |
| `PASS_RANK_ONLY` | G1–G4 pass; G5 fails | Show rank and view, no probability. Calibration is not refitted |
| `PROVISIONAL` | H-3M meets every `PASS` condition | Show as "provisional" until 12 months of FORWARD data |
| `FAIL_UNSTABLE` | G1 passes, G4 fails | No view at that horizon. Record which months or half drove it |
| `FAIL_NO_VALUE` | G1 passes, G2 and G3 both fail | No view. Ranking skill too small to matter after costs |
| `FAIL` | G1 fails | No view. Horizon closed under this feature set |

**Programme level:**

| Scenario | Action |
| --- | --- |
| Data gates fail | `DATA_NOT_READY`. Fix the data and re-run the gates. Allowed because no outcome has been computed yet |
| No horizon passes | Close the scorecard lane. TalonX stays a descriptive Risk and Event Intelligence product. Write the closeout. No variants |
| Only H-1D passes | Contradicts Tasks 93–95A, so treat as a likely leak. Run the one leakage audit described under Run budget, failures and isolation. Clean → forward-test H-1D only. Leak found → `FAIL` |
| Every horizon passes, or HOLDOUT IC exceeds TRAIN IC at any horizon | Same leakage audit before anything goes forward |
| One or more of H-1W, H-1M, H-3M pass | Start the FORWARD scorecard for passing horizons only |

**Forward checkpoints (live paper, same code hash):**

| Horizon | Checkpoint | Confirm if | Retire if |
| --- | --- | --- | --- |
| H-1D | 13 weeks | mean IC > 0 and G2 or G3 holds | mean IC ≤ 0 |
| H-1W | 26 weeks | as above | mean IC ≤ 0 |
| H-1M | 12 months | as above | mean IC ≤ 0 |
| H-3M | 12 months | as above, then `PROVISIONAL` becomes `PASS` | mean IC ≤ 0 |

A confirmed horizon is a decision-support signal, not a profitability claim. Real money, shorting, real-time data or automated execution each need their own mandate.

**Independence from PDM and V2.** The PDM verdict (17 Nov) and the V2 closeout do not change any rule here. If PDM shows post-delivery value, that successor study runs separately.

## Run budget, failures and isolation

**Run budget. Each line is the maximum, ever.**

| Step | Runs allowed |
| --- | --- |
| Data gates | Until they pass (no outcome is computed before they pass) |
| RIDGE fit and calibration on TRAIN | 1 |
| VALIDATE read | 1 |
| HOLDOUT read | 1 |
| Leakage audit | 1, only when the Decision table calls for it |
| Bug-fix re-run after HOLDOUT | 1, only under the bug rule below |

Every run writes its inputs' hashes, code commit, timestamps and outputs to `results/scorecard_v1/<step>/` and is committed before the next step starts.

**Crashes.** A step that stops before writing its metrics file produced no result and may resume. A step that wrote its metrics file is final.

**Bug rule.** If a correctness bug (look-ahead, wrong join, wrong adjustment) is found after HOLDOUT is read: describe it in a commit before fixing, fix it, re-run once, and report both results. The verdict is the **lower** of the two, so a fix can never upgrade a result.

**Leakage audit (one pass, three checks).**

1. Delay every feature by one extra session: HOLDOUT IC falling by more than half means a timing leak.
2. Shuffle labels within each rank date: mean IC must sit within ±0.005 of zero.
3. Re-run the automated timestamp test on the frozen panel.

Any check failing makes that horizon `FAIL` (leak).

**Isolation from the live system until the programme decision (18 Nov) and approval:**

- New package `talonx_scorecard/` on its own branch. It never imports `talonx_opportunity` or `talonx_v2`, and is not registered with any supervisor.
- No restart or change to promotion, notifier, discovery or delivery while PDM runs.
- SEC data from bulk files only, downloaded outside US market hours, so the live engine keeps its share of SEC's request limit.
- Heavy jobs run in the evening or on a separate machine.
- No PDM output is opened before its endpoint.

## Owner approval

Approval locks every section above. The approved text is committed to `docs/research/preregistration/` before any panel is built, and that commit hash becomes the study's identity.

**Open items to settle before approval:**

- [ ] Confirm the four horizons (1D, 1W, 1M, 3M)
- [ ] Confirm the 12 features, or swap any now; no changes after approval
- [ ] Confirm the segment dates, especially a HOLDOUT ending 2026-06-30
- [ ] Confirm the 20 bps / 10 bps cost assumptions
- [ ] Confirm that build work starts offline now and the mandate formally opens on 2026-11-18

**Approved by:** Ritesh **Date:** 2026-11-03 **Commit:** pending. The approved text must be committed to `docs/research/preregistration/` before any panel is built; that hash then becomes the study's identity.
