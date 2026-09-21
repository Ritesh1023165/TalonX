# PQ-2B — SIP runtime adapter + OPEN/CLOSE finality + first-release provider contract

Date: 2026-09-21. Scope: provider/runtime/finality only. **Implemented, not activated.** Not performed: strategy research, profitability work, corporate-action/dividend redesign, final V2 release acceptance, release freeze, prospective validation, broker or Telegram work, production configuration/provider switch, any live session.

## 0. Verdict

**`PQ2B_ACCEPTED_WITH_BOUNDED_FOLLOWUPS`** — all 23 acceptance conditions are met by deterministic tests and bounded read-only probes; the bounded follow-ups (section 29) are fail-safe. `OPS-005` is marked **RESOLVED at contract level** (section 30) with the residuals stated there.

## 1. Repository state
Branch `feature/task131-option-a-integration`; starting HEAD `37b0fec` = origin; no TalonX process running (checked, nothing killed); working tree clean apart from git-ignored-db side files (`notifications.db-shm/-wal`, not staged). Production ledger `v2_lane.db` md5 `cff00b0f46e7e5b65e6f5903366fab28`, mtime 2026-09-15 — unchanged. See `repository_state.txt`.

## 2. Price-consumer inventory (Task A)
`price_consumer_inventory.csv` — every release-critical consumer, its field, its provider/basis **before** PQ-2B and **after** (release mode): liquidity prior close ≥ $5; 20-session median dollar volume ≥ $5M; target Session-1 open; entry recovery (same original session's open through Session 3's official close); paper fill/sizing/cost; Session-10 close; +1…+5 close recovery; settlement/reconciliation (persisted values only); dashboard marks (FINAL bars only); operator provenance; replay. Before PQ-2B the paths were CSV snapshot (all-adjusted), composite splices, yfinance/IEX (split-only since PQ-2A closure) with a UTC-date finality heuristic.

## 3. Provider architecture (Task B)
`provider_architecture.csv` — AVAILABLE / CONFIGURED / ENTITLED / QUALIFIED / ACTIVE kept separate for `AlpacaSipBarAdapter` (new), `CsvBarAdapter`, the legacy CSV loader, `CompositeBarAdapter`, `AlpacaIexBarAdapter`, `YFinanceBarAdapter`, Original's poller/gateway and the research SIP loaders. Nothing is "active" because credentials exist: the only ACTIVE default is the (stale) csv mode; SIP is implemented, entitled, qualified for the release contract, and **not active**.

## 4. Entitlement / configuration state
Credentials `APCA_API_KEY_ID` / `APCA_API_SECRET_KEY` are configured (values never recorded). Read-only probes: SIP daily bars HTTP 200; `end=now` and `end=now−10 min` → **403 "subscription does not permit querying recent SIP data"**, `end=now−16 min` → 200 (`probe_sip_recent_data_rule.json`) — the free-tier 15-minute rule is confirmed empirically, not just documented. No broker endpoint was called.

## 5. Selected provider contract (`release_provider_contract.json`, `V2_RELEASE_PRICE_CONTRACT@1`, fingerprint `ac5e51aa3599d6c9`)
```
AUTHORITATIVE RELEASE PROVIDER   Alpaca Market Data v2, GET /v2/stocks/bars
FEED                             sip (consolidated tape)      TIMEFRAME 1Day
ADJUSTMENT BASIS                 split  (split-adjusted price, inverse-split-adjusted volume, NO dividend adjustment)
FIELDS                           open = o, close = c, volume = v
SESSION IDENTITY                 New-York date of the bar timestamp t (must be NY midnight)
FALLBACK POLICY                  NONE — one authoritative provider, fail closed
CREDENTIALS                      APCA_API_KEY_ID, APCA_API_SECRET_KEY   TIMEOUT 20 s   PAGES <= 5   CACHE TTL 300 s
```
The contract answers the 11 questions of the brief: provider (Alpaca SIP daily); fields (prior close / liquidity `c`,`v`; entry & recovery `o`; exit & recovery `c`); basis (split-only); timestamps (source event time `t`, receipt time, session date, `usable_after_utc`, `basis_as_of`); when OPEN/CLOSE are usable (section 8/10); early closes (section 11); provider late/stale/unavailable/rate-limited/inconsistent/missing (section 17); fallback (NONE); compatible basis for every consumer (section 13); provenance (section 20).

