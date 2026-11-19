# Dynamic Tradable Universe study — 2026-09-29 (READ-ONLY research)

Branch `feature/continuous-opportunity-engine`. **Nothing in production changed.** The production universe is
unchanged, `OPERATOR_UNIVERSE_MUTATION_MODE` stays DRY_RUN, and no Signal policy changed. Every threshold below is
a *candidate research parameter*, not an approved product rule.

- Tools: `2026-09-29_dynamic_tradable_universe/tools/`.
- Result tables: `2026-09-29_dynamic_tradable_universe/`, containing `dtu_study.json`, `capture_rows.csv.gz`,
  `universe_snapshot_*.csv`, `monday_154.txt` and `misses.txt`.

## 1. Question and answer in one paragraph

*What is the smallest ACTIVE_CORE that materially reduces scan workload while preserving ≥95% of useful TalonX
opportunities once Event-Tier recovery is included?*

**Answer:**
- **Useful opportunities that must be preserved** are Opportunity setups, paper Signals, ≥80-score Signals, Lab
  events and ≥10% movers.
- **Smallest Core:** a Core of **500** (ADV20-ranked within V1's own floors) plus the event tier below meets ≥95% on
  both replayed sessions:
  - setups, Signals and ≥80-score Signals 100%;
  - movers 97.6–98.2%;
  - Lab 98.1–100%.
- **Workload saved:** 1-minute bar volume falls about 63%, symbols evaluated per scan fall 65–69%, and SEC lookups
  fall 19–26% (estimated).
- **What is lost:** 41–46% of all new candidate identities at Core 500. These are WATCH-level 2–3% gappers in non-Core names, since every setup is kept. Up to 69 of Monday's
  154 Signals would reach the engine at the scan where their gap first crossed 3%, which adds 0–5 minutes of latency
  depending on design.
- **The event tier does the work.** Capture is almost flat across Core sizes, so Core size only trades WATCH-level
  coverage and latency against workload.
- **SEC load has a hard limit.** It cannot fall much further without losing setups, because SEC lookups are, by
  construction, lookups for ≥2% gappers.
- **The core finding: a pure liquidity Core does not work.** Top-1200 by ADV20 alone captures 25% of Monday's
  Signals and 12% of movers.

## 2. Sources

| Dataset | Content | Status |
|---|---|---|
| `market.db` `universe` (09-25, 09-28, 09-29) | Every Alpaca US equity with ELIGIBLE / EXCLUDED:reason (`talonx_premarket/universe.py`) | local, MEASURED |
| `market.db` `daily` | ~45 days of daily SIP bars up to D-1, giving price, ADV20 and daily coverage | local, MEASURED |
| `market.db` `aggregates` | Window-to-date 1-min bar counts per symbol (09-25, 09-28), used for bar workload | local, MEASURED |
| `opportunity.db` | Scans (funnel, duration), `near_misses` (every ≥2% gap observation per scan), `candidate_events` | local, MEASURED |
| `promotion.db` + `paper_outcomes` | Signals (Fri 36, Mon 154) with their outcomes | local, MEASURED |
| Lab outbox + `notification.db` | Lab messages sent (Fri 294, Mon 319) | local, MEASURED |
| D-1 RTH 1-min bars (09-24, 09-25, 09-28) | RTH coverage and 1-min range proxy (`fetch_d1_features.py`, existing Alpaca SIP) | fetched, MEASURED |
| SIP NBBO quote samples (09-25, 09-28; 15:00Z and 18:00Z) | Quoted spread in bps for 5,305 of 5,652 symbols | fetched, MEASURED |
| EDGAR daily form index 09-10 → 09-28 | Every 8-K / 6-K / Form 4 filing, 16,219 rows (`fetch_edgar_daily_index.py`) | fetched, MEASURED |
| Alpaca `/v2/stocks/snapshots?feed=delayed_sip` | Universe-wide last trade and previous daily bar, for the gap sweep | probed, MEASURED |
| V2 scope (39 names) + V2 episodes | Operator/V2-protected symbols | local |

## 3. Classifying the universe (09-28)

The 14,380 Alpaca US-equity assets split as follows:

| Bucket | Count |
|---|---|
| **ELIGIBLE (the 5,652 base)** | 5,652 |
| FUND_ETF_ETN | 5,975 |
| NOT_TRADABLE | 877 |
| MALFORMED_OR_NON_COMMON_SYMBOL | 446 |
| WARRANT | 408 |
| NOT_LISTED_EXCHANGE (OTC / Pink) | 313 |
| UNIT | 273 |
| NOTE_DEBT | 167 |
| RIGHT | 124 |
| PREFERRED | 109 |
| NOT_SEC_REGISTRANT_TICKER | 31 |
| DEPOSITARY_NON_ADR | 5 |

**The structural study is therefore already applied:** the 5,652 base is the common-equity-like, listed,
SEC-registrant bucket.
- By exchange: NASDAQ 3,388, NYSE 1,997, AMEX 246, ARCA 20, BATS 1.
- ADRs are kept by design.
- "Common equity only" is thus the *current documented* scope (universe.py), not a new hypothesis. Its rules are
  name-regex heuristics, so a small residue of misclassified funds or SPAC units is possible.

**The layer below it (new evidence):** 1,727 of the 5,652 (Monday) fail V1's own hard gates (`min_prev_close` $1,
`min_adv_dollar_20d` $1M). Discovery can never turn these into a candidate, yet they are ingested every 60 s and
evaluated every scan.

