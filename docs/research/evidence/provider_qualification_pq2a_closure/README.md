# PQ-2A CLOSURE — Fractional entitlement decision + dividend total-return accounting

Date: 2026-09-21. Scope: close the two product-contract decisions surfaced by PQ-2A. Not performed: PQ-2B, SIP runtime adapter, open/close finality, OPS-005, final release acceptance, release freeze, prospective validation, profitability work, production DB mutation, broker/Telegram activity.

## 0. Verdict

**`PQ2A_CLOSURE_ACCEPTED_WITH_BOUNDED_FOLLOWUPS`** — all 18 acceptance conditions are met by deterministic tests; the bounded follow-ups (section 20) are fail-safe.

## 1. Repository state
Branch `feature/task131-option-a-integration`; starting HEAD `b8b98e0` = origin; status clean apart from git-ignored-db side files (`notifications.db-shm/-wal`, not staged). See `repository_state.txt`.

## 2. Cleanup / worktree state
No PQ-2A pytest processes remained (checked; nothing killed). The PQ-2A scratch worktree was already unregistered; its leftover scratch directory (in the session scratchpad, outside the repository) was deleted. `git worktree list` shows only the five unrelated pre-existing worktrees (research/hotfix branches), left untouched. Production ledger `v2_lane.db` md5 `cff00b0f46e7e5b65e6f5903366fab28`, mtime 2026-09-15 — identical before and after.

## 3. Gatekeeper decisions (authoritative)
1. Exact fractional economic entitlement after a corporate action is allowed (V2 paper); no truncation, no cash-in-lieu; whole-share ENTRY sizing unchanged.
2. Total return retained: eligible ordinary cash dividends are part of V2 performance. Recorded in `DECISION_LOG.md` (PQ-2A CLOSURE section) and `REQUIREMENTS_TRACKER.md` (S5-26 revised, S10-17 contract, new S13-21).

## 4. Price basis confirmation (Task A) — the gating fact
Not guessed; measured (`probe_dividend_semantics.json`, `probe_yfinance_price_basis.json`, code inspection).

| Path | Basis before this task | Evidence |
|---|---|---|
| `CsvBarAdapter` (Task107A/95G snapshot) | **DIVIDEND-ADJUSTED** (`adjustment=all`, relative to snapshot time) | code tag `SPLIT_DIVIDEND_ADJUSTED`; PQ-2A NVDA/AAPL bars |
| `AlpacaIexBarAdapter` | **DIVIDEND-ADJUSTED** (`adjustment=all`, relative to the fetch date) | code |
| `YFinanceBarAdapter` | **DIVIDEND-ADJUSTED** (`auto_adjust=True`) | code |
| service legacy CSV loader | **UNKNOWN** (`UNKNOWN_LEGACY_CSV`) | code |

`adjustment=all` is relative to the **query** date: AAPL sessions 2026-05-06.. queried in Sept 2026 — raw/split open **281.915**, dividend/all open **281.41** (later dividends folded in). A fill fetched after an ex-date therefore embeds that dividend in its price; crediting the dividend as cash on top would count it twice. The basis is **known, not ambiguous**, so the closure is not blocked — but the contract must change:

**New V2 price-basis contract for LIVE fills: SPLIT_ADJUSTED, dividend-UNADJUSTED.**
- `AlpacaIexBarAdapter`: `adjustment=split`; `YFinanceBarAdapter`: `auto_adjust=False`. Verified equal to Alpaca's split-only series (NVDA 2024-06-07 open: yfinance `auto_adjust=False` 119.77 = Alpaca `split` 119.77; `auto_adjust=True` 119.43 = Alpaca `all`; AAPL 2026-05-06 `auto_adjust=False` 281.92 = raw).
- Provenance already records `adjustment_state`; a fill on any state other than `RAW`/`SPLIT_ADJUSTED` (dividend-adjusted, unknown, legacy, NULL) with an **eligible dividend in the hold window ⇒ BLOCK** (`CA_DIVIDEND_PRICE_BASIS_NOT_UNADJUSTED`, existing `EXIT_UNRESOLVED`). With no dividend in the window such a fill is unaffected.
- Consequence recorded: the frozen replay snapshot stays all-adjusted (approximate total return via price); live paper = split-only price + explicit dividend cash. A composite splice of the all-adjusted CSV and a split-only live tail differs by the cumulative dividend factor (fractions of a percent) — relevant only at the `$5`/`$5M` liquidity boundary (bounded residual).