## 6. SIP runtime adapter (Task C)
`talonx_v2/sip_adapter.py::AlpacaSipBarAdapter` — read-only market data, no websocket, no broker endpoint. Requests `feed=sip`, `adjustment=split`, `timeframe=1Day`, explicit `end = now − 16 min`, `sort=asc`, bounded pagination. Exposes `history()`/`session()` in the shape the V2 pipeline already consumes plus provenance (`_source_timestamp`=bar `t`, `_receipt_timestamp`, `_basis_as_of`, `_feed`, `_adjustment_state=SPLIT_ADJUSTED`). Malformed rows (non-finite/non-positive price, negative volume, high<low, timestamp not New-York midnight) are dropped; two disagreeing rows for one session drop the session; typed errors `ProviderTimeout / ProviderRateLimited / ProviderEntitlementError / ProviderMalformed / ProviderError`. `make_resolver(mode="sip")` builds it with the calendar-aware `FinalityPolicy`. **SIP V2 RUNTIME ADAPTER: IMPLEMENTED. PRODUCTION ACTIVATION: NO.**

## 7. Exact OPEN semantics (Tasks D, E)
Probe `probe_sip_semantics.json` + `probe_open_close_prints.json` (30 symbol-sessions: AAPL, MSFT, NVDA, PLTR, SOFI, SMCI, CHPT, UPST, GME, RIVN, ABCL, MARA on 2026-09-17/18; 2025-11-28 and 2025-12-24 early closes; 1-minute tape 04:00–post-market plus trades at the exact boundaries; SIP trade conditions `O`/`Q` open, `6`/`M` close):

| Comparison of the SIP daily bar `o` | Result |
|---|---|
| = official opening-auction print (cond `O`) | exact in 7/29; max deviation **1.19%** |
| = first `Q` (official open) print | exact in 9/30; max deviation 0.50% |
| = open of the 09:30 minute bar | equal in 20/30 |
| = first trade of the pre-market | equal in 1/30 |

**Definition:** the daily open is the provider's **first eligible trade of the session by participant timestamp** — *not* the official exchange opening auction price, *not* the 09:30 minute open. It is a provider-computed daily open. This is the same field the frozen Task107A/95G research used (same provider/feed/timeframe), so it is retained and the deviation is documented rather than "corrected". Missing / NaN / zero / negative / infinite open ⇒ the bar is dropped ⇒ unavailable ⇒ no fill, no zero (`test_04`, `test_05_06_07`).

## 8. OPEN finality / usability
Documented + measured: bars aggregate the tape over the whole New-York day **04:00 → post-market end** (daily volume / (regular + extended minute volume) = **1.000…1.098**, median 1.002); the daily open can in principle change until late/out-of-sequence earlier-timestamp trades are in; the free-tier query lag is 15 min; minute bars are recalculated within seconds for late trades (Alpaca minute-bar documentation).

**Rule (OPEN and CLOSE, identical):** session S's bar is usable iff `now ≥ session_close(S) + 4 h + 15 min + 1 min`, i.e. the post-market session has ended (20:00 ET; **17:00 ET after an early close**) plus a **conservative** margin equal to the provider's documented free-tier SIP delay window (15 min) and its late-trade recalculation margin. The live probe (section 31) shows the 15 minutes is *not required for visibility* (the in-progress bar is served near real time); it is kept as a margin because the minimal safe margin after post-market end could not be measured — settlement is not latency-sensitive, so conservatism is free. TalonX therefore consumes the target-session open **after that session is complete** — exactly the existing flow (paper fills are not real-time), now with an evidence-backed rule instead of a UTC-date heuristic that was one hour early in winter, blind to early closes and to the 15-minute rule (`test_08`, `test_14`).

**Revisions:** the provider exposes **no correction/version metadata**. Revision study (`probe_revision_study.json`): the Task107A snapshot (fetched 2026-09-06, ≈ 4 sessions after its last bar) vs a SIP re-fetch on 2026-09-21, both `adjustment=all`, 150 random symbols × 21 August sessions = **3,150 bars**: **2,751 identical (OHLCV), 399 in 19 dividend-paying symbols moved by one uniform price factor with identical volume (a dividend basis shift — ARCC, GLPI, SPY, …), 0 genuine revisions**. It also demonstrates why all-adjusted snapshots cannot serve a total-return ledger. Limitation: revisions in the first days after first usability are not observable with a snapshot fetched 4 sessions later; TalonX's mitigation is structural — the persisted execution value is immutable and a later provider value is never applied silently.