| Proposed state (future) | 09-28 count | Meaning |
|---|---|---|
| STRUCTURALLY_EXCLUDED | 8,728 | universe.py EXCLUDED:reason (auditable) |
| AUTO_EXCLUDED (below V1 floors) | 1,727 | structurally eligible; price < $1 or ADV20 < $1M at D-1 (V1 hard gates) |
| EVENT_ELIGIBLE pool | 3,925 | structurally eligible and within V1 floors |
| ACTIVE_CORE | N (study) | top-N of the pool by ADV20 $ |
| EVENT_PROMOTED | ~1,190–1,480 active on average beyond the Core (E5, N = 1,200 → 500; Monday) | pool members promoted by a trigger (below) |
| OPERATOR_ADDED | 40 (V2 scope and episode symbols) | always active |
| OPERATOR_EXCLUDED | 0 applied (1 recorded in DRY_RUN, TSLA, restored) | never active |

Feature availability over the base (Monday):

| Feature | Available |
|---|---|
| price / ADV20 | 5,650 |
| D-1 RTH coverage | 5,652 |
| minute-range proxy | 5,495 |
| measured spread | 5,304 (93.8%) |

Missing: historical point-in-time quotes (only 2 sampled instants per day), Form 4 transaction codes and 8-K item
numbers universe-wide.

## 4. Tradability grid (09-28, eligible counts; no winner chosen)

Price × ADV20, with no coverage or spread rule:

| Price floor | ADV ≥ $0.5M | ≥ $1M | ≥ $2M | ≥ $5M | ≥ $10M |
|---|---|---|---|---|---|
| $1 | 4,262 | **3,925** | 3,553 | 3,043 | 2,616 |
| $2 | 4,033 | 3,755 | 3,448 | 2,989 | 2,597 |
| $3 | 3,871 | 3,628 | 3,360 | 2,940 | 2,572 |
| $5 | 3,592 | 3,396 | 3,172 | 2,826 | 2,504 |

At price ≥ $1 and ADV ≥ $1M, adding coverage and spread rules:

| D-1 RTH coverage | No spread cap | ≤ 200 bps | ≤ 100 bps | ≤ 50 bps |
|---|---|---|---|---|
| none | 3,925 | 3,787 | 3,593 | 3,100 |
| ≥ 80% | 1,823 | 1,821 | 1,815 | 1,738 |
| ≥ 90% | 1,378 | 1,378 | 1,375 | 1,324 |
| ≥ 95% | 1,049 | 1,049 | 1,047 | 1,008 |
| ≥ 98% | 784 | 784 | 784 | 762 |

**Read-out:**
- **RTH minute coverage is a very strong filter:** ≥80% already removes more than half the pool. 74 of Monday's 154
  Signals had D-1 coverage below 0.8, so a coverage *floor* would cut Signals heavily.
