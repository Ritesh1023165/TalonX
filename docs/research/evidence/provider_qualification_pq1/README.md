# PQ-1 — Provider Qualification & Price Finality

Date: 2026-09-19. Scope: V2 first-release qualification only. No final release acceptance, release freeze, prospective paper validation, provider activation, trading, notification, or production mutation occurred.

## 1. Repository state

- Required branch: `feature/task131-option-a-integration` — confirmed.
- Starting HEAD: `be5720d8197d4c1cf265b5baea8f0b39f2057537` — exactly the reported accepted HEAD.
- Starting status: clean and tracking the matching origin branch.
- Runtime safety: no TalonX process detected.
- Raw capture: `repository_state.txt`.

## 2. Executive verdict

**`PQ1_NOT_ACCEPTED`**.

The data landscape is better than the old Task 117 entitlement snapshot: the currently configured Alpaca credentials can now read recent SIP historical daily bars. That resolves neither of the release-blocking semantic gaps:

1. no available runtime path has an evidence-backed immutable/sufficient-finality boundary for the exact prospective open and close consumed by TalonX; and
2. the existing `adjustment=all` execution path is not paired with split share/basis changes or dividend entitlement accounting. A split or dividend during a position can therefore make persisted shares/cost/P&L economically inconsistent.

The task does **not** select or activate a provider merely because the endpoint is reachable. `OPS-005` remains open. Current provider data appears available, so this is `PQ1_NOT_ACCEPTED`, not `PQ1_BLOCKED_PROVIDER_REQUIREMENT`.

## 3. Price-consumer inventory

The machine-readable inventory is `price_consumer_inventory.csv`. Release-critical consumers are:

1. liquidity: last prior close and median of `close × volume` over exactly 20 completed XNYS sessions strictly before target entry;
2. qualification/admission: the same liquidity result plus target-session open availability;
3. target entry and Session-3 recovery: the **original target session's open**, never a later session's open;
4. paper fill, whole-share sizing, cost basis and cash debit: one identical persisted entry value;
5. Session-10 target exit: target session close;
6. exit recovery: first available close in the next five eligible XNYS sessions, then `EXIT_UNRESOLVED`;
7. settlement/reconciliation: persisted entry/exit values, never a refreshed historical substitute;
8. dashboard: persisted executions for realized values and latest completed-session close for marks; unavailable remains unknown/partial, never zero;
9. replay: historical OHLCV, release compatibility classified separately.

## 4. Provider architecture and state

See `provider_inventory.csv` and `qualification_matrix.csv`.

- `CsvBarAdapter`: available/configured and the default when V2 is started; qualified only for bounded deterministic replay. Its snapshots are stale prospectively.
- `YFinanceBarAdapter` / `composite-yf`: available/configured and historically opt-in active, but not active/default now. Strong bounded parity does not establish causal availability, correction stability, delisted coverage, or a safe fallback contract.
- Alpaca IEX daily: available/configured; explicitly non-conformant because single-venue volume changes the liquidity input and its daily first/last eligible trades are not the SIP consolidated bar.
- Alpaca SIP daily: available via research code and currently entitled; there is no V2 runtime SIP adapter. Qualified for consolidated historical liquidity data, not for current-runtime prospective execution finality.
- Task107A/95G SIP CSV: qualified historical snapshot, not a prospective feed.
- Original's yfinance poller and the shared Alpaca intraday gateway are different lanes/contracts and are not V2 daily providers.

`AVAILABLE IN CODE`, `CONFIGURED`, `QUALIFIED`, and `ACTIVE` are intentionally separate columns. No TalonX process was active during PQ-1.

## 5. Exact proposed first-release price contract

This is the contract required for acceptance; it is **proposed but not yet executable/accepted**.

### Liquidity price/data

- Provider/feed: one authoritative consolidated-US-exchange daily-bar feed; the only presently plausible candidate is Alpaca SIP historical bars.
- Fields: daily `close` and `volume` for the 20 XNYS sessions strictly before target entry.
- Adjustment: split-normalized price and inversely split-normalized volume on the same basis; dividend adjustment must not distort dollar-volume economics. Mixing adjusted price with raw volume is forbidden.
- Finality: each session must be complete and beyond the provider's defined correction boundary. “Calendar date is before today” is not, by itself, sufficient evidence of provider finality.
- Missing/stale/error: fail closed with `NO_PRIOR_BARS`, `INSUFFICIENT_HISTORY`, or provider-unavailable state; no alternate provider is silently substituted.

### Entry price

