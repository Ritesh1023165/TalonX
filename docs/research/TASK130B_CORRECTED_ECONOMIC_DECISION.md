# Task 130B — corrected economics, full identity resolution, and final gate

Full outputs: `results/task130b_durable_replay/{summary,corrected_stats,
closed_trades,daily_marks,funnel_counts,audit_log,episode_comparison}.json`,
`results/task130b_identity_evidence/{accession_evidence_chains,
classification_summary,full_identity_classification}.json` (compact
copies in `docs/research/evidence/task130b/`; `daily_marks.json`,
`audit_log.json`, and `accession_evidence_chains.json` stay local only,
following this program's evidence-size convention).

## Per-episode comparison vs. Task 130A (Part 9)

| | count |
|---|---:|
| Unchanged (identical episode_id, timing, quantity/cost, symbol) | **153 of 153** |
| Identity-corrected | 0 |
| Newly admitted | 0 |
| Excluded | 0 |
| Timing changed | 0 |
| Quantity/cost changed | 0 |
| Missing-data disposition changed | 0 |

**The durable, V2Store-backed, session-phased driver produced the
EXACT SAME 153 closed trades as Task 130A's in-memory driver** — same
`episode_id`s, same entry/exit sessions, same shares/notional, same
P&L to full precision, same daily-marked drawdown (−2.7478%, peak
2026-03-04, trough 2026-03-20 — identical dates). **This numerical
equality is not treated as evidence the two implementations are
equivalent in general** — it is explained specifically: Task 130A
itself already established that capacity was never binding in this
window/population (minimum cash observed $181,392.76 of $300,000), and
this run's own funnel confirms the same (`SKIPPED_INSUFFICIENT_CAPACITY`
never fires — not present in `funnel_counts.json` at all). The
durability, session-phasing, and bounded missing-price-retry mechanics
this task adds are specifically designed to matter under capacity
contention, restart interruption, or missing-price gaps — NONE of
which the real dataset for this window/population happens to trigger.
A clean, uninterrupted, always-priced run therefore converges on the
same admitted set regardless of which driver enforces the contract.
**This is a property of this specific historical window, not a general
claim that the durability/ordering repairs are inert** — the Part 6
failure-path tests (`tests/test_task130b_durable_replay.py`) are what
demonstrate those repairs actually work, using synthetic scenarios
that deliberately DO trigger capacity contention and missing prices,
since the real dataset does not.

## Funnel (full run, for reference)

`SKIPPED_ENTRY_STALE`=216, `SKIPPED_NO_PRIOR_INTENT`=7,
`INTENT_CREATED`=162, `ENTERED`=153, `EXITED`=153,
`SKIPPED_IN_COOLDOWN`=5, `SKIPPED_SYMBOL_ALREADY_OPEN`=4,
`SKIPPED_LIQUIDITY_OR_NONBUY`=7. 162 intents created, 153 filled — the
9 non-filled PENDING intents ended `EXPIRED_COOLDOWN`/
`EXPIRED_SYMBOL_OPEN`/`EXPIRED_NO_PRICE` (subset of the SKIPPED_* rows
above, since those dispositions are recorded at the point the intent
is later resolved at OPEN, not at creation).

## Historical economic result (unchanged from Task 130A, now on a durable, session-phased implementation)

- N=153 closed trades, 106 distinct issuers.
- **Net mean +2.0219%/round trip** (clears +0.50%), median +1.674%,
  win rate 62.75%, PF 2.1399.
- Issuer-block bootstrap 95% CI **[+0.7222%, +3.3989%]** — excludes
  zero.
- Date-block (19 monthly blocks) bootstrap 95% CI **[+0.5723%,
  +3.4573%]** — excludes zero. **Both methods agree.**

## Concentration and stability (unchanged, reused unmodified `compute_stats`)

**Original, preregistered, trade-count-ranked**: excl. top-1 (SPG) →
+2.1629%; top-3 (SPG, TPL, LUV) → +1.9907%; top-5 → +1.9523%. Sign
never reverses.

**Supplemental, NOT-preregistered, P&L-contribution-ranked**: excl.
top-1 (LB) → +1.7911%; top-3 (LB, EL, LUV) → +1.4560%; top-5 (LB, EL,
LUV, SEDG, BBWI) → +1.1421%. Sign never reverses; magnitude declines
more steeply under this lens, as previously disclosed (69 of 106
issuers are net-positive contributors).

**Calendar half-year stability, period boundaries not moved**: 2024H2
+4.26% (n=21), 2025H1 +2.72% (n=47), 2025H2 +2.09% (n=52), **2026H1
−0.50% (n=33)** — three of four independently positive; the negative
most-recent half-year remains visible.

## Daily marked equity, drawdown, and study-cutoff vs. tail (Part 8)

- **Max drawdown (true daily mark-to-market), study window: −2.7478%**
  — peak 2026-03-04, trough 2026-03-20, not recovered within the study
  window (11 sessions from trough to cutoff — too little time to
  determine recovery, an honest boundary effect).
