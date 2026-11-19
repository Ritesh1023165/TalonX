# Opportunity Engine 600-name admission cap: preview and deployment proposal (NOT deployed)

**Status: `PREVIEW_ONLY_NOT_DEPLOYED`.** No config, environment variable, code or live store was changed. No strategy
returns were calculated or inspected to choose the cap.

Source: `results/opportunity/market.db` (read-only), via `universe_cap_preview.py`. Outputs: `preview.json`,
`membership_2026-10-08.csv`.

## Current live policy

- **`DTU_V2_LIVE_FLOOR`**, policy fingerprint `65f3285f8181c552` (`talonx_opportunity/universe_tiers.py`; deployed
  2026-10-04 at `daa1d29`).
- **Floors.** As-traded D-1 close ≥ $5. ADV20 ≥ $20M, where ADV20 = mean(close × volume) over the 20 completed XNYS
  sessions ending at D-1. Bars are Alpaca SIP 1Day `adjustment=raw`, and all 20 sessions are required. The V1
  structural and floor rules are retained.
- **Admissible set** = ACTIVE_CORE (top 1,200 by live ADV20) + EVENT_ELIGIBLE (the remaining qualifying names, which
  become active on a GAP ≥ 3% or SEC 8-K trigger).
- The snapshot's `core_rank` already ranks qualifying names by live ADV20, descending, with ties broken by symbol
  ascending. **The proposed top-N is exactly `core_rank ≤ N`.** It adds no new identity, share-class, sector or
  volatility rule.

## Preview (latest snapshot: window 2026-10-08, input session 2026-10-07, built 2026-10-08T00:02:39Z, ~2.7 h after that session's close)

| | Current admissible | Cap 500 | **Cap 600** | Cap 700 |
|---|---|---|---|---|
| Names | 2,093 (1,200 core + 893 event-eligible) | 500 | **600** | 700 |
| ADV20 cutoff (last selected) | $75.0M (core rank 1,200) / $20M floor | $256.5M (XP) | **$205.3M (PCVX)** | $172.7M (ANF) |
| Removed vs current admissible | — | 1,593 | **1,493** | 1,393 |
| Exact ADV20 ties at any boundary | — | 0 | 0 | 0 |

- **Every cap fills.** About 2,090 names qualify each day, so no threshold would ever be relaxed to fill slots.
- **Price, ADV20 and exchange distributions** per cap and window are in `preview.json`. At 600 on window 10-05, the
  median close was $134 and median ADV20 $420M; there were 7 names at $5–10; 375 NYSE / 224 NASDAQ / 1 BATS.
- **Sector:** **UNKNOWN**. No sector or SIC metadata is stored for the Opportunity Engine universe. None was fetched
  or invented.
- **Membership turnover** across consecutive available operational snapshots, at cap 600:

  | Change | Entered / left |
  |---|---|
  | 10-05 → 10-06 | 7 / 7 |
  | 10-06 → 10-07 | 6 / 6 |
  | 10-07 → 10-08 | 6 / 6 |

  Caps 500 and 700 are similar (5–8 names per day).

## What a 600 cap changes, and what it does not

1. **Newly admissible Opportunity Engine names:** at most 600 (core_rank ≤ 600). Ranks above 600 could no longer create
   a *new* candidate identity. Under this proposal the event tier for those names is removed too, so a gap or 8-K does
   not admit them.
   - **Alternative for the owner:** keep the event tier and only shrink the core from 1,200 to 600.
   - **Difference:** the alternative keeps admissible ≈ 2,093 and saves fetch workload only, not breadth.
2. **Protected subscriptions (fetched, not admissible):** remain as today. These cover:
   - V2 open positions and intents;
   - the V2 execution scope (39, `OPERATOR_ADDED`);
   - operator adds;
   - open BULLISH/BEARISH setups until invalidated or expired;
   - the current window's promoted names through their horizon;
   - same-window WATCH identities.
3. **Benchmarks and shared services:** SPY and other references, the SEC 8-K feed, and V2's daily SIP pricing are
   separate and unchanged.
4. **V2's fixed campaign universe** (39, RC1) is untouched. OPS-006 stays open.

**Why the monitored total stays above 600.** Effective active = admissible core + protections + V2 scope + operator
adds. Today the median effective active set is about 1,430–1,510, with 39 operator/V2 names and 230–310
event-promoted names. Under a 600 cap the steady state is roughly 600 + 39 + open-setup protections. During the first
sessions after deployment, setups opened under the old universe stay protected until they expire, so the total decays
from about 1,500 toward about 650–750 over a few sessions.

## Estimated workload (assumptions stated)

| Item | Today | Cap 600 (estimate) |
|---|---|---|
| REGULAR 1-min fetch: fetched symbols per cycle (median) | 1,459–1,532 | ~650–750 at steady state |
| Batches per cycle (~180–200 symbols per request observed) | 8 | ~4 |
| Cycle duration (median) | 11.9–16.7 s | ~6–9 s (assumed proportional to batches) |
| DTU event sweep (universe-wide snapshots, ~6 requests per minute) | needed for GAP triggers | not needed for admission if the event tier is removed. It is still a shared cost while the DTU shadow or the alternative runs |
| SEC lookups / features / scoring | ~1,500 active | ~650–750 |

**Assumptions:**
- Request count scales with symbol count divided by batch size. Pagination at bar-density peaks is ignored.
- The Alpaca 200/min account quota is shared with V2, VR and research fetches.
- Halving per-cycle requests mainly frees quota headroom. Rate-limit risk was the binding operational constraint on
  2026-09-30.

## Deployment proposal (for an owner decision; not executed)

**Change.** A new policy `DTU_V3_TOP600` (a subclass, so DTU_V1/V2 fingerprints are unchanged). `core_size=600`, plus
`admit_event_tier=False` under the recommended option, or `True` under the alternative. Selected with
`TALONX_DTU_POLICY=DTU_V3_TOP600`.

**Classification.**
- STRATEGY_MATERIAL for `ingestion` and `discovery`: it changes the admissible population and therefore every
  downstream candidate, promotion and review-alert population.
- Promotion, evaluators and outcomes are unchanged code but see a different input population.

**Segmentation.**
- A new universe segment starts at the first window built under DTU_V3, for:
  - OE candidates;
  - promotions and review alerts;
  - outcome tracking;
  - the VR registry (VR entries are interrupted anyway);
  - DTU shadow comparisons if they run.
- It is never pooled with DTU_V1/V2 windows.

**Tests to add before deployment:**
- `core_rank ≤ 600` selection with a deterministic tie-break;
- fewer than 600 qualifying (keep fewer; no relaxation);
- protections still fetched but not admissible;
- V2 scope always fetched;
- fail-safe without a snapshot;
- event-tier on/off variants;
- fingerprint stability of DTU_V1/V2;
- dashboard counts.

**Deploy.** Off-hours, through the documented component-specific restart of `ingestion` and `discovery` with
`declare-change` STRATEGY_MATERIAL. Verify the first 600-name snapshot before PREMARKET.

**Rollback.** `TALONX_DTU_POLICY=DTU_V2` plus a restart of the same components (bit-identical DTU_V2 fingerprint). The
segment boundary is recorded both ways.

**Owner decisions needed:**
- **(a)** Cap value: 600 recommended for parity with the request; 500 and 700 are shown for comparison only.
- **(b)** Event tier for ranks above N: removed (recommended, matching "600-stock universe") or kept.
- **(c)** Deployment window and segment label.
