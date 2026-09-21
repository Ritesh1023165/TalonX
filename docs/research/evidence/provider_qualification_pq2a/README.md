# PQ-2A — Corporate Action Safety & Accounting Contract

Date: 2026-09-21. Scope: correctness of V2 paper accounting across corporate actions **only**. Not performed: strategy research, provider activation, SIP runtime adapter, open/close finality, PQ-2B, final V2 release acceptance, release freeze, prospective paper validation, profitability work, production DB mutation, broker/Telegram activity.

## 0. Verdict

**`PQ2A_ACCEPTED_WITH_BOUNDED_FOLLOWUPS`**

All 18 acceptance conditions are met by deterministic tests. Four bounded follow-ups remain, each fail-safe today (section 23): the dividend performance model needs a gatekeeper product decision (`DIVIDEND_POLICY_DECISION_REQUIRED`), fractional reverse-split entitlement uses an exact-retention model that deviates from the agreed `S5-26` cash-in-lieu, unsupported action classes fail closed rather than being supported, and an ambiguous entry basis fails closed rather than being resolved by a basis-witness re-fetch.

## 1. Repository state

- Branch `feature/task131-option-a-integration`; starting HEAD `9b3f7ca6d7ad394b2ba20f7171534be0dc89b87e` = reported HEAD = `origin/feature/task131-option-a-integration`; working tree clean at start; no TalonX process running.
- Raw capture: `repository_state.txt`.

## 2. Current accounting flow (traced before any change)

| Stage | Code | Persisted / used |
|---|---|---|
| ENTRY | `pipeline.process_episode` → `paper.enter_position` → `sizing.size_whole_shares_fee_inclusive` | `positions.shares` (whole), `entry_price` (entry-session **open**, on whatever basis the provider served *at that moment*), `entry_fee`, `position_cost = shares×price+fee`, `entry_price_provenance` (PQ-1), `trades` BUY row, cash debit, all in one transaction |
| HOLD | `positions.status='OPEN'`, `target_exit_session = entry+10` | nothing recomputed; quantity and cost are write-once |
| EXIT | `pipeline.settle_due_exits` → `paper.close_position` → `sizing.compute_exit_economics` | re-reads `shares`, `position_cost` from the row inside the transaction; `exit_net = shares × exit_close − exit_fee`; `realized_pnl = exit_net − position_cost`; SELL trade, cash credit, cooldown |
| RECONCILIATION | `talonx_ops/prospective/close.py::_v2_reconcile`, `ledger_guard.check_ledger_continuity` | `cash + open_cost + unresolved_cost = starting + realized`; whole-share entries; ledger equation |
| DASHBOARD | `talonx_ops/dashboard_read.py`, `paper_performance.py`, `talonx_v2/service.py::_phase_mark` | shares, cost, realized P&L, marked value = `shares × mark` |

## 3. Root cause of the false split P&L

Entry price, shares and cost are persisted on the **price basis the provider served at entry time** (`adjustment=all` is relative to the *query* date). The exit close is fetched later, on the **post-split basis**. Shares were never re-expressed, so settlement computed `shares_pre_split × price_post_split − cost_pre_split`. Nothing in the ledger, the settlement formula or the reconciliation knew that two different bases were being compared.

Reproduced with the real settlement code (`scenario_results.json`, `tests/test_pq2a_corporate_actions.py::test_root_cause_*`):

| 10 sh @ $100 (cost $1,000), 10:1 split, exit close $11 | shares settled | proceeds | P&L |
|---|---|---|---|
| **Before (unguarded)** | 10 | $110 | **−$890 (−89%)** |
| **After (PQ-2A)** | 100 | $1,100 | **+$100 (+10%)** |
| Expected (economic) | 100 | $1,100 | +$100 |

The same defect was latent in three places, all fixed: settlement quantity, `_phase_mark`/`paper_performance` unrealised P&L (`shares × mark − cost`), and `CompositeBarAdapter.history()` (section 16).

## 4. Corporate-action source inventory