## 5. Fractional-entitlement contract
`POST-CORPORATE-ACTION FRACTIONAL ENTITLEMENT: EXACT RETENTION`; `NEW ENTRY SIZING: WHOLE SHARE ONLY`; `CASH-IN-LIEU: NOT FABRICATED`. Behaviour was already implemented in PQ-2A; this task documents it as the rule, revises S5-26, and adds tests 1–5: whole-share sizing unchanged (25.00→400, 30.00→333, 7,000→1, 20,000→refused), 5 sh × 1:10 = exactly `Fraction(1,2)`, ≠ 0, ≠ 1, cash unchanged, no trade/dividend rows, entry row still `5.0`.

## 6. Dividend source semantics (Task B, Task F)
Alpaca `/v1/corporate-actions` (type `cash_dividend`), 368 dividends sampled across 30 symbols 2024-01→2026-09:

| Field | Present | Notes |
|---|---|---|
| `symbol`, `rate`, `ex_date`, `record_date`, `payable_date`, `process_date`, `id`, `cusip`, `special`, `foreign` | `record_date`/`payable_date` missing in 0 of 368; all fields present in every record of the AAPL/MSFT/KO sample | `rate` = **per share, raw, as of the ex-date** |
| declaration date | **absent** | not available |
| `special` | present on every record | true for e.g. BABA specials → unsupported |
| `foreign` | present | 77/368 true (ADR/foreign, withholding/FX) → unsupported |
| source timestamp | absent | TalonX stamps `received_at_utc` |

- **Amount basis**: rate is per share **as of that ex-date, not split-normalised** (NVDA 0.04 on 2024-03-05 before the 10:1; 0.01 after; AVGO 5.25 before its 10:1, 0.53 after). yfinance dividends ARE normalised (NVDA 0.004), so they are **not read** by the yfinance witness and cannot be compared with Alpaca's amount.
- `payable_date − ex_date` ranges 0…43 days; `ex_date ≠ record_date` in 61/368 (earlier T+2 era) — ownership therefore uses the **ex-date** only, valid in both eras.

## 7. Entitlement rule (machine-tested)
`ELIGIBLE ⇔ entry_session < ex_date ≤ exit_fill_session` (T+1-era convention: ownership must exist at the close before the ex-date).

| Case | Result | Test |
|---|---|---|
| entry before ex-date, held through | eligible | `test_06_07` |
| entry **on** ex-date | not eligible (bought ex-dividend) | `test_08` |
| entry after ex-date | not eligible | `test_08` |
| exit before ex-date | not eligible | `test_09` |
| exit **on** ex-date | **eligible** (owned through the prior close) | `test_exit_ON_the_ex_date…` |
| exit after ex-date, before payment | eligible; receivable retained | `test_10_11` |
| multiple dividends | independent | `test_12` |
| duplicate provider event | one entitlement | `test_13_14` |
| missing/ambiguous/malformed | no cash; fail closed | `test_15_16`, `test_receivable_is_never_credited…` |
| special / foreign / stock dividend | unsupported → `EXIT_UNRESOLVED`, operator-visible | `test_17` |
| unsupported dividend effective **after** the exit | irrelevant (not held through it) | `test_unsupported_dividend_effective_AFTER…` |

## 8. Receivable / credit lifecycle (Tasks C, D, I)
Minimal, additive table `dividend_entitlements` (no existing row/table altered; entry rows never rewritten; no `trades` row added):

```
provider event ──eligible?──▶ ACCRUED (atomic with settlement; amount fixed; NO cash)
                                 │  on/after payable_date AND fresh provider re-confirmation
                                 ▼
                              CREDITED  (portfolio.cash += amount in the SAME transaction;
                                         conditional UPDATE ... WHERE state='ACCRUED' = once-only gate)
```
- Entitlement date ≠ payment date: the Session-10 exit before payment loses nothing — the receivable persists after the position is CLOSED and is credited later; the closed trade row is never reopened or mutated (`test_10_11` compares the row before/after).
- No cash is fabricated: never credited without a `payable_date`; never if the provider is unavailable, no longer reports the event, changed the amount/payable date, or reclassified it special (`test_receivable_is_never_credited_without_fresh_provider_confirmation`).
- Ownership of the receivable: `campaign_id`, `account_id`, `position_id`, `episode_id`, `symbol`, `action_key` (lineage), plus source refs and receipt time (`provenance_json`).
- Runtime: `V2Service._phase_dividends` (after the close phase) credits due receivables each tick; failure never aborts the tick.