## 9. Exact CLOSE semantics (Task F)
The SIP daily close **equals the official closing-auction cross print (cond `6`) in 30/30 samples — including the four early-close sessions (13:00 ET)** (`stats.close_vs_closing_cross_6`: n=30, exact 30, max deviation 0.0). It is **not** the last regular minute bar's close (equal in 4/30 — the 16:00 minute holds the cross) and **not** the last extended-hours trade (equal in 2/30). "Session-10" is the official exchange-calendar session (`exchange_calendars` XNYS via the existing `v2cal`); after-hours prices are never substituted; no next-day price is ever substituted for the target close; unavailable ⇒ the unchanged +1…+5 recovery, then `EXIT_UNRESOLVED`.

## 10. CLOSE finality / usability (Task G)
Same rule as section 8. The closing cross is on the tape at the official close (SOFI early close 2025-12-24: cross at 18:00:00.076 UTC = 13:00 ET, daily close 27.48 = cross); the daily bar's high/low/volume keep growing until post-market ends, so TalonX waits for the complete bar rather than settling on a partial one. Corrected consolidated closes are an excluded trade class in Alpaca's bar documentation; with no version metadata the limitation is stated (section 8), not inferred away.

## 11. Early closes (Task P)
`v2cal.session_open_utc` (new) and `session_extended_end_utc` (new) reuse the existing `exchange_calendars` XNYS calendar — no duplicate calendar logic. Probe: on 13:00-ET early closes the tape's last minute bars are 16:55–16:59 ET (post-market ends **17:00 ET = close + 4 h**); on normal days 19:55–19:59. Test `test_14`: 2025-11-28 close 18:00Z, extended end 22:00Z, usable 22:16Z; 2025-11-26 close 21:00Z, usable 01:16Z next day; a hard-coded 16:00-ET assumption would have declared the early-close bar final 1 h 16 min early. DST (EDT/EST bar timestamps `04:00Z`/`05:00Z`, opens 13:30Z/14:30Z) covered in `test_20`.

## 12. Causal timing model (Task H)
For every release-critical price TalonX distinguishes and persists: **source event time** (`source_timestamp` = provider bar `t`), **provider availability / usability time** (`usable_after_utc` = `session_extended_end + 16 min`, a conservative completeness margin; the provider itself serves the in-progress bar earlier but provisionally), **TalonX receipt time** (`receipt_timestamp`), **session identity** (`session`, NY date), **finality/usability time** (`usable_after_utc`), and the **basis date** (`basis_as_of`). A bar is never used before it is usable, historical values fetched later are never presented as decision-time values (basis date recorded), and the pinned/replay clock is the *start* of the pinned date so same-day data is never final. Limitation stated: the provider's actual publication timestamp of a bar is not exposed. Measured instead (section 31): the in-progress current-day bar is visible ~81 s after the open and is provisional; the completed-bar rule never relies on that.

## 13. Liquidity history basis (Task I) — the PQ-2A residual is closed
Release mode uses **option A + C**: one authoritative split-only provider for the entire 20-session window (no CSV snapshot is even read — `test_31_32` seeds a poisoned CSV and proves it is never touched) and fail-closed on anything unprovable. `CompositeBarAdapter` now refuses any splice whose **adjustment states differ** (an all-adjusted snapshot + split-only tail) in addition to the PQ-2A split/evidence checks. Release mode additionally requires the window to be **exactly the 20 XNYS sessions immediately preceding entry** (`liquidity_window.evaluate_liquidity_checked`; a stale response missing the 2 most recent sessions ⇒ `NON_CONTIGUOUS_WINDOW_2_OF_20_SESSIONS_MISSING`, a non-terminal skip retried next tick — `test_18`). Missing history keeps the frozen `NO_PRIOR_BARS` / `INSUFFICIENT_HISTORY` reasons. Note the strategy fingerprint hashes `liquidity.py`; that file is **byte-identical** — the new precondition sits in a plumbing module (an earlier draft that edited `liquidity.py` changed the fingerprint and was reverted after investigation).