Full table: `source_inventory.csv`; raw probe payloads: `probe_alpaca_corporate_actions.json`, `probe_alpaca_all_types_and_yfinance.json` (bounded read-only market-data calls only; no broker/order endpoint; keys never recorded).

| Source | AVAILABLE | CAUSALLY AVAILABLE | RELEASE-QUALIFIED (PQ-2A) |
|---|---|---|---|
| Alpaca `GET /v1/corporate-actions` (existing credentials, free) | yes — forward/reverse/unit splits, cash dividends (rate, ex/record/payable date), mergers, spin-offs, name changes, stock dividends; uuid `id`; bulk-by-day works | yes for prospective use (fetched at run time, applied only when `ex_date ≤ as_of`, receipt time stamped); retrospective correction/late publication cannot be excluded for *replay* | **QUALIFIED as the single authoritative event source**, fail-closed on outage/malformed/conflict/unsupported |
| Alpaca bars `adjustment=raw|split|dividend|all` | yes (configurable) | yes | not an event source; defines the *basis* a row is on |
| yfinance `Ticker.splits/dividends` | yes (float ratios, no id, no unsupported classes) | yes | **QUALIFIED only as an optional independent witness** (not wired by default); disagreement ⇒ conflict ⇒ fail closed |
| Task107A/95G CSV snapshot | prices only | stale prospectively | not a source; basis UNKNOWN by design |

Verified events (probe): NVDA 10:1 2024-06-10, CMG 50:1 2024-06-26, AVGO 10:1 2024-07-15, SMCI 10:1 2024-10-01; reverse splits AMC 1:10 2023-08-24, GNS 1:10 2024-08-16, MULN 1:25 / 1:9 / 1:100 / 1:100; a non-integer reverse ratio exists (CRNCY 62:79). yfinance independently agreed on NVDA (10.0), CMG (50.0), AMC (0.1). The 2026-09-19 PQ-1 note "no reverse-split fixture found" is closed: real reverse-split payloads are recorded here and are the shape the tests use.

## 5. Adjustment semantics (`adjustment_semantics.csv`)

- Snapshot CSV, IEX adapter, yfinance adapter: **split + dividend adjusted, relative to the fetch date**; the same bar changes after a later split/dividend. Alpaca bars prove it: NVDA 2024-06-07 open — raw 1,197.70; split-adjusted 119.77 (volume ×10); dividend-adjusted 1,194.29; all 119.43.
- The legacy service CSV loader labels `UNKNOWN_LEGACY_CSV`.
- **New:** every adapter row and every persisted fill now carries `basis_as_of` (live adapters: the UTC fetch date at load; static snapshot: `None` = UNKNOWN, never guessed). Snapshot last-row date is 2026-08-31 for 2,403 of 4,234 files (a lower bound, not an as-of).

## 6. First-release corporate-action contract (machine-tested)

| Case | Behaviour |
|---|---|
| Forward split | `economic_shares = shares × R`, `R = new/old` exact; aggregate cost unchanged; trail row `APPLIED` |
| Reverse split | same rule with `R < 1`; whole result exact; fractional retained exactly (section 9) |
| Cash dividend | observed only: trail `DIVIDEND_OBSERVED_NOT_CREDITED`; no cash, no shares, no price adjustment |
| Unsupported / malformed / undated action | detected → **BLOCK** → `EXIT_UNRESOLVED` (capacity and account block retained), no P&L |
| Conflicting evidence (same ex-date different ratios, sources disagree, a source cannot answer, an applied split vanishes) | **BLOCK** → `EXIT_UNRESOLVED` |
| Evidence unavailable | **HOLD** inside the existing +5-session window, then `EXIT_UNRESOLVED` |
| Discovered after entry, before exit | applied by the per-tick sweep and re-verified at settlement |
| On the target exit session | `ex_date == exit session` ⇒ exit bar is post-split by construction ⇒ applied |
| During the exit-recovery window | applied if `entry_basis < ex_date`; exit at the first available close through +5 unchanged |