- **Coverage is better used as a ranking or cost input than as an exclusion.**
- **Stricter price/ADV floors cost real Signals.** Price ≥ $3 with ADV ≥ $2M, uncapped, keeps 86% of Monday's
  Signals and 56% of movers, while cutting SEC load only ~20%.

## 5. D-1 feature architecture (measured cost)

| Daily D-1 batch step | Cost (measured) | Existing? |
|---|---|---|
| Universe build (Alpaca assets × SEC tickers) | already daily | yes (`universe.json`) |
| Daily bars → price, ADV20, daily coverage | already fetched by ingestion (`daily`) | yes |
| D-1 RTH 1-min bars → coverage, range proxy | **131–137 requests, ~135 s** for 5,655 symbols | new |
| NBBO spread sample (2 instants) | **112–114 requests, 154–385 s** | new |
| EDGAR daily form index | **1 request per day** | new |
| Intraday gap sweep (snapshots, `delayed_sip`) | **6 requests, ~5 s per sweep** for 5,652 symbols (5,649 usable) | new (per cadence, not D-1) |

**Proposed artifact** `universe_snapshot_YYYY-MM-DD`, written once per day from D-1 data. Prototype CSVs are in the
evidence folder. Fields:
- `symbol`, `exchange`, `structural` (reason);
- `price`, `adv20_usd`, `adv20_sh`, `daily_coverage`;
- `rth_coverage_d1`, `range_bps_d1`, `spread_bps`, `spread_basis`;
- `v1_floor_eligible`, `adv_rank`, `core_rank`, `is_core`, `is_event_eligible`;
- `promotion_reason`, `promotion_expiry`.

Storage: one SQLite table or Parquet file per day (~5.7k rows, <1 MB). Refresh: once after the D-1 close, before
04:00 ET. Nothing in the live 5-minute scan computes ADV20 or density.

## 6. Event tier (mandatory) and TTL study

**Triggers modeled.** Each is available without continuously scanning the symbol.

| Trigger | Source | TTL modeled | Symbols promoted per session (Mon / Fri) |
|---|---|---|---|
| FORM4_CLUSTER (≥2 Form 4 filings in 10 sessions) | EDGAR index | 10 sessions | 658–693 / 676–721 |
| FILING_8K (8-K, 8-K/A, 6-K) | EDGAR index | 2 / 3 / 5 sessions | 86–205 / 205–311 / 393–488 |
| GAP_SNAPSHOT ≥3% / ≥5% / ≥10% | `delayed_sip` snapshot sweep | rest of session | 1,454 / 486 / 119 (Fri 1,053 / 347 / 89) |
| OPEN identity protection | TalonX's own candidate store | until invalidated or expired | — |
| OPERATOR_ADDED (V2 scope, episodes) | V2 / operator | until removed | 40 |

Filing triggers were evaluated as a D-1 batch (filed ≤ D-1) and as REALTIME (filed ≤ D, which needs a live EDGAR feed).

**What the data says about each trigger:**
- **Index-level Form 4 clusters are noise for this purpose.** They promote ~650–720 names a session, mostly routine
  grants and sales, and add ~0 setup or Signal capture beyond the gap trigger. A useful Form 4 trigger needs
  transaction codes (open-market P), which the index lacks. That is a data gap, not a result.
- **Filings alone recover little.** E1 (D-1 filings) with Core 1200 captures 45% of setups and 42% of Signals on
  Monday.
- **The gap sweep carries the recovery.** A ≥3% threshold equals V1's setup gap threshold, so no setup can form
  outside it.
- **Identity protection is needed for lifecycle events.** Without it, invalidations and updates of names that left
  the gap condition are lost: Lab capture falls to 91.5–95.6% on Monday at Cores of 500–2,000.
- **Protection is modeled non-circularly.** An identity protects its symbol only if its own creation was captured
  under the same policy, in-window or carried from the previous replayed window.

## 7. Replay results (MEASURED capture; ESTIMATED SEC / scan time)