## 9. Split / dividend interaction (Task F)
Quantity = **exact economic shares at the ex-date** from the PQ-2A trail: entry shares × ∏ `APPLIED` splits with ex < dividend ex ÷ ∏ `REFLECTED` splits with ex > dividend ex (entry shares are on the entry basis). Tests: 10 sh → 10:1 → 100 sh, $0.20 ⇒ **$20** (`test_18`); dividend *before* the split uses the pre-split count at the raw rate (10 × $2.00 = $20); a split already reflected in the entry basis is undone for an earlier dividend (1,000 → 100); reverse split 5 → ½ sh, $1.00 ⇒ **$0.50**; 333 sh → 333/10, $0.15 ⇒ exact `4.995` → $5.00 (ROUND_HALF_UP once, exact retained); split and dividend on the **same ex-date** ⇒ ambiguous ⇒ BLOCK.

## 10. Cash / accounting model (Tasks G, H)
**`DIVIDEND PERFORMANCE MODEL: TOTAL_RETURN`.**
- `positions.realized_pnl_usd` = **PRICE P&L** (fee-inclusive: exit proceeds − entry economic cost); unchanged semantics (Packages 1/4).
- Dividend P&L = Σ `CREDITED` entitlements; **total return = price P&L + dividend P&L** (fees are already inside price P&L).
- **Both** performance and paper cash are affected, consistently: credit raises `portfolio.cash` and dividend P&L in one transaction. Cash equation everywhere (`close._v2_reconcile`, `ledger_guard`, `paper_performance`): `cash + open cost + unresolved cost = starting + price P&L + credited dividends`. Accrued (unpaid) receivables are an asset in equity, **not** cash.
- Reconstruction visible per closed trade: `price_pnl_usd`, `dividend_pnl_usd`, `dividend_receivable_usd`, `total_return_pnl_usd`.

Numerical examples (`closure_scenario_results.json`, reproducible with `pq2a_closure_scenarios.py`):

| Scenario | Economic shares | Price P&L | Dividend P&L | Total | Cash − start |
|---|---|---|---|---|---|
| **A** 100 sh @ $100, exit $105, $0.50 dividend (payable after exit) | 100 | $500.00 | **$50.00** | **$550.00** | $550.00 |
| **B** 10 sh @ $100, 10:1, exit $11, $0.20 dividend | 100 | $100.00 | $20.00 | $120.00 | $120.00 |
| **C** 5 sh @ $100, 1:10, exit $1,050, $1.00 dividend | 0.5 | $25.00 | $0.50 | $25.50 | $25.50 |
| **D** with fees: entry $1 + exit $1, $0.50 dividend | 100 | $498.00 (net of $2) | $50.00 | $548.00 | $548.00 |
| E entered on ex-date | 100 | $500.00 | $0 | $500.00 | $500.00 |
| F exit before ex-date | 100 | $500.00 | $0 | $500.00 | $500.00 |

## 11. Settlement interaction
Settlement records eligible entitlements atomically inside `paper.close_position`'s transaction (`record_dividend_entitlement`, which re-checks `entry < ex ≤ exit` in the transaction). A stale duplicate close is a no-op and creates no second receivable (`test_33`). Unsupported/conflicting/unknown-basis evidence, or a dividend-adjusted fill basis with an eligible dividend, ⇒ `EXIT_UNRESOLVED` with **no** cash, P&L or receivable. Evidence unavailable ⇒ HOLD inside the unchanged +5 window (settlement never proceeds without dividend knowledge). Session-10/+5 unchanged (`test_30`: exit at +2 with a dividend at +1 ⇒ eligible; bar at +6 ⇒ unresolved).

## 12. Idempotency (Task K)
Content key `DIV|SYM|ex_date|normalised-rate` + `UNIQUE(position_id, action_key)` + once-only conditional UPDATE. Proven for: duplicate provider event under a new id and `0.500` vs `0.5` (one row); three repeated polls; restart (new `V2Store`); a stale caller re-crediting the same entitlement (`False`); a second settlement attempt (no second row). Same `(symbol, ex_date)` with a different amount ⇒ CONFLICT (never credit both).

## 13. Campaign / account isolation (Task J)
Each campaign is its own ledger file; rows carry `campaign_id`/`account_id`. `test_20`: same symbol, two campaigns, different windows — only the campaign holding through the ex-date gets the entitlement and the cash; the other gets neither. Lineage explicitly asserted (`CAMP-X`).