## 14. Dollar-volume semantics (Task J)
Unchanged: `median over the 20 sessions of close × volume ≥ $5,000,000` and last `close ≥ $5` (`test_27_28`: 5.00 passes / 4.99 fails; $5,000,000 passes / $4,999,999 fails). Fields: provider daily `c` and `v`; the volume is **consolidated full-tape-day volume including extended hours** (section 8), inversely split-adjusted, so `close × volume` is **invariant across a split**: NVDA 2024-06-05…06-11 raw (1,224.40 × 52.84 M) vs split-only (122.44 × 528.4 M) agree to 0.2% on every row (`test_29_30`); the gate decision is identical on the raw and split series, and the *incompatible* mixture (split-adjusted price × raw pre-split volume) understates dollar volume > 5× (proved, not assumed).

## 15. Fallback policy (Task K)
**Option A: one authoritative provider, fail closed** (`fallback_mode = "NONE"`). Rationale: no other candidate satisfies every dimension — IEX (single-venue volume breaks the $5M gate), yfinance (open/close semantics unverified, no correction metadata), the snapshot (not live, all-adjusted). `provider_contract.fallback_mismatches` lists every mismatching dimension; `fallback_allowed` returns False for the release setting and for every existing candidate even under a hypothetical "compatible only" mode (`test_34_35`); a provider outage yields no price, never a silent switch.

## 16. Provider disagreement (Task L)
The primary is always authoritative. An optional **witness** may be attached to `PricingResolver`; when its open/close differs by > 0.5% the event is **logged** (`disagreements`, action `LOGGED_ONLY_PRIMARY_AUTHORITATIVE`, surfaced in the service status) and nothing else happens — no averaging, no fallback, a failing witness is ignored (`test_33`).

## 17. Outage / rate limit / stale / malformed (Task M)
Every case yields an explicit *unavailable* and **no trade, no settlement, no zero** (`test_15_16_17`, `test_18`, `test_19`, `test_05_06_07`, malformed-shape and conflicting-duplicate tests): timeout → `PROVIDER_TIMEOUT`; HTTP 429 → `PROVIDER_RATE_LIMITED`; 401/403 → `PROVIDER_ENTITLEMENT`; other HTTP/network → `PROVIDER_ERROR`; bad body → `PROVIDER_MALFORMED_RESPONSE`; missing symbol/session → `NO_BAR`; stale response → `NO_BAR` for the session and `NON_CONTIGUOUS_WINDOW…` for liquidity; NaN / zero / negative / infinite / missing price or bad timestamp → the row is dropped; a wrong-date bar is never substituted for the requested session. Deadlines are untouched.

## 18. Entry recovery (Task N) — unchanged
Session 1 target; recovery through the official close of Session 3, then expiry. A missing Session-1 bar is retried by the existing tick machinery; when it appears the fill uses **Session 1's open, not Session 2's** and the provenance records Session 1 (`test_21`); deadline arithmetic asserted (`test_22`); `max_entry_staleness_sessions = 3`. No new recovery policy.

## 19. Exit recovery (Task O) — unchanged
Session-10 close → first available close in +1…+5 → otherwise `EXIT_UNRESOLVED`; a close at +5 is used, at +6 never; exhausted ⇒ no SELL, no exit price, no P&L (`test_23`–`test_26`); a not-yet-usable close never settles early (`test_exit_bar_not_yet_final…`). No extension beyond +5, no intraday proxy, no zero.

## 20. Provenance (Task Q)
Entry/exit/trade provenance (PQ-1/PQ-2A) now also carries `feed`, `contract`, `contract_fingerprint`, `usable_after_utc`, `session_tz`. The liquidity decision persists `source_meta.liquidity_window = {n_sessions, first/last session, providers, feeds, adjustment_states, contract, strict_contiguous_window}`. Survives restart (`test_38`); legacy rows stay NULL (nothing fabricated); composite rows still name the real supplier.

## 21. Corporate-action compatibility (Task R)
`test_36`: split during the hold on SIP prices (entry fetched right after the entry session, exit later) — 400 → 4,000 sh, +8% (not −89%); a 10:1 split **inside** the liquidity window leaves the gate decision unchanged. The PQ-2A split suite (44 tests) is green.

## 22. Dividend compatibility
`test_37`: SIP fills carry `SPLIT_ADJUSTED` (dividend-unadjusted), so PQ-2A's dividend guard admits the position; price P&L $800 is untouched, a $0.50 dividend accrues $200 and is credited after payable; cash = 300,000 + 800 + 200 — no double count. The PQ-2A closure suite (45 tests) is green.