**Basis proof (per fill).** Entry basis `B_e`: `ex < B_e` ⇒ already reflected (recorded `REFLECTED_IN_ENTRY_BASIS`, no share change); `ex == B_e` ⇒ ambiguous ⇒ BLOCK; `ex > B_e` ⇒ apply; `B_e` unknown ⇒ BLOCK. Exit side: a split after the exit fill session requires an exit basis strictly later than its ex-date (else HOLD / BLOCK if unknown).

**Detection.** Explicit provider event only. Price movement is never used; there is no threshold anywhere.

## 7. Forward split

`tests/…::test_02` (2:1), `::test_03` and the PQ-1 known-gap fixture (10:1), `::test_06` (applied during the hold by the sweep, entry row untouched), `::test_07` (on the exit session), `::test_08` (inside the recovery window). 10:1 fixture: 400 sh @ 25.00 → 4,000 sh; exit 2.70 → $10,800; P&L **+$800 (+8%)**, cash 300,800.

## 8. Reverse split

`::test_04`: 400 sh, 1:10 → 40 sh; exit 270 → $10,800, **+$800** (not a manufactured gain). Scenario file: 100 sh @ $10, 1:10, exit $105 → 10 sh, +$50.

## 9. Fractional reverse-split entitlement

5 sh × 1:10 = **0.5 sh**, retained **exactly** (`Fraction("1/2")` in the trail; settled through `Decimal`, never a binary float). Exit @ $1,050: proceeds $525 vs cost $500 → **+$25**. `::test_05`: 333 sh × 1:10 = 333/10 sh, exit $330 → +$999 exactly.

Why not truncate + cash-in-lieu (agreed `S5-26`)? It needs a cash-in-lieu **settlement reference price**; no free source provides one (the Alpaca record carries only ratio and dates). Crediting cash would fabricate it; rounding to 0 or 1 would invent economics. Exact retention conserves aggregate economics, needs no invented number, and is isolated to the trail (replaceable). Entry sizing stays whole-share (`::test_30`); `positions.shares` (entry quantity) stays whole so the `whole_share_positions` reconciliation still passes. **Recorded as a gatekeeper decision**, not silently settled.

## 10. Dividend policy

`DIVIDEND PERFORMANCE MODEL: DECISION_REQUIRED` — ledger mechanics are **price-return-only (interim, fail-safe)**.

- An authoritative decision already exists (`S10-17`, Session 10 §G): dividends recorded separately but **included in total economic return**, entitlement verified, receivables ≠ cash, and never double counted through cash *and* an adjusted price. It is not implemented (no receivable lifecycle).
- Interim mechanics: dividend events are OBSERVED (audit trail), never credited, never used to adjust ledger prices. The prices in the ledger are what the provider served at fill time, so the only dividend effect that can reach a P&L is the small `adjustment=all` rebase for a dividend with ex-date between a bar's session and its fetch — there is **no cash path**, so a dividend cannot be counted twice. `::test_25_26`: cash and shares unchanged after a $0.50 dividend; P&L = price return; no dividend trade row.
- Consequence for the gatekeeper: live paper P&L excludes dividends, while research replays on the `adjustment=all` snapshot approximate total return. The gatekeeper must decide whether first release may ship price-return-only (performance labelled) or must implement the agreed total-return lifecycle first.

## 11. Ledger representation

Purely additive (`CREATE IF NOT EXISTS`); no existing table or row altered, no production migration.

- `corporate_actions` — registry: content `action_key`, kind, ex-date, ratio, `sources_json` (every source ref: source, provider id, receipt time), raw payload.
- `position_corporate_actions` — append-only trail, `UNIQUE(position_id, action_key)`: status (`APPLIED` / `REFLECTED_IN_ENTRY_BASIS` / `DIVIDEND_OBSERVED_NOT_CREDITED` / derived `BLOCKED_*`), exact `shares_before`/`shares_after` fractions, aggregate `cost_basis` (unchanged), entry/exit basis dates.
- `positions.shares` = **original entry quantity, never rewritten**; economic quantity = entry shares × ∏ `APPLIED` ratios, derived from the trail (`V2Store.effective_shares_exact`). No denormalised counter that could be applied twice.
- Settlement re-reads the economic quantity inside the settlement transaction (Package 2 principle) and records the actual post-action quantity on the SELL trade.