- Provider/feed: same authoritative provider/feed selected for the strategy version.
- Field: daily-bar `open` for the first XNYS session strictly after cluster activation. This is the provider's first qualifying daily-bar trade, **not claimed to be an exchange official opening-auction print**.
- Session: target session remains fixed through recovery; processing on Session 2/3 still consumes the target session's open.
- Availability/finality: only after the session is complete and the chosen provider-finality boundary is satisfied. Current code's prior-date `FINAL` label is a TalonX date rule, not proof of provider immutability.
- Missing: unknown/unavailable; never zero. Retry only through the accepted Session-3 deadline; after it, no fill.
- Invalid: NaN, infinity, zero, negative, wrong-session, future, or provisional values are rejected.

### Exit price

- Provider/feed: the entry position's authoritative provider contract; no mid-position provider switch without an audited compatibility/revalidation event.
- Field: daily-bar `close` for entry session + 10 XNYS sessions. It is the provider's last qualifying daily-bar trade, not claimed to be an official closing-auction print.
- Early close: the exchange calendar defines the session and actual close time; no fixed 16:00 ET assumption.
- Missing: earliest eligible close in sessions +1 through +5; after all five pass, `EXIT_UNRESOLVED`. No backward fill, “latest” substitution, or made-up trade.
- Revision: the execution value used at settlement is immutable in the ledger; a later provider correction must be separately recorded and reconciled, never silently rewrite cash/P&L.

Because the provider correction boundary and corporate-action lifecycle below are unclosed, this proposed contract is **not accepted**.

## 6. Raw/adjusted and corporate-action policy

Existing Task107A/95G, yfinance, and Alpaca adapter requests use the conceptual `adjustment=all` basis. Prior evidence shows split-adjusted OHLC and inversely adjusted volume agree closely across four split cases, preserving `close × volume`.

That is adequate for historical liquidity comparison but not sufficient for prospective paper accounting:

- forward/reverse split: the position must transactionally adjust share count and per-share basis exactly once on the effective session, retaining total cost; current V2 does not;
- cash dividend: price return and cash entitlement must be separated or a deliberately total-return-adjusted synthetic ledger must be used consistently; current V2 does neither and must not double-count;
- stock dividend/spin-off/merger/symbol change/cash-in-lieu: fail closed and block new exposure unless explicitly supported;
- historical provider revisions must not mutate already-settled execution economics.

Until this layer exists and is tested, `adjustment=all` must not be represented as corporate-action-safe execution accounting.

## 7. Corporate-action and edge cases

Reused evidence rather than redownloading a large history:

- normal sessions and dividend back-adjustment: Task117 22-symbol/1,210-field study;
- splits: NVDA, AVGO, SMCI (10:1) and CMG (50:1), 657 common sessions for live names;
- delisted/unavailable: AAN and WOW return no yfinance history while SIP snapshots retain history;
- missing/future/holiday: adapter tests reject or return no bar without “latest” substitution;
- early close: Package 3 verifies the 2026 day-after-Thanksgiving XNYS close as 18:00 UTC, not 21:00 UTC;
- reverse split: no bounded like-for-like provider fixture was found in accepted prior evidence — explicit remaining gap, not fabricated.

## 8. Provider parity results

Reused Task117 results:

- initial domain: 23 requested / 22 compared; 1,210 field observations; 660 liquidity classifications; 100% of adjusted open/close within 0.5%; 100% volume within 7%; zero missing common-session dates; AAN absent;
- expanded domain: nine symbols, 657 common sessions for live names, 1,062 more liquidity grid points;
- combined: **1,722 liquidity decisions, zero flips**;
- four split windows: maximum open/close relative difference at most `0.000109`; maximum volume relative difference `0.029483`;
- delisted AAN/WOW: zero yfinance rows versus retained SIP history.

These results remain `PROVIDER_EXPANDED_PARITY_INCONCLUSIVE`, exactly as the original evidence concluded. They do not prove point-in-time availability or universal interchangeability.

## 9. V2 decision parity

- Liquidity pass/fail: 0 changes across 1,722 bounded observations.
- `$5` and `$5M` gates: no flips in the tested domain.
- Entry/exit availability in the initial overlap: no yfinance miss where SIP had a usable common bar.
- Whole-share/P&L: prior study reported no 10-session return-sign change and small price differences; it did not establish identical share quantities for every possible `$10,000` boundary.
- Delisted historical decisions: materially non-comparable under yfinance-only history.
- No profitability was recomputed in PQ-1.

## 10. Causal availability and finality