How capture is counted:
- **Captured:** the symbol is CORE / OPERATOR_ADDED / protected, or was promoted before the opportunity's time.
- **Late:** promoted at the same scan the opportunity appeared. That is 0–5 minutes later, depending on whether the
  sweep runs ahead of ingestion.

How load is counted:
- **SEC load** is reconstructed per scan as alert-worthy plus scored near-miss symbols. The reconstruction calibrates
  against measured lookups at +6% (857 vs 808 per scan on Monday).
- **1-minute bar volume** uses measured per-symbol bar counts.
- **Scan p90** is a least-squares fit, duration = a·(symbol fraction) + b·(lookups), per window. Fits: Friday
  a = 7.0 s, b = 0.125 s/lookup; Monday a = 6.5 s, b = 0.048 s/lookup, the difference reflecting SEC refresh ON.
  The fit is scaled to the measured p90 (Friday 258 s, Monday 74.8 s).

The "Full" row is the V1-floor pool, **not** today's 5,652 baseline. Against the 5,652 baseline every reduction is 0,
and the Full row's 10.8% bar and 30.6% symbol reductions come purely from dropping the 1,727 names below V1 floors.

### Pareto — Monday 2026-09-28, E5 = Core + filings (realtime, 8-K TTL 3, Form 4 cluster TTL 10) + gap sweep ≥3% + protection

| Core | Effective active (mean / max) | All candidates % | Setup % | Signal % | ≥80 Signal % | Mover % | Lab % | Signals 0–5 min late | SEC load − % (est.) | 1-min bars − % | Symbols evaluated − % | Scan p90 s (est.) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 500 | 1983 / 2257 | 59.2 | 100.0 | 100.0 | 100.0 (16) | 97.6 (84) | 98.1 | 69 | 19.5 | 63.5 | 64.9 | 55.5 |
| 750 | 2128 / 2395 | 61.6 | 100.0 | 100.0 | 100.0 (16) | 97.6 (84) | 98.4 | 68 | 18.2 | 58.5 | 62.4 | 56.6 |
| 1000 | 2273 / 2525 | 64.5 | 100.0 | 100.0 | 100.0 (16) | 97.6 (84) | 98.4 | 61 | 17.0 | 53.4 | 59.8 | 57.7 |
| 1200 | 2389 / 2625 | 67.1 | 100.0 | 100.0 | 100.0 (16) | 97.6 (84) | 98.4 | 53 | 15.8 | 49.3 | 57.7 | 58.7 |
| 1500 | 2553 / 2768 | 70.9 | 100.0 | 100.0 | 100.0 (16) | 97.6 (84) | 98.7 | 47 | 14.0 | 44.1 | 54.8 | 60.1 |
| 2000 | 2842 / 3017 | 78.0 | 100.0 | 100.0 | 100.0 (16) | 97.6 (84) | 99.4 | 36 | 10.6 | 35.2 | 49.7 | 62.8 |
| 3000 | 3421 / 3508 | 90.3 | 100.0 | 100.0 | 100.0 (16) | 98.8 (84) | 100.0 | 17 | 4.9 | 20.1 | 39.5 | 67.6 |
| Full V1 pool (3,925) | 3925 / 3925 | 100.0 | 100.0 | 100.0 | 100.0 (16) | 100.0 (84) | 100.0 | 0 | 0.0 | 10.8 | 30.6 | 71.6 |
| Baseline (5,652) | 5652 | 100 | 100 | 100 | 100 | 100 | 100 | 0 | 0 | 0 | 0 | 74.8 (measured) |

### Pareto — Friday 2026-09-25, same policy (SEC refresh was OFF that day)