## 23. Late-published dividend decision (Task S)
Evidence (`probe_dividend_publication_lead.json`): all 8 future-dated ex-dates in a 40-symbol basket are already listed ≥ 9 days ahead; settlement itself re-queries fresh evidence and fails closed if the source is down. Publication after settlement should therefore be rare — but not excludable, and a silent miss understates total return. **Implemented (small, bounded):** `dividends.catch_up_recent_closed` — positions CLOSED within the last **5 sessions** (= the +5 recovery window), same idempotent receivable lineage, never reopens a trade, skips trades with unsupported/conflicting evidence or a non-dividend-unadjusted / legacy fill basis, never rescans older trades (`test_47`–`test_50`); wired into the service dividend phase before credit.

## 24. Replay compatibility (Task V)
`provider_contract.classify_replay` (rule-based, tested in `test_39`):

| Replay evidence | Verdict | Why |
|---|---|---|
| Task107A/95G SIP snapshot & Task112R/116 replays built on it | **PARTIALLY_COMPATIBLE** | same provider/feed/timeframe and the same open/close/volume definitions (compatible); differs in dividend adjustment (`all` vs `split`), snapshot vs live timing/finality not reproduced, no corporate-action position accounting in replay |
| yfinance-based parity studies | INCOMPATIBLE | feed scope and open/close/volume semantics unverified |
| IEX studies | INCOMPATIBLE | single-venue volume |

No profitability was recomputed and no historical performance claim is transferred across the differing basis/finality/accounting semantics.

## 25. Readiness / configuration (Tasks T, U)
`talonx_v2/provider_contract.py::check_readiness` (CLI: `python -m talonx_v2.provider_contract`, exit 2 unless QUALIFIED): `NOT_CONFIGURED → CONFIGURED → REACHABLE → ENTITLED → QUALIFIED`; QUALIFIED requires the provider to **honour `adjustment=split`** on a known 10:1 split (NVDA 2024-06-07 raw/split open ratio ≈ 10, volume ratio ≈ 10, close × volume invariant). ≤ 3 read-only calls. `talonx_v2.run --mode live --pricing-mode sip` refuses to start unless QUALIFIED (`test_live_start_in_sip_mode_refuses…`); missing credentials, entitlement failure, unreachable provider and an unhonoured basis are each reported (`test_40`–`test_42`). The service status shows the active contract id/fingerprint, provider, feed, adjustment, fallback mode, finality rule and recent witness disagreements. Env vars merely existing never starts anything.

## 26. Tests
See `test_results.txt`. New `tests/test_pq2b_provider_contract.py` (51 tests; matrix 1–50); mutation check: 11 deliberate regressions (dividend-adjusted request; finality ignoring the post-market span / the 15-min lag / the early-close calendar; contiguity removed; intraday timestamps accepted; composite basis-state check removed; witness averaging; unbounded catch-up; legacy backfill; fallback enabled) are all caught.

## 27. Strategy fingerprint
`V2 STRATEGY FINGERPRINT: e2acf6454789217e`. **STRATEGY RULES CHANGED: NO.** Thresholds `(2,10,1,20,5,000,000,5.0,5,3)` asserted; `talonx_v2/config.py` and `liquidity.py` byte-identical.

## 28. Defects corrected
1. Finality was a UTC-date heuristic: 1 h early in winter, blind to early closes and to the free-tier 15-minute rule (now calendar-aware and evidence-based).
2. A stale/partial provider response silently made the liquidity gate use an OLDER 20-bar window (now fail-closed in release mode).
3. Composite could splice an all-adjusted snapshot with a split-only tail (now refused on any adjustment-state mismatch).
4. Adapters cached history forever within a process (SIP adapter has a TTL; stale-cache refetch tested).
5. Provider failure reasons were collapsed to one string (now typed: timeout / rate limit / entitlement / malformed).
6. A dividend published after settlement was never picked up (bounded catch-up).
7. (found while implementing) an edit to `liquidity.py` changed the strategy fingerprint — reverted and re-implemented in a plumbing module.