## 14. Reconciliation (Task L)
Existing mechanisms extended (no new framework): `dividend_accounting_consistent` (routes to `LEDGER_MISMATCH` block), cash equation includes credited dividends, `ledger_guard` reports the same problems. **Accepts** correct ACCRUED and CREDITED states. **Detects**: missing credit (cash short by $200 ⇒ cash equation FAIL), duplicate credit (second row ⇒ duplicate + cash FAIL), impossible lineage (missing position, wrong episode, ex-date ≤ entry or after exit), wrong quantity/amount, credit before payable date, overdue receivable (> 10 days past payable).

## 15. Operator visibility (Task M)
Read-only. `dashboard_read` ledger block: `dividends: {status NONE|RECEIVABLE|CREDITED, credited_usd, accrued_receivable_usd, items[symbol, ex_date, payable_date, rate_per_share, eligible_quantity, total_usd, state, provenance…]}` plus `dividend_pnl_usd` / `total_return_pnl_usd`; `paper_performance` adds `dividend_pnl`, `total_return_pnl`, per-trade fields and includes credited dividends in the reconciliation basis; service status carries dividend accrued/credited/last run. Unsupported distributions show as `BLOCKED_*` corporate-action rows and `EXIT_UNRESOLVED`. `test_25`: the projection connection is `mode=ro`, a write raises, and table contents/cash are unchanged after reading.

## 16. Unsupported distributions (Task N)
Fail closed and operator-visible; never treated as ordinary cash: `special:true`, `foreign:true`, stock dividends, malformed/zero/negative/NaN/inf/missing amounts, missing ex-date. Mergers/spin-offs/renames/unit splits retain the PQ-2A fail-closed behaviour.

## 17. Product requirement updates (Task O)
`REQUIREMENTS_TRACKER.md`: S5-26 **revised** (exact fractional entitlement; no cash-in-lieu; whole-share new entries) and update paragraph; S10-17 **retained** with the implementation contract; S13-21 added. `DECISION_LOG.md`: closure decisions appended (history not rewritten). `OPERATIONAL_FINDINGS.md` OPS-004 updated.

## 18. Tests
See `test_results.txt`. New `tests/test_pq2a_closure_dividends.py` (45 tests, matrix items 1–34 + extras). One PQ-2A test that asserted the interim price-return-only mechanics was superseded (documented in place). Mutation check: eight deliberate regressions were all caught (entry-on-ex-date eligible; exit-on-ex-date ineligible; basis guard removed; split trail ignored; entry shares used instead of ex-date shares; credit ignoring payable date; once-only gate removed; credited dividends omitted from the reconciliation equation). One further mutation (dropping the provider re-confirmation branch) is behaviourally equivalent, because the code then raises and still credits nothing. Single-guard mutations of the eligibility rule are masked by redundant guards (window filter, store re-check) by design; the combined mutation is caught.

## 19. Strategy fingerprint
`V2 STRATEGY FINGERPRINT: e2acf6454789217e` (asserted in `test_34` via `research/scripts/task112_v2_release_fingerprint.py`); thresholds `(2,10,1,20,5,000,000,5.0,5,3)` asserted unchanged. `talonx_v2/config.py` untouched. **STRATEGY RULES CHANGED: NO.** The price-basis change affects only the data adapters' adjustment parameter, not any frozen rule value.

## 20. Remaining gaps (fail-safe)
1. Special / foreign / stock / return-of-capital distributions are unsupported (fail closed), not modelled; withholding tax and FX not modelled.
2. Receivables are credited only when the provider re-confirms; no expiry/write-off policy for a receivable the provider never confirms (stays ACCRUED, flagged overdue after 10 days).
3. A dividend published by the provider only *after* the position has settled cannot be added retroactively (settlement holds if the source is down, but late provider additions are not re-scanned for closed trades).
4. Split-adjusted live basis vs all-adjusted snapshot: bounded liquidity-boundary residual (section 4).
5. Entry price fetched exactly on a split's ex-date still fails closed (PQ-2A follow-up, unchanged); mergers/spin-offs/renames/unit splits remain fail-closed; provider corporate-action SLA remains unpublished.
6. Original's own accounting and `S5-27` Decimal migration out of scope.
7. `positions.realized_pnl_usd` stays price P&L by design; consumers that need total return must add `dividend_entitlements` (the dashboards/paper_performance/reconciliation now do).

## 21. Verdict
`PQ2A_CLOSURE_ACCEPTED_WITH_BOUNDED_FOLLOWUPS`. OPS-005, SIP runtime adapter, open/close finality, PQ-2B, final release acceptance, release freeze, prospective validation: **not started**. Next step awaits gatekeeper review.