| Core | Effective (mean / max) | All cand. % | Setup % | Signal % | ≥80 % | Mover % | Lab % | Late | SEC − % | Bars − % | Symbols − % | p90 s (est.) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 500 | 1768 / 2011 | 54.4 | 100.0 | 100.0 | 100.0 (3) | 98.2 (57) | 100.0 | 22 | 26.4 | 63.1 | 68.7 | 181.6 |
| 1000 | 2077 / 2294 | 60.8 | 100.0 | 100.0 | 100.0 (3) | 98.2 (57) | 100.0 | 20 | 22.4 | 53.0 | 63.3 | 192.1 |
| 1200 | 2210 / 2414 | 64.2 | 100.0 | 100.0 | 100.0 (3) | 98.2 (57) | 100.0 | 18 | 20.6 | 48.8 | 60.9 | 196.8 |
| 2000 | 2722 / 2880 | 74.9 | 100.0 | 100.0 | 100.0 (3) | 98.2 (57) | 100.0 | 11 | 14.0 | 34.6 | 51.8 | 214.5 |
| 3000 | 3346 / 3422 | 88.8 | 100.0 | 100.0 | 100.0 (3) | 98.2 (57) | 100.0 | 7 | 6.2 | 19.8 | 40.8 | 235.3 |
| Baseline (5,653) | 5653 | 100 | 100 | 100 | 100 | 100 | 100 | 0 | 0 | 0 | 0 | 258 (measured) |

### Contrast — Monday, Core only (E0, no event tier): this is why a naive Top-N fails

| Core | Setup % | Signal % | ≥80 Signal % | Mover % | Lab % | SEC − % | Bars − % |
|---|---|---|---|---|---|---|---|
| 500 | 12.3 | 5.8 | 0.0 | 3.6 | 16.9 | 86.9 | 82.0 |
| 1000 | 23.5 | 16.2 | 37.5 | 10.7 | 25.4 | 75.8 | 67.1 |
| 1200 | 29.6 | 25.3 | 43.8 | 11.9 | 29.8 | 70.2 | 61.6 |
| 2000 | 52.3 | 48.7 | 75.0 | 23.8 | 44.5 | 50.1 | 42.0 |
| 3000 | 79.4 | 77.3 | 93.8 | 60.7 | 74.3 | 24.8 | 22.8 |

Other policies are in `tables.md` / `dtu_study.json`:
- **E7** (gap ≥3% + protection, no filing triggers), Monday Core 500: all candidates 45.2%, setups and Signals 100%,
  movers 97.6%, Lab 96.6%, SEC −25.7%, bars −82.0%, symbols −74.5%, p90 50.5 s, but **100 late Signals**. It is
  cheaper than E5 because filing triggers add ~800–1,000 active names.
- **V2 capture:** 100% by construction. All 40 V2 scope and episode symbols are OPERATOR_ADDED; with ADV ranking
  alone, 1 Monday Signal was V2-scope.
- **Category G impact:** 0 of today's full-engine outputs lost at the mover level. The 3 movers missed under E5 had
  no ≥3% observation at a gate-passing scan in the full engine either.

## 8. Important misses (not hidden)

**E5 (recommended research candidate), any Core 500–1200:**

| Window | Population | Symbol | When | Detail | Why | Final |
|---|---|---|---|---|---|---|
| Fri | mover | MX | 23:43Z | +18.9%, $3.18, ADV rank 3,554 | move happened on thin after-hours prints; never ≥3% at a gate-passing scan | MISSED (full engine had no ≥3% candidate for it either) |
| Mon | mover | EDRY | 21:53Z | +11.3%, $48.16, rank 2,513 | same (after-hours) | MISSED (no full-engine output lost) |
| Mon | mover | FISN | 23:27Z | −10.7%, $6.25, rank 3,382 | same (after-hours) | MISSED (no full-engine output lost) |
| Mon | Lab | BIRK, CERT, DRVN, FIGS, VECO (+NTR at Core 500) | 08:04Z | INVALIDATED | identities created before the replay horizon (Thu 09-24 or earlier) cannot be proven captured | MISSED under a conservative replay artefact |
| Mon | Signals | 69 (Core 500) / 53 (Core 1200) | — | 3 / 1 of them score ≥80 | promoted at the scan the gap first crossed 3% | RECOVERED, 0–5 min late |
| Fri | Signals | 22 (Core 500) / 18 (Core 1200) | — | 2 / 0 score ≥80 | same | RECOVERED, 0–5 min late |
| both | WATCH identities | ~41% (Mon, Core 500) / ~33% (Core 1200) of all new identities | — | 2–3% gappers outside the Core | below the 3% trigger | MISSED; research statistics and Lab WATCH digest only |