- **Study cutoff (2026-03-31)**: equity **$330,840.98**, **2 positions
  still open** (not yet exited at cutoff — see below).
- **After the 20-session settlement tail** (through 2026-04-28, no new
  eligible-entry sessions admitted): equity **$330,935.40**, **0
  positions open, 0 unresolved exits** — both of the 2 positions open
  at cutoff settled naturally within the tail. Tail-inclusive max
  drawdown is unchanged at −2.7478% (the tail's own marks never
  exceed the study-window trough).
- **Capital utilization (day-frequency occupancy)**: 89.62% of study
  sessions had ≥1 open position.
- **Invested-capital / equity exposure ratio (NEW — closes Task 130A's
  disclosed gap)**: mean open-position cost basis ÷ mean equity over
  the study window = **12.07%**. This is a genuinely distinct measure
  from the 89.62% occupancy figure above — occupancy counts ANY day
  with ≥1 of 20 possible slots filled, while this ratio reflects how
  much of the $300k+ equity base was actually deployed on average (a
  handful of $10k positions against $300k+ equity is a LOW average
  exposure ratio even on a day nearly always occupied by at least one
  position).
- Every session's mark records requested date, actual mark date,
  staleness, and unavailability explicitly (`daily_marks.json`'s own
  `stale_or_missing_marks` field) — no unavailable mark is presented
  as a fresh valuation; none occurred in this real run (0 stale/missing
  marks across all 414 sessions — the daily bar coverage for this
  626-name/window combination was complete).

## Issuer identity: full 35-symbol classification (Part 3)

35 ambiguous symbols within the frozen 626-name Discovery Universe v1
(unchanged population). Using identity evidence only, never trade
profitability, and the CIK-padding fix (`_norm_cik`) that Task 130A's
own script lacked:

| final classification | count | basis |
|---|---:|---|
| **VERIFIED_CONSISTENT** | 8 | TRADED, accession-level exact constituent records confirm a single issuer CIK per winning episode |
| VERIFIED_ERROR_REQUIRING_CORRECTION | 0 | (none found) |
| **UNRESOLVED** | 11 | overlapping CIK date ranges and/or no exact eligible-entry-session accession match — kept visible, not discarded |
| NOT_TRADED_DATE_RANGE_CONSISTENT | 16 | never traded in this population; non-overlapping CIK date ranges; explicitly NOT accession-chain-verified since no episode from these symbols was ever admitted |

**The CIK-normalization fix alone reduced the unresolved count from
Task 130A's 14/35 to 11/35** — three symbols (including LB) were
previously miscounted as ambiguous/overlapping purely because
`"701985"` and `"0000701985"` were treated as different issuers.

**All 8 traded ambiguous symbols are `VERIFIED_CONSISTENT`** — the
exact accession-level evidence chain (not a 60-day-grace date-range
proxy) confirms every constituent record of each winning episode
shares one issuer CIK:

- **CZR**: Caesars Entertainment Inc (CIK 1590895 only, post-2020 rename)
- **DOC**: Healthpeak Properties Inc (CIK 765880 only, post-2024 merger)
- **LB**: LandBridge Co LLC (CIK 1995807 only) — an UNRELATED company
  that reused the "LB" ticker after L Brands renamed to Bath & Body
  Works; the trade is entirely within LandBridge's own filing history
- **MRVL**: Marvell Technology Inc (CIK 1835632 only, post-2021 rename)
- **MTCH**: Match Group, Inc. (CIK 891103 only — one of two CIKs
  sharing this exact issuer name; the trade uses only the later one)
- **PCG**: PG&E Corp, the publicly-traded parent (CIK 1004980 only —
  distinct from the regulated operating subsidiary Pacific Gas &
  Electric Co, CIK 75488, which also files Section 16 reports under
  the same ticker but whose filing dates do not overlap this trade)
- **TPL**: Texas Pacific Land Corp (CIK 1811074 only, post-2021
  trust-to-corporation conversion; unrelated to a brief 2020 RENN Fund
  Inc appearance under the same symbol, entirely outside all 4 TPL
  trade dates) — 4 trades, all CIK 1811074 only
- **WTW**: Willis Towers Watson PLC (CIK 1140536 only) — ticker reuse
  after Weight Watchers International's brief, unrelated 2019 use of
  "WTW"

**A shared issuer CIK is treated as necessary, not sufficient,
evidence**: the Form 4 research dataset carries no security/share-class
title field, so price-series identity beyond issuer-CIK level (e.g.
distinguishing share classes under one issuer) cannot be verified from
this dataset — a disclosed data limitation, not silently assumed away.
No unvalidated same-share-class clustering filter is introduced; the
frozen contract's actual behavior (one issuer CIK per constituent
record set) is what is verified.

**11/35 remain UNRESOLVED** — kept fully visible in the population,
never silently discarded. None of the 11 correspond to an actual
traded episode (all 8 traded ambiguous symbols are `VERIFIED_CONSISTENT`).
Exclusion-sensitivity of the unresolved set is diagnostic only and was
not applied to any reported figure above (all 153 trades, including
any from the 16 `NOT_TRADED_DATE_RANGE_CONSISTENT` or `UNRESOLVED`
symbols that happened not to be traded, are included as-is — moot here
since none of the 11/16 non-`VERIFIED_CONSISTENT` symbols appear among
the 153 actual trades).