## 12. Idempotency

`::test_09` duplicate event (different provider id, same content) + three sweeps ⇒ 4,000 sh (not 40,000), one trail row, one registry row. `::test_10` new `V2Store` on the same file (restart) ×2 ⇒ unchanged. The key is content-derived (`SPLIT|SYM|ex_date|num/den`) and enforced by a DB `UNIQUE` constraint, so it holds under concurrency and replay. `::test_31` duplicate settlement remains a no-op.

## 13. Settlement

Uses persisted economics only: economic quantity from the trail, unchanged persisted `position_cost`; never reconstructed from a current price. Expected vs actual for every case is in `scenario_results.json` and the tests. A stale-snapshot duplicate close and a settlement while a corporate-action block row exists are both refused inside the transaction (`::test_16`, `::test_31`).

## 14. EXIT_UNRESOLVED / fail-closed

The existing `EXIT_UNRESOLVED` state is sufficient — **no new lifecycle state and no new account-block reason type** (`account_blocks` keeps its four reasons). `::test_14`, `::test_14b`, `::test_15`, `::test_16`, unsupported-class parametrized test: position stays occupying capacity and symbol ownership, cash untouched, `exit_price`/`realized_pnl_*` `NULL`, no SELL trade, an active `EXIT_UNRESOLVED` account block, and the reason is in `source_meta.exit_unresolved_detail` (`CORPORATE_ACTION CA_…`) plus a `BLOCKED_*` trail row. Transient causes (evidence outage, exit basis not yet including the split) HOLD inside the unchanged Session-10/+5 window (`::test_32`); deterministic causes go straight to unresolved.

## 15. Reconciliation

`close._v2_reconcile` gains `corporate_action_adjustments_consistent` (routed through the existing `LEDGER_MISMATCH` block mechanism); `ledger_guard.check_ledger_continuity` reports the same problems; the RI-3 operator state maps a FAIL to `LEDGER_MISMATCH` without invalidating older evidence files that lack the key. A correctly adjusted split raises no cash-creation/deficit/missing-position/duplicate finding (`::test_17`, incl. mid-hold). It detects a corrupted chain, a share count that is not entry × ratio, an `APPLIED` row with `ex_date ≤ entry_session`, and a SELL whose quantity ≠ the economic quantity (`::test_18`). Cost-basis, cash and ledger-equation checks are unchanged because a pure split changes none of them.

## 16. Composite adapter safety

**Proved** (`::test_23`): a 20-session window can hold ~$250 snapshot rows next to ~$25 live rows after a 10:1 split (`{250.0, 25.0}` in one series) — the old `history()` merged them silently.

**Fixed:** `CompositeBarAdapter.history()` splices only when bases are provably compatible: equal `basis_as_of` dates; or unequal/unknown bases **and** corporate-action evidence shows no split/unsupported action in `(hist basis, live basis]` (snapshot lower bound = its last row date; dividends ignored inside the frozen `adjustment=all` contract). Otherwise — split found, evidence unavailable, conflicting, or no evidence source configured — it raises `IncompatibleAdjustmentBasis`; the resolver records `REJECTED_INCOMPATIBLE_ADJUSTMENT_BASIS` and returns an empty history (liquidity gate: non-terminal skip, retried next tick). `session()` never mixes and is untouched. `::test_24`: compatible bases and proven-no-split still merge; a composite in which only one source contributes is unchanged. One PQ-1 test that relied on the old unconditional splice was updated to supply a compatible basis (documented in the test).

## 17. Provenance

`::test_20_21_22`: every corroborating source, provider id and receipt time is retained in the registry; the original entry provenance JSON is byte-identical after a split; exit provenance and trade provenance are retained; composite rows keep naming the actual supplying sub-adapter (PQ-1 test still passes); `basis_as_of` is added to provenance for new fills.

## 18. Operator visibility