**Core only (E0), ≥80-score Signals missed.** This is the case against a pure liquidity Core.

Friday:

| Core | Missed | Names (ADV rank, close return) |
|---|---|---|
| 500 | 3 | CHE (1,138, +0.3%), JEF (953, 0.0%), CAR (1,399, +1.4%) |
| 1000 | 2 | — |
| 1200 | 1 | — |
| 1500 | 0 | — |

Monday:

| Core | Missed | Names (ADV rank, close return) |
|---|---|---|
| 500 | 16 of 16 | — |
| 1200 | 9 | CAAP 88.0 (3,051, +5.2%), HHH 86.8 (1,570, +4.9%), PACS, HTHT, EC, BLFS, AVPT (2,063, +2.0%), STOK, JBI |
| 2000 | 4 | CAAP, AVPT, STOK, JBI |
| 3000 | 1 | CAAP |

## 9. Monday's 154 Signals

| Policy | CORE | PROTECTED (identity created while promoted) | EVENT_RECOVERED | RECOVERED, 1 scan late | OPERATOR_ADDED | MISSED |
|---|---|---|---|---|---|---|
| E0 Core 1200 | 38 | — | — | — | 1 | **115** |
| E5 Core 1200 | 38 | 102 | 8 | 5 | 1 | **0** |
| E5 Core 500 | 8 | 132 | 8 | 5 | 1 | **0** |

The E5 event triggers break down as: gap sweep 8, 8-K 3, Form 4 cluster 2.

Named examples. Price, ADV rank, coverage and spread are D-1 values; outcomes are paper and descriptive only.

| Symbol | Price | ADV20 (rank) | D-1 RTH coverage | Spread | Score | E0 @ 1200 | E5 @ 1200 | 30 min / close |
|---|---|---|---|---|---|---|---|---|
| SMJF | $1.60 | $1.27M (3,802) | 0.39 | 158 bps | 75.7 | MISSED | recovered | 0.0% / **+15.9%** |
| URG | $1.13 | $7.8M (2,780) | 0.98 | 88 bps | 70.7 | MISSED | recovered | −1.3% / −3.9% |
| ECX | $1.09 | $1.27M (3,801) | 0.49 | 91 bps | 75.0 | MISSED | recovered | −0.9% / −2.2% |
| ANNX | $3.64 | $12.5M (2,459) | 0.99 | 27 bps | 70.5 | MISSED | recovered | −2.7% / +2.2% |
| CRCT | $6.14 | $4.0M (3,184) | 0.71 | 17 bps | 66.3 | MISSED | recovered | 0.0% / 0.0% |

Outcomes by tradability bucket for Monday's Signals. This is descriptive; one day of data makes no edge claim. The
reference friction is V2's `friction_bps = 20` (round trip):

| Bucket | n | Confirmed @30m | Mean 30m | Median 30m | Mean close | Median half-spread |
|---|---|---|---|---|---|---|
| price < $3 | 15 | 9/15 | −0.71% | +1.06% | +1.77% | 37 bps |
| price ≥ $3 | 139 | 55/133 | −0.09% | −0.19% | −0.17% | 11 bps |
| ADV20 < $2M | 12 | 4/12 | −1.11% | −1.09% | +0.98% | 48 bps |
| spread > 100 bps | 17 | 7/16 | **−1.96%** | −0.99% | +0.08% | **79 bps** |
| spread ≤ 100 bps | 137 | 57/132 | +0.07% | −0.13% | +0.01% | 11 bps |
| D-1 coverage < 0.8 | 74 | 31/72 | −0.30% | −0.17% | −0.17% | 23 bps |
| ADV rank > 1200 | 115 | 48/110 | −0.18% | −0.10% | +0.02% | 16 bps |

**Execution cost is the real discriminator for low-priced names, not price itself.**
- Monday's 17 Signals with quoted spreads above 100 bps carry a median **half-spread of 79 bps**. That is about 4×
  V2's whole 20 bps round-trip friction assumption, just to cross once, and their 30-minute mean was −1.96%.
- Low price alone (< $3) did *not* underperform on this day: median +1.06% at 30 minutes, +1.77% mean at close,
  n = 15.