## 29. Remaining gaps (all fail-safe)
1. No provider correction/version metadata: a correction after first usability cannot be detected; execution values are immutable and later values never applied silently. Revision evidence covers ≥ 4 sessions after publication (0 of 3,150 bars), not the first days.
2. The daily OPEN is the provider's first eligible trade, up to ~1.2% away from the official auction print in the sample; this matches the research data but is not an exchange-official price.
3. Actual per-bar publication time is not exposed. Same-day live latency was observed for the OPEN only (section 31); the minimal safe margin after post-market end for the CLOSE could not be observed (the session ends ~6 h after the probe window) — the rule therefore keeps a conservative +16 min and is not shortened without a multi-day close-latency study.
4. Free-tier rate limits (200 requests/min) are not stress-tested; adapter caches (300 s TTL) and per-symbol calls are the mitigation; a 429 is a typed, retried-next-tick failure.
5. The default pricing mode remains the stale `csv`; activation of `--pricing-mode sip` (and the operator decision to use it) is a separate gated step.
6. Carried over: entry price fetched exactly on a split's ex-date fails closed; mergers/spin-offs/renames/unit splits fail closed; special/foreign dividends unsupported.

## 30. OPS-005 decision
**RESOLVED at contract level.** Checklist: (1) executable authoritative contract — yes (`RELEASE_CONTRACT`, adapter, `--pricing-mode sip`); (2) runtime adapter — yes; (3) OPEN semantics — defined and measured; (4) OPEN usability/finality rule — defined, evidence-backed, limitation stated; (5)–(6) CLOSE — same, official closing cross 30/30; (7) early closes — yes (calendar, probe, tests); (8) split-only enforced — request param + readiness self-check + adjustment-state guards; (9) liquidity basis compatible — same provider, exact window, composite mismatch refused; (10) outage/missing/stale fail-safe — tested; (11) fallback explicit — NONE; (12) provenance adequate — yes; (13) corporate-action accounting compatible — tests 36/37; (14) tests demonstrate the contract — yes. Residuals are the bounded gaps above; **production activation was not performed and is not implied**.

## 31. Live OPEN-availability probe (Task E) — `probe_live_open_latency.json`, `probe_live_open_provisional_check.json`
Read-only poller, session 2026-09-21 (open 13:30:00Z), AAPL / SOFI / MARA / GME polled every 30 s (13:25–14:05Z, 308 polls, all HTTP 200):

| Observation | Result |
|---|---|
| bar for the current day | **absent** at the last pre-visibility poll (13:30:49Z, 49 s after the open); **first visible 13:31:21Z = 81 s after the open**, simultaneously for all 4 symbols |
| bounded by the request `end`? | **No.** The polls used `end = now − 16 min` (09:15 ET — before the regular session) yet the first visible bar already held regular-session volume (AAPL 1,336,238 sh) — the current-day bar is served in near real time; the 15-minute rule constrains the `end` parameter, not the in-progress bar |
| stability of `o` once visible | **unchanged for the next 33 minutes on 4/4 symbols** (AAPL 335.28, SOFI 17.46, MARA 13.94, GME 22.78; 65 polls each) |
| relation to the 09:30 minute bar | MARA/SOFI: `o` = first regular minute open; AAPL: 335.28 vs 335.36 (first-eligible-trade ordering by participant timestamp — same behaviour as the completed-day study) |
| the in-progress bar is complete? | **No** — close/high/low/volume keep moving (AAPL close 334.015 at 13:31, 336.82 at 13:50); volume at 13:50Z is 5.97 M vs a full-day ~36–87 M |

Consequences for the contract: (1) the in-progress bar **must** be treated as PROVISIONAL — without the finality policy the resolver would consume a partial close and volume; (2) the OPEN was stable for 33 minutes on one session and four symbols — this is *supportive but not sufficient* evidence to relax the completed-bar rule for OPEN (a single session cannot bound late/out-of-sequence changes), so the uniform rule stands and an earlier-OPEN rule is recorded as a possible follow-up needing a multi-session intraday-stability study; (3) my earlier assumption that the daily bar is only visible after end + 15 min was wrong for the current-day bar and is corrected above.

## Files in this bundle
`README.md`, `repository_state.txt`, `price_consumer_inventory.csv`, `provider_architecture.csv`, `release_provider_contract.json`, `probe_sip_semantics.json`, `probe_open_close_prints.json`, `probe_revision_study.json`, `probe_sip_recent_data_rule.json`, `probe_dividend_publication_lead.json`, `probe_live_open_latency.json`, `test_results.txt`.