**Do not read this as "all 35 ambiguous symbols are resolved"** — 16
of 35 are reported honestly as `NOT_TRADED_DATE_RANGE_CONSISTENT`
(visible in the population, date-range-consistent, but never put
through the accession-level verification the 8 traded symbols
received, because no trade ever exercised them) and 11/35 remain
genuinely `UNRESOLVED`.

## Disclosed, not fixed: a real characteristic of the frozen `cluster_engine`

See the qualification addendum and durable-lifecycle acceptance
documents: the production clustering algorithm's greedy window
consumption can silently drop later, otherwise-independent filings
that arrive within the same 10-trading-day window as an
already-activated cluster, without ever forming a second episode. This
affects population coverage (potential missed episodes), not the
identity or pricing of any of the 153 admitted trades. No algorithm
change is in scope for this task.

## Final gate (Part 10) — separate acceptances

| gate | result |
|---|---|
| **Identity / security-price integrity** | **ACCEPTED for the traded population** — all 8 traded ambiguous symbols `VERIFIED_CONSISTENT` via exact accession-level evidence chains (not a date-range proxy); 11/35 non-traded-relevant symbols remain genuinely `UNRESOLVED` (disclosed, never used to shrink the population); price-series identity beyond issuer-CIK level is not verifiable from this dataset (disclosed data limitation) |
| **Historical economics** | Net +2.0219%/round trip, N=153 — clears +0.50%; both bootstraps exclude zero and agree; both concentration tests stay positive through top-5; 2026H1 negative reading preserved |
| **Durable prospective lifecycle** | **ACCEPTED** — real, committed SQLite state (`V2Store`, isolated path) verified by genuine close/reopen; explicit session phases (OPEN/CLOSE/POST-CLOSE/MARK) structurally prevent same-day filing information from funding that morning's own entries; all critical transitions (intent+reservation, reservation-consumption+position, expiry+release, exit+credit+cooldown) verified transactional by 10/10 failure-path tests |
| **Missing-price / restart behavior** | **ACCEPTED** — bounded, idempotent missing-price retry (5-session symmetric window) verified to defer rather than immediately expire, and to fill at most once; restart/close-reopen durability verified directly against a real temporary SQLite file |
| **Valuation / window accounting** | **ACCEPTED** — study-cutoff equity/positions reported separately from tail-inclusive; drawdown reported both ways, including starting equity as the series' own first observation; invested-capital/equity exposure ratio (12.07%) now computed, distinct from day-occupancy (89.62%); zero stale/missing marks occurred in this real run, and the mechanism to flag them (verified by test in the driver's fixture suite) is in place regardless |
| **Overall integration readiness** | Historical economics and durability are both now qualified on the same real population; 11/35 non-traded ambiguous identities remain open as a disclosed, bounded, non-blocking limitation |

### Verdict

> **`PASS_FOR_INTEGRATION_REVIEW`**

All required economic/statistical/sensitivity/stability gates are met.
Identity integrity is now verified at the accession level for every
traded episode (closing Task 130A's own most significant disclosed
gap — the 60-day-grace heuristic). Durability, session-ordering, and
missing-price recovery are now real, tested, SQLite-backed behaviors,
not in-memory conveniences (closing Task 130A's second disclosed gap).
Invested-capital/equity exposure is now computed (closing Task 130A's
third disclosed gap). **This is still not a deployment recommendation
and does not by itself authorize production integration** — it is
conditional evidence for a LATER, separately-authorized
activation-review task, exactly as Task 130/130A's own handoffs
specified. Paper fills in this offline, ideal-price replay are NOT
executable returns, and historical consistency with Task 130A is NOT
independent confirmation of anything beyond "this specific window's
capacity was never binding under either implementation" — stated
explicitly, not implied.

## Residual, disclosed gaps (not blocking, named for the next task)

1. 11/35 ambiguous issuer-CIK mappings remain unresolved at the
   symbol level (0 of these correspond to an actual traded episode).
2. 16/35 ambiguous symbols were never put through accession-level
   verification because no trade ever exercised them — reported
   honestly as `NOT_TRADED_DATE_RANGE_CONSISTENT`, not claimed
   resolved.
3. The frozen `cluster_engine`'s greedy window-consumption
   characteristic (documented above) may silently omit legitimate,
   independent clusters that fall within 10 trading sessions of an
   already-fired cluster on the same issuer — a population-coverage
   question, out of scope to fix here.
4. This remains an offline, ideal-price replay; no live, delayed-data
   production run has been qualified by this task.

## One next action

No further repair task is proposed from this task's own findings. The
named residual gaps above are small, bounded, and appropriate for the
SAME later, separately-authorized integration-review task Task
130/130A's own handoffs already specified — not a new research cycle.
Task 129's broader alpha-research pause remains in effect for every
other mechanism. Integration remains HOLD. Production remains paused.