- This supports a **spread / cost rule over a price floor**, for Signal eligibility or presentation. That is a
  future Signal-policy question, not changed here.

## 10. Recommended candidate architecture (research only; nothing approved)

1. **D-1 snapshot, daily:** structural bucket + V1 floors → EVENT_ELIGIBLE pool (~3,925). Anything below the floors
   becomes AUTO_EXCLUDED with an explicit reason, because V1 cannot produce a candidate from it. This alone is
   zero-loss: −10.8% 1-minute bars and −30.6% symbols evaluated, with no change to any output.
2. **ACTIVE_CORE:** top-N of the pool by ADV20 $.
   - N is a *workload/latency* dial, not a capture dial. The smallest tested that met ≥95% was **500**.
   - N = 1000–1200 is a reasonable first live setting: fewer late Signals (53 vs 69 on Monday) and more WATCH
     coverage.
3. **EVENT_PROMOTED:**
   - a universe-wide `delayed_sip` snapshot sweep each cycle, |gap| ≥ 3% vs the previous close, with a TTL of the
     rest of the session;
   - promotion backfills the symbol's window-to-date 1-minute bars before the next scan, so V1 features are computed
     exactly as today;
   - open-identity protection until the identity is invalidated or expires;
   - 8-K (realtime) with a TTL of 3 sessions, as an optional low-volume trigger;
   - Form 4 only once transaction codes are available (P-clusters), **not** index-level clusters.
4. **OPERATOR:** OPERATOR_EXCLUDED > OPERATOR_ADDED (V2 scope, open positions, pending intents) > CORE > EVENT. Every
   non-active name carries an auditable reason.
5. **Spread:** keep as a measured D-1 feature (cost reporting and future Signal eligibility). **No spread exclusion
   at universe level:** only 3,100 of 3,925 names would pass a 50 bps cap, and today's high-scoring names include
   wide-spread ones.

**Operator view (design; not implemented).** Sentinel read-only commands:
- `/universe summary`: counts per state;
- `/universe excluded`: counts per reason;
- `/universe status SYM`: state, reason, rank, promotion trigger and expiry;
- `/universe excluded file`: CSV of every non-active symbol with its reason, from the D-1 snapshot.

## 11. Unresolved questions / data gaps

1. **Snapshot semantics** (`prevDailyBar` vs `dailyBar` across 04:00 / 09:30 / 16:00 ET, and odd-lot or extended
   trades in `latestTrade`) must be verified against V1's `prev_close` / last-bar close before the sweep can be
   trusted. The sweep only *promotes*; V1 still computes the features.
2. **WATCH-level coverage:** is losing ~33–41% of 2–3% WATCH identities in non-Core names acceptable? They feed the
   Lab digest and candidate research statistics only. A 2% sweep threshold would keep them, but returns SEC load to
   ~baseline.
3. **SEC load cannot fall much via the universe:** it is gap-driven and so are opportunities. A materially lower SEC
   load needs a *lookup policy* change (for example, a lookup only when a symbol could become a setup). That is a
   strategy change and out of scope here.
4. **Only two sessions were replayed**, with Friday SEC refresh OFF and Monday ON. The Friday "carried identity" horizon
   starts 09-25.
5. **Form 4 transaction codes and 8-K items universe-wide** need per-filing parsing (thousands of documents a day).
6. **Scan-time estimates are model-based.** A shadow run would measure them.

## 12. Verdict

- **DYNAMIC_TRADABLE_UNIVERSE_STUDY = PARTIAL.**
  - **Conclusive:** a liquidity-only Core fails, and the event tier is necessary; the V1-floor layer is zero-loss;
    the gap sweep is feasible on the existing entitlement.
  - **Not conclusive:** 2 sessions only, the sweep's semantics are unverified, and SEC/scan-time figures are
    estimates.
- **READY_FOR_DYNAMIC_UNIVERSE_IMPLEMENTATION = NO** (production). The next step is a *shadow* task: run the D-1
  snapshot and the delayed_sip sweep alongside the full engine for ≥5 sessions and compare, with no production change.