For every price, TalonX must distinguish:

- source event time: provider bar/session timestamp;
- receipt time: when TalonX received the response;
- data availability time: when the endpoint was entitled to return it;
- finality time: when the contract permits economic use.

Alpaca documents that daily bars aggregate eligible trades by New York day, SIP is consolidated across exchanges, historical SIP on the free/basic path may be queried once the end is at least 15 minutes old, and late trades can update bars. The 15-minute access rule is **not** an immutability guarantee. No official provider guarantee was found that a daily open/close cannot later be corrected. Therefore exact finality remains insufficiently evidenced.

## 11. Open and close finality

- Open: current resolver rejects today's bar as provisional and accepts prior dates. That safely avoids an intraday partial bar, but “next date” is only a local heuristic. Required release behavior is wait until a provider-qualified boundary, preserve source/receipt timestamps, and never substitute another provider on disagreement.
- Close: same issue, plus late/corrected trades. Early-close timing is correct through `exchange_calendars`; provider publication finality is not.
- Disagreement: authoritative provider wins only if already qualified. A different provider is diagnostic evidence, not an automatic price chooser.

## 12. Outage/degraded behavior

- timeout/exception/rate limit: resolver returns provider error/empty history; no fill;
- 404/symbol unavailable: no bar; no “latest” substitution;
- stale/wrong-session/provisional/invalid: rejected;
- partial universe outage: affected symbols fail closed; unaffected observations may proceed only under the same authoritative contract;
- total outage: no new price-dependent trades; pending recovery/exit obligations remain visible;
- target exit exhaustion: `EXIT_UNRESOLVED` and account block semantics remain intact.

## 13. Fallback policy

**Policy A: one authoritative provider, fail closed.** No qualified fallback exists. `composite-yf` is not approved fallback merely because bounded numerical parity is strong. If a fallback is later qualified, activation must be explicit, semantically normalized, durably attributed, decision-revalidated, and must define whether an open position may switch. Current answer: mid-position switching is **not allowed**.

## 14. Provider provenance

Defect corrected in PQ-1: adapter provenance previously stopped at `PricingResolver` and was discarded before persistence.

Additive, legacy-safe fields now persist:

- `positions.entry_price_provenance`;
- `positions.exit_price_provenance`;
- `trades.price_provenance`;
- liquidity-source provenance remains in preserved `positions.source_meta`.

Each new resolver-backed fill records provider, exact field (`open`/`close`), session, source timestamp when supplied, TalonX receipt timestamp, adjustment state, and finality label. Under `composite-*` modes the provider is the **actual sub-adapter that supplied the row** (`CompositeBarAdapter` tags each row with `_source_adapter`), not the composite's name; without this a trade could not say whether the SIP snapshot or the live tail priced it. Legacy/injected rows remain NULL/unknown; nothing is fabricated. Restart persistence is tested. `EXIT_UNRESOLVED` now merges its marker into `source_meta` instead of overwriting admission/liquidity evidence.

## 15. Replay/runtime compatibility

**`PARTIALLY_COMPATIBLE`**.

- Task107A/95G SIP `adjustment=all` replay and bounded yfinance parity are methodologically comparable for tested historical OHLCV/liquidity observations.
- Task112R's runtime-matching G2b and Task116 replay use the correct second-distinct-owner activation semantics.
- Original headline research using last-filing activation remains incompatible.
- Prospective runtime finality, provider correction behavior, delisted coverage, and corporate-action position accounting are not reproduced by retrospective snapshots. Historical profitability cannot be claimed to transfer on this basis.

## 16. Credential and entitlement state

No secrets are recorded. `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` are configured. A bounded read-only probe made two market-data requests (AAPL, five completed sessions): SIP HTTP 200/five bars; IEX HTTP 200/five bars. No broker/order endpoint was called. See `credential_entitlement.json`.

## 17. Defects and corrections

Corrected:

1. execution provider provenance was not persisted;
2. `mark_exit_unresolved()` overwrote the position's existing source metadata, destroying earlier evidence;
3. (found in completion review) composite adapters stamped the composite's name as provider, hiding which sub-adapter supplied a price; corrected additively.

Not corrected because broader release semantics remain undecided:

1. no runtime Alpaca SIP adapter;
2. no provider-guaranteed finality boundary;
3. no split/dividend position-accounting layer;
4. default CSV remains stale;
5. no qualified fallback;
6. (found in completion review) `CompositeBarAdapter.history()` merges snapshot rows (adjustment basis as of snapshot time) with live-tail rows (basis as of now). If a split occurs between the two, the 20-session liquidity window mixes bases. Same root cause as gap 3;
7. **demonstrated, not just argued**: `test_KNOWN_GAP_split_during_hold_is_not_normalized_by_the_ledger` shows a 10:1 split during a hold yields a spurious ~-89% realized loss, because entry is stored on the pre-split basis while exit is served post-split with shares/cost unadjusted. It is a characterization test and must be replaced (not deleted) when a corporate-action layer exists.

Completion-review note: a minimal fail-closed split guard (compare the stored entry-session bar with the provider's current adjusted bar at settlement; on mismatch hold for review) is a candidate bounded follow-up. It changes settlement behaviour, so it is a gatekeeper design decision and was not implemented here.

## 18. Tests

See `test_results.txt`. Final focused result: **117 passed, 0 failed, 0 skipped** (5-file scope); the broader 13-file regression is 325 passed / 3 failed. The 3 failures reproduce identically on clean HEAD (OPS-017 stale V1 fingerprint literals x2; one RI-3 renderer test needing an absent executable) and are unrelated. The initial 36 errors were pytest temporary-directory permission failures, not assertion failures. Tests cover validation, normal open/close, NaN/zero/negative/None open never filling, timeout/rate-limit, early-close/Session-3, split price-volume compatibility, exit fall-forward to the first later close (+2 case), a bar beyond +5 never used and `EXIT_UNRESOLVED` with no SELL, composite fallback only for uncovered sessions, composite sub-adapter provenance, disagreement authority, resolver/default-CSV provenance, restart, unresolved-evidence preservation, legacy unknown handling, unchanged thresholds and fingerprint, and the split-during-hold gap characterization.

V2 strategy fingerprint: `e2acf6454789217e`, unchanged. No frozen strategy value or threshold changed.

## 19. Qualification matrix

The exact purpose-by-purpose statuses are in `qualification_matrix.csv`. In summary:

- `QUALIFIED_FOR_HISTORICAL_V2_REPLAY`: cached Alpaca SIP CSV;
- `QUALIFIED_FOR_LIQUIDITY_HISTORY`: Alpaca SIP historical endpoint/data class;
- `QUALIFIED_FOR_BOUNDED_PARITY_DOMAIN`: yfinance daily `auto_adjust=True`;
- `NOT_QUALIFIED_FOR_LIQUIDITY_HISTORY`: Alpaca IEX;
- `INSUFFICIENT_EVIDENCE_FOR_CAUSAL_OPEN_CLOSE`: Alpaca SIP and yfinance prospective use;
- `NOT_QUALIFIED_FOR_CURRENT_RUNTIME` corporate-action-safe lifecycle: all candidates;
- `NOT_QUALIFIED_FOR_FALLBACK`: every candidate pair.

## 20. Roadmap gate and remaining gaps

- OPS-005 PROVIDER FINALITY: **NOT_RESOLVED**
- FIRST-RELEASE AUTHORITATIVE PROVIDER CONTRACT: **NOT_DEFINED** (a precise proposed contract exists; it is not executable/qualified)
- FIRST-RELEASE REQUIRED DATA AVAILABLE: **YES** (current SIP historical entitlement confirmed; runtime/finality correctness is the blocker)
- PRODUCTION PROVIDER SWITCH PERFORMED: **NO**
- STRATEGY RULES CHANGED: **NO**
- PROFITABILITY RESEARCH PERFORMED: **NO**
- TALONX SIGNAL: **UNCHANGED**
- TALONX SENTINEL: **UNCHANGED**
- TALONX LAB: **OFF**
- V2 FINAL RELEASE ACCEPTANCE NOT STARTED
- RELEASE CANDIDATE NOT FROZEN
- PROSPECTIVE PAPER VALIDATION NOT STARTED
- NEXT STEP AWAITS GATEKEEPER REVIEW

Required next gate, without assuming authorization: approve and implement one corporate-action-safe raw/normalized price model; implement/qualify the chosen provider adapter; establish a correction/finality boundary with captured source/receipt/availability/finality timestamps; add a reverse-split fixture; then repeat only the bounded qualification checks needed to close these specific gaps.

## Source evidence

- Local: Task117 provider studies under `results/task117_phase0_*`; Package 3 evidence; Task112R parity; RI-1 evidence.
- Provider documentation reviewed: Alpaca Market Data FAQ (SIP vs IEX, aggregation and historical-delay behavior), Real-time Stock Data (daily/updated bars and late trades), and Historical Stock Data/API reference.