Read-only, no ledger mutation (`::test_19`: the projection connection is `mode=ro` and a write attempt raises). `dashboard_read.py` ledger block gains `corporate_actions: {status: NONE|OBSERVED|ADJUSTED|BLOCKED, items:[{symbol, action_type, ex_date, ratio, adjustment_status, shares_before/after, detail}]}`; `paper_performance` shows the economic quantity and marks on it; `V2Service` marks show `economic_shares` and cost-basis-relative unrealised P&L (`+$800`, not `−$8,900`); the service status JSON carries `corporate_action_guard` (state, sources, last sweep). Unresolved positions are additionally visible through the existing `EXIT_UNRESOLVED` count and account block. No RI-3 redesign.

## 19. Legacy behaviour

`::test_27`: a legacy row (no provenance) with **no** evidence of any action settles exactly as before and stays `NULL` (nothing back-filled); a legacy row with a split in its window cannot be adjusted (basis unknown) ⇒ BLOCK. No historical production row was read, migrated or rewritten.

## 20. Test evidence

See `test_results.txt`. New file `tests/test_pq2a_corporate_actions.py` (matrix items 1–32 + root cause, reflected/ambiguous basis, vanished-event, source parsing against real payload shapes, cache, service, live-entry refusal); PQ-1 known-gap converted (not deleted).

## 21. Strategy fingerprint

`V2 STRATEGY FINGERPRINT: e2acf6454789217e` (recomputed by `research/scripts/task112_v2_release_fingerprint.py` inside `::test_28_29`). `talonx_v2/config.py` and every frozen threshold are untouched: `(min_distinct_owners, hold_trading_days, entry_offset_sessions, liquidity_lookback_sessions, liquidity_min_median_dollar_volume, liquidity_min_close, exit_fallforward_max_sessions, max_entry_staleness_sessions) = (2, 10, 1, 20, 5,000,000, 5.0, 5, 3)`. **STRATEGY RULES CHANGED: NO.**

## 22. Defects corrected

1. Split/reverse split during a hold booked as trading P&L (root cause, section 3).
2. Unrealised P&L / marked value used entry shares (false loss on dashboards and status).
3. `CompositeBarAdapter.history()` silently mixed adjustment bases.
4. Fills carried no adjustment-basis date, so basis could not be proven or checked.
5. (found while implementing) an "already reflected" rule of `ex ≤ basis` would have mis-classified a split effective on the fetch date; tightened to strict `<`, equality fails closed.

## 23. Remaining gaps (all fail-safe today)

1. **`DIVIDEND_POLICY_DECISION_REQUIRED`** — agreed total-return receivable lifecycle not implemented; ledger is price-return-only (section 10).
2. **Fractional entitlement model** — exact retention, deviating from agreed `S5-26` cash-in-lieu; gatekeeper to confirm or specify a settlement reference.
3. **Ambiguous basis** (`ex == entry basis date`) blocks rather than being resolved by re-fetching the entry-session bar as a witness — bounded follow-up.
4. Mergers / spin-offs / renames / unit splits / stock dividends: detected and blocked, not supported (`S5-25`).
5. Alpaca corporate-action completeness/latency has no published SLA; the live companion now **requires Alpaca market-data credentials** (`.env` already provides them; startup refuses without).
6. `basis_as_of` is TalonX's fetch-date claim, not a provider-certified adjustment timestamp.
7. Original's own accounting and the `S5-27` Decimal migration are out of scope.
8. Pre-existing, unrelated: the existing test suites write PENDING rows into the repo-root `notifications.db` (ignored by git; observed again this session); the full-tree pytest run stalls in `tests/test_backtest_cost_sensitivity.py` on this machine on both the starting HEAD and this tree.

## 24. Verdict and roadmap gate

`PQ2A_ACCEPTED_WITH_BOUNDED_FOLLOWUPS`. `OPS-005` provider finality, SIP runtime adapter, open/close finality, PQ-2B, final release acceptance, release freeze and prospective validation are **not started**. Next step awaits gatekeeper review.

## Files in this bundle

`README.md`, `repository_state.txt`, `source_inventory.csv`, `adjustment_semantics.csv`, `probe_alpaca_corporate_actions.json`, `probe_alpaca_all_types_and_yfinance.json`, `pq2a_scenarios.py` + `scenario_results.json`, `test_results.txt`.
