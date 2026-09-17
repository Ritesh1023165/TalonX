# Package 4 — Whole-Share, Fee-Inclusive Sizing & Precise Accounting

**Type**: implementation task, following Package 3's acceptance. Branch
`feature/task131-option-a-integration`. Starting HEAD `f439630`
(verified: current branch, current HEAD, clean tree — no drift to
reconcile).

## 1. P4-A — Capital flow map (before Package 4)

```
V2Config.starting_cash_usd (default $100,000, env TALONX_V2_STARTING_CASH_USD)
  -> V2Store.__init__(starting_cash=...) -- seeds portfolio.cash ONLY if the row
     does not already exist (a brand-new db file = a new campaign; an existing
     file's cash is NEVER reset, confirmed by direct code reading)
  -> V2Store.cash() -- the single authoritative CASH read (portfolio.cash, REAL)
  -> service._capacity_rejection_reason() -- AVAILABLE cash, computed on demand
     as cash() - (per_position_allocation_usd * count(PENDING intents)) --
     reservations were ALREADY a subset of cash, never a separate debit
     (Session 10 §B's own agreed model -- confirmed already correct pre-Package 4)
  -> service.upsert_entry_intent() -- creates the durable PENDING reservation row;
     does NOT touch portfolio.cash at all (confirmed: no UPDATE portfolio anywhere
     in this call)
  -> paper.enter_position() -- FILL. Pre-Package-4: `talonx_paper.engine.
     calculate_buy(cash, allocation_usd, price)` -> `spend/price, spend`
     (CONTINUOUS float division, no fee parameter at all -- OPS-014's own finding)
  -> V2Store.insert_open_position(entry_price, shares, position_cost) -- write-once
  -> V2Store.set_cash(cash - cost) -- the ONE cash debit, exactly once
  -> paper.close_position() -- EXIT. Pre-Package-4:
     `talonx_paper.engine.calculate_sell_pnl(shares, entry_price, exit_price)`
     internally re-derives `cost_basis = shares * entry_price` -- NEVER reads the
     persisted `position_cost` for the P&L formula itself (only used it for the
     trade record's own position_cost field) -- dormant/invisible under today's
     zero-fee assumption (entry_total == notional there), but WRONG in general
     the moment a non-zero fee is ever configured (P4-E's own defect, below)
  -> V2Store.close_position() -- the authoritative OPEN->CLOSED transition
     (Package 1's own conditional UPDATE)
  -> V2Store.set_cash(cash + proceeds) -- proceeds = shares*exit_price, NO fee
     ever subtracted (none existed)
  -> V2Store.append_trade() -- audit trail
```

**Every monetary value, before Package 4**:

| value | authoritative source | representation | rounded? | caller-supplied? | persisted? | fees included? |
|---|---|---|---|---|---|---|
| `shares` | `calculate_buy`'s `spend/price` | float, CONTINUOUS (fractional) | no | no (derived) | yes (`positions.shares` REAL) | n/a |
| `entry notional` | == `position_cost` (no fee) | float | no | no | yes (`position_cost`) | N/A -- no fee existed |
| `entry fee` | **did not exist** | — | — | — | **not persisted** | — |
| `reserved amount` | `per_position_allocation_usd` (a FIXED cap, not the actual computed fill cost) | float | no | no (config) | not persisted (derived on demand from `COUNT(pending)`) | n/a |
| `position_cost` | `calculate_buy`'s `spend` | float | no | no | yes | no (zero-fee) |
| `exit proceeds` | `shares * exit_price` | float | no | no | not persisted separately (only in `realized_pnl_usd`) | no |
| `exit fee` | **did not exist** | — | — | — | **not persisted** | — |
| `realized_pnl_usd` | `calculate_sell_pnl`'s `proceeds - (shares*entry_price)` | float | no | no | yes | **entry fee NOT included — the defect** |
| `cash after entry` | `cash - cost` | float | no | no | yes (`portfolio.cash`) | n/a |
| `cash after exit` | `cash + proceeds` | float | no | no | yes | n/a |

## 2. Defects found (before any change)

1. **P4-B**: `calculate_buy` produced continuous, fractional share
   counts with **no fee parameter whatsoever** — the frozen "no
   fractional shares for the first-release V2 paper strategy"
   requirement was not met at all (this is exactly `OPS-014`'s own,
   already-documented finding, now closed).
2. **P4-E**: `calculate_sell_pnl` computed cost basis as
   `shares * entry_price`, never reading the persisted, authoritative
   `position_cost` (entry_total) — dormant and invisible under
   today's zero-fee assumption (the two values are identical when fee
   = 0), but wrong in general: the instant any non-zero entry fee is
   ever configured, this would silently **omit the entry fee from
   P&L**, overstating realized gains. Found by direct code trace
   during P4-A, before any change was made — a genuine, if currently
   dormant, defect.

## 3. P4-B — Whole-share, fee-inclusive sizing (correction)

**New module, `talonx_v2/sizing.py`** (V2-ONLY — `talonx_paper.engine`
is deliberately left completely unmodified; Original's own
fractional-share accounting is a separate, out-of-scope concern; the
frozen "no fractional shares" requirement is explicitly scoped to "the
first-release V2 paper strategy," not Original).

**Formula** (Session 10 §C, directly implemented): the largest
non-negative whole quantity `Q` such that
`Q * price + fee_fn(Q, price) <= allocation_usd`, found via a bounded
backward search from `floor(allocation/price)` down to 0 (correct for
ANY fee shape — flat, per-share, percentage, minimum — never assumes
monotonicity for correctness, only uses it implicitly as the search
terminates at the first, i.e. largest, satisfying `Q`). Quantity is
**never** rounded up. `Q=0` (or a price/allocation that admits no
share at all) returns an explicit reason
(`ALLOCATION_BELOW_ONE_SHARE`, `ONE_SHARE_PLUS_FEE_EXCEEDS_ALLOCATION`,
`BAD_PRICE`, `NO_ALLOCATION`).

**Available-cash enforcement (the resolved ambiguity)**: Session 10
§C explicitly states "insufficient cash to reserve the approved
allocation causes a **skip**, not a smaller reservation." This is
**not treated as ambiguous** — `size_whole_shares_fee_inclusive`
computes `Q` against the allocation cap only, then separately checks
whether that `Q`'s own fee-inclusive total fits AVAILABLE cash; if
not, the trade is refused ENTIRELY (`INSUFFICIENT_AVAILABLE_CASH`),
never silently re-sized down to whatever smaller amount available
cash would support. Verified directly:
`test_p4b_available_cash_smaller_than_allocation_rejects_not_resizes`.

**Wired into `talonx_v2/paper.py::enter_position()`**: `available_cash`
passed to sizing excludes this episode's own (about-to-be-consumed)
reservation but **does** exclude every OTHER still-`PENDING` intent's
own reserved allocation — the same accounting
`_capacity_rejection_reason()` already uses at admission time,
re-verified here as the final, same-transaction, authoritative check
(Package 2's own established principle, applied to sizing).

**Cost model**: `fee_fn` is pluggable, `(quantity, price) -> float`.
Default `sizing.zero_fee` returns `0.0` — the CURRENT, frozen,
approved assumption (matching the pre-Package-4 codebase's own actual
zero-fee behavior). **No numerical commission/spread/slippage/tax/SEC
/exchange/FX cost was invented.** `S10-22`/`OPS-014`'s own explicitly
deferred numerical-cost question remains open and unresolved — this
package makes the mechanism fee-function-capable, nothing more.
Deliberately **not** added as a `V2Config` field (to avoid any risk to
the frozen-contract `validate_frozen()` assertions or the
`V2_FINGERPRINT_EXPECTED` release-fingerprint hash, which hashes
`V2Config`'s own frozen parameter values) — `fee_fn` is an optional
parameter on `enter_position()`/`close_position()` themselves.

## 4. P4-C — Money precision

**Representation**: `Decimal`, used ONLY inside
`talonx_v2/sizing.py`'s own internal comparisons (`Q*price+fee <=
allocation`, `<= available_cash`) — the ONE place a binary-float
summation error could produce a wrong boundary decision (e.g. an
allocation that "exactly" fits N shares at an awkward price like
33.33, or a price itself carrying binary imprecision such as
`0.1+0.2`). Every float entering this boundary is converted via
`Decimal(str(x))`, never `Decimal(x)` directly on a float (which would
import the float's own raw binary value rather than its decimal
string representation).

**No repository-wide Decimal migration was performed.** Every
function in `sizing.py` still accepts and returns plain Python
`float`s at its own boundary — `positions`/`trades` remain SQLite
`REAL` columns, matching every other package's own established,
accepted float-based persistence convention. This is the "narrowest
precise-accounting boundary necessary for V2," per the task's own
explicit instruction.

**Rounding mode**: `ROUND_DOWN` (`decimal.ROUND_DOWN`) for the
`q_max` upper-bound computation (`floor`, matching "never round
quantity up"); the search itself is exact-comparison (`<=`), not a
rounding operation.

**Float-entry boundary**: the Package-3-authoritative `entry_price`
(itself a validated finite-positive float, per Package 3's own
`validate_bar`/`_bars()` fix) enters `sizing.py` and is converted to
`Decimal` exactly once, at the top of
`size_whole_shares_fee_inclusive`/`compute_exit_economics` — Package
3's own "single authoritative price, no second read" guarantee is
unaffected; this package does not introduce a second price read.

**Tests**: `test_p4c_decimal_boundary_avoids_binary_float_accumulation_error`,
`test_p4b_price_from_float_with_inexact_binary_representation`,
`test_p4b_awkward_decimal_price_33_33`.

## 5. P4-D — Reservation semantics

Verified (largely already correct, from Package 1/2's own prior work —
Session 10 §B's agreed model was ALREADY structurally implemented
before Package 4; this package's job was to verify it holds under the
NEW whole-share sizing path, not to rebuild it):

- **Create**: `upsert_entry_intent()` never touches `portfolio.cash` —
  confirmed by direct code reading and
  `test_p4d_creating_reservation_does_not_touch_cash`.
- **Fill**: `enter_position()`'s single `store.set_cash(cash - cost)`
  call, inside the SAME `BEGIN IMMEDIATE` transaction as the position
  insert and trade record (Task 131 Remediation Directive 4, unchanged)
  — `test_p4d_fill_debits_cash_exactly_once`.
- **Release (expiry)**: the pre-existing staleness sweep
  (`_phase_post_close`) marks the intent `EXPIRED_STALE` without ever
  touching cash — `test_p4d_release_via_expiry_does_not_change_cash`.
- **Restart**: a genuinely fresh `V2Service`/`V2Store` instance against
  the same file sees the same `PENDING` intent and the same cash —
  `test_p4d_restart_preserves_active_reservation`.
- **Duplicate fill**: `enter_position()`'s pre-existing idempotency
  guard (`position_for_episode`/`episode_disposition`) refuses a
  second fill for the same episode —
  `test_p4d_duplicate_fill_attempt_is_refused`.
- **Account block**: Package 2's block check remains the first
  statement inside `enter_position()`'s protected transaction, now
  running BEFORE the new sizing call — `test_p4d_account_block_still_prevents_new_reservation`.

## 6. P4-E — Position basis / exit / P&L (correction)

**Formula** (Session 10 §D, directly implemented in the new
`sizing.compute_exit_economics`): `exit_net = shares*exit_price -
exit_fee`; `realized_pnl = exit_net - entry_total`, where
`entry_total` is the AUTHORITATIVE persisted `position_cost` (never
re-derived as `shares*entry_price` alone — see the P4-E defect in §2).
Package 2 acceptance's own A5 principle (settlement derives economics
from the authoritative persisted record, a caller cannot override
shares/entry price/cost basis) is fully preserved — `close_position()`
still re-reads `position_id`, `shares`, `position_cost`, `entry_price`
fresh from the row inside the same transaction, unchanged; only the
FORMULA consuming those values was corrected.

**Reconciliation test**
(`test_p4e_round_trip_cash_reconciles_with_fees`, TEST-ONLY
illustrative fee functions — $2.50/share entry, $1.50/share exit, NOT
approved cost parameters): for a single isolated round trip,
`initial_cash - entry_total + exit_net == ending_cash` (verified
exactly), and `realized_pnl_usd == exit_net - entry_total` (verified
exactly). `test_p4e_exit_pnl_uses_authoritative_entry_total_not_notional_alone`
directly proves the fixed formula uses `entry_total`, not
`shares*entry_price` alone.

**Idempotency**: `test_p4e_duplicate_settlement_attempt_is_safe` —
Package 1's own settled-flag mechanism, re-verified against the new
formula: exactly one BUY + one SELL trade row, never two SELLs.

## 7. P4-F — Campaign defaults / configuration

**Existing behaviour, verified, not rebuilt**: `V2Config.starting_cash_usd`
already defaults to `$100,000` (`TALONX_V2_STARTING_CASH_USD`, both
configurable via env var) and `V2Config.per_position_allocation_usd`
already defaults to `$10,000` (`TALONX_V2_ALLOCATION_USD`) — these
ALREADY matched the agreed capital contract before Package 4 (no
change needed to `V2Config` itself, and none was made, for the
fingerprint-safety reason in §3). `V2Store.__init__`'s own seed logic
(`if row is None: INSERT ... starting_cash`) already correctly applies
a configured/default value ONLY to a brand-new database file, never
retroactively — confirmed directly and by
`test_p4f_new_campaign_file_receives_configured_defaults` /
`test_p4f_existing_account_retains_its_cash_when_reopened_with_different_config`
(a "restart" with a DIFFERENT configured `starting_cash` does NOT
reset an existing account's real cash).

**Remaining campaign-isolation gap (disclosed, NOT built here, per the
task's own explicit instruction not to create a broad campaign
architecture)**: "campaign identity" today is effectively "one V2
account per database file" (`V2_ACCOUNT_ID = "V2"`, a single fixed
identity per Package 2's own work) — there is no first-class
multi-dimensional `Account ID · Strategy/Version · Execution Mode ·
Campaign · Currency` model (Session 10 §A's full agreed shape).
Separately, `talonx_ops/prospective/__init__.py::CAMPAIGN_STARTING_
CASH = 300_000.0` is a hardcoded module constant tied to the SPECIFIC,
already-live production campaign's own frozen starting point (used
only for that campaign's own EOD reconciliation expected-cash
formula) — it is completely independent of, and NOT reconciled with,
`V2Config.starting_cash_usd`'s own $100,000 new-campaign default. A
future release-integration task would need to unify these into one
real campaign-identity model (e.g. reading a campaign's own recorded
starting cash from its own ledger rather than a hardcoded constant
elsewhere) before "new campaign defaults" and "reconciliation against
an existing campaign" can be said to share one authoritative source.
This gap is NOT fixed here, per the task's own explicit boundary.

## 8. P4-G — Concurrent capacity (cash-limited, independent connections)

**Scenario**: cash = $15,000, allocation = $10,000/intent, TWO
different episodes, TWO genuinely independent `V2Service`/`V2Store`
connections (not two calls on one instance) racing for admission.

**Mechanism**: `_capacity_rejection_reason()` runs inside the SAME
`BEGIN IMMEDIATE`-protected transaction as the reservation write
(`_phase_post_close`'s own `with self.store.transaction():` block,
unchanged by Package 4) — the SECOND writer's own `BEGIN IMMEDIATE`
must wait for the FIRST writer's transaction to commit before its own
`pending_entry_intents()`/`cash()` read can even run, so it correctly
sees the first writer's now-committed reservation and refuses.

**Test** (`test_p4g_two_concurrent_admissions_cannot_together_overcommit_cash`):
writer A is paused mid-transaction (holding the real SQLite write
lock, confirmed via a `threading.Event` checkpoint, not a hopeful
sleep) while writer B's own attempt is started and confirmed BLOCKED
(a bounded `Thread.join(timeout=0.5)` liveness check) before A is
released. Result: exactly one `PENDING` reservation exists afterward
(episode A's); episode B's disposition is `REJECTED_CAPACITY_EXCEEDED`
— two $10,000 reservations were never simultaneously created against
only $15,000 of real cash.

**Account blocks still win**: `test_p4d_account_block_still_prevents_new_reservation`
confirms Package 2's block check (now running before the new sizing
call, still the same first-statement-in-transaction position) remains
intact.

## 9. P4-H — Accounting invariants

Two new invariants added to `talonx_ops/prospective/close.py::
_v2_reconcile()` (extending the EXISTING `asserts`/`findings`
mechanism, not a new system): `whole_share_positions` (every
position's `shares` is integer-valued) and
`positive_finite_position_cost` (every OPEN/EXIT_UNRESOLVED position's
`position_cost` is finite and > 0). Both are wired into the EXISTING
`_record_v2_reconciliation_blocks()` — a violation records a
`LEDGER_MISMATCH` account block via `talonx_ops.account_blocks`, the
SAME mechanism Package 2 already established — **no parallel safety
system was built**, per the task's own explicit instruction.

Other invariants from the task's own list (`reserved >= 0`,
`available = cash - active reservations`, `terminal unfilled intent
has no active reservation`, `filled position cannot consume
reservation twice`, `settled position cannot settle twice`,
`EXIT_UNRESOLVED remains represented as an obligation`) are already
enforced STRUCTURALLY by Package 1/2/3's own existing mechanisms
(exactly-once `WHERE status='PENDING'`/`WHERE status='OPEN'` SQL
guards, the idempotent `account_blocks` upsert, `mark_exit_unresolved`'s
own capacity-retention fix) and were re-verified, not re-implemented,
by this package's own P4-D/P4-E tests. A retrospective "was cash ever
overcommitted historically" reconciliation check was considered but
NOT implemented — it would require importing `V2Config`'s own
`per_position_allocation_usd` into `close.py` (a module that
otherwise has no `V2Config` dependency at all), a broader coupling
judged unnecessary given the ENFORCEMENT-time mechanism (§8) already
prevents overcommitment from ever occurring.

**Tests**: `test_p4h_non_whole_share_position_triggers_ledger_mismatch_block`,
`test_p4h_invalid_cost_basis_triggers_ledger_mismatch_block` (both
simulate corruption via a direct raw SQL UPDATE, bypassing the now-safe
sizing path entirely — exactly the scenario this invariant exists to
catch if it were ever reintroduced), `test_p4h_healthy_ledger_produces_no_invariant_blocks`.

## 10. Cost model boundary (explicit statement)

**Current assumption**: zero-cost (`sizing.zero_fee`, returns `0.0`).
This exactly matches the pre-Package-4 codebase's own actual behavior
(`calculate_buy` never applied a fee). **This is NOT new profitability
evidence** — no numerical commission, spread, slippage, tax, SEC fee,
exchange fee, or FX cost was invented or applied to any V2 accounting
in this package. `S10-22`/`OPS-014`'s own deferred numerical-cost
question remains fully open. What Package 4 DOES guarantee: whichever
cost model is eventually approved will be applied CONSISTENTLY to
sizing, reservation, position basis, and exit proceeds/P&L, because
all four now flow through the SAME two functions
(`size_whole_shares_fee_inclusive`/`compute_exit_economics`) and the
SAME `fee_fn` parameter — there is no longer a risk of, say, sizing
assuming one fee while P&L assumes another (the exact defect found and
fixed in §2/§6 for the zero-fee-only case, generalized).

## 11. Schema changes (additive only)

`talonx_v2/store.py`, following the store's own pre-existing `ALTER
TABLE ... ADD COLUMN` migration convention (no destructive migration,
no new table):
- `positions`: `entry_fee REAL`, `exit_fee REAL` (nullable).
- `trades`: `fee REAL` (nullable; entry_fee on a BUY row, exit_fee on
  a SELL row).

`insert_open_position()`/`close_position()`/`append_trade()` gained
optional, backward-compatible keyword parameters (`entry_fee`,
`exit_fee`, `fee`, all defaulting to `0.0`) — every pre-existing
caller that does not pass them is unaffected.

## 12. Code changes (file-by-file)

- **`talonx_v2/sizing.py`** (new) — `zero_fee`, `SizingResult`,
  `size_whole_shares_fee_inclusive`, `ExitEconomics`,
  `compute_exit_economics`.
- **`talonx_v2/paper.py`** — `enter_position()` now uses
  `size_whole_shares_fee_inclusive` (whole-share, fee-inclusive,
  available-cash-aware) instead of `talonx_paper.engine.calculate_buy`;
  `close_position()` now uses `compute_exit_economics` instead of
  `talonx_paper.engine.calculate_sell_pnl`. Both gained an optional
  `fee_fn` parameter (default `sizing.zero_fee`). Module docstring
  updated; the now-unused `calculate_buy`/`calculate_sell_pnl` import
  removed (Original's own copies remain completely unmodified).
- **`talonx_v2/store.py`** — additive schema/migration (§11);
  `insert_open_position`/`close_position`/`append_trade` gained
  optional fee parameters.
- **`talonx_ops/prospective/close.py`** — `_v2_reconcile()` gained the
  two new P4-H invariant asserts; `_record_v2_reconciliation_blocks()`
  extended to record a `LEDGER_MISMATCH` block for either.
- **`tests/test_task110_v2_integration.py`** — one pre-existing
  source-inspection assertion corrected (`test_41_original_local_
  paper_only_no_alpaca`: now checks for `from talonx_v2.sizing import`
  instead of the no-longer-present `from talonx_paper.engine import`
  — the actual safety property it protects, no broker/Alpaca code in
  V2's paper module, is unaffected and still verified).
- **`tests/test_package3_pricing_timing.py`** — one pre-existing
  test's share-count assertion corrected
  (`test_p3a_same_entry_price_flows_into_sizing_reservation_fill_and_cost_basis`:
  now asserts the whole-share `floor()` result instead of the
  superseded continuous-division expectation — a disclosed, intended
  consequence of this package's own P4-B work, not a regression).
- **`tests/test_package4_sizing_accounting.py`** (new) — 28 targeted
  tests, P4-B through P4-H.

## 13. Tests and results

```
.venv/Scripts/python.exe -m pytest tests/test_package4_sizing_accounting.py -p no:cacheprovider -q
28 passed (run 3x to confirm no flakiness in the concurrency test)

.venv/Scripts/python.exe -m pytest tests/test_package1_settlement_integrity.py tests/test_package2_account_blocks.py tests/test_package2_acceptance_review.py tests/test_package3_pricing_timing.py -p no:cacheprovider -q
75 passed

.venv/Scripts/python.exe -m pytest <21-file V2 regression -- see regression_scope_raw.txt> -p no:cacheprovider -q
252 passed, 3 failed
```

The 3 failures are byte-identical BY NAME to 3 of the already-
documented pre-existing failures (`test_item3_original_strategy_
fingerprint_unchanged`, `test_03_v1_fingerprint_intact` — both report
the SAME `ed8272fe568d` value, the already-tracked `OPS-017` finding
in `talonx_quant/*`, a subsystem this package never touches;
`test_admission_policy_reflects_permissive_default`, also already
documented and unrelated). Zero new failures. V2's own strategy
fingerprint (`11107198c5b81237`) independently re-verified unchanged
via `tests/test_task114_prospective.py::test_b1_preflight_
fingerprints_are_expected` / `::test_task114_does_not_change_
fingerprints` (both pass) — `V2Config` itself was never modified.

## 14. Production safety

No live TalonX process found (`tasklist`, checked before and after
this session's work). `v2_lane.db`/`paper_trading.db`/
`dispatch_audit.db` content modification timestamps unchanged
throughout (every test uses an isolated `tmp_path` SQLite file). A
read-only snapshot of the real production `v2_lane.db` confirms
`positions_has_entry_fee_col: false` — this package's new schema was
never applied to production data (no deployment performed). No
application start/stop/restart, no Telegram send, no provider
activation, no real capital.

## 15. Package 4 verdict

**`PACKAGE4_ACCEPTED_WITH_BOUNDED_FOLLOWUPS`.**

All 15 acceptance-standard items are satisfied:
1-3. Whole-share, allocation-capped, available-cash-aware sizing
   (§3, tested).
4. Entry costs applied consistently to sizing/reservation/basis via
   one shared `fee_fn`/function pair (§3/§6/§10).
5-7. Reservations reduce available cash without fabricating a
   cash/equity change; release never creates cash; fill debits exactly
   once (§5, all pre-existing-and-verified or newly corrected).
8-9. Exit proceeds/P&L reconcile with authoritative persisted entry
   economics; settlement still cannot be overridden by a caller (§6).
10. Duplicate fill/settlement remain safe (§5/§6).
11. Concurrent admissions cannot overcommit capital — proven with
   independent connections (§8).
12-13. Existing account balances are not retroactively reset; new-
   account defaults are correctly represented where the architecture
   supports them (§7).
14. Money precision/rounding is explicit (Decimal, `ROUND_DOWN`, at
   one documented boundary) (§4).
15. The zero-cost assumption is explicitly disclosed, not invented
   (§10).

**Bounded follow-ups** (none block acceptance):
- The full multi-dimensional campaign-identity model (Session 10 §A)
  remains unbuilt; today's isolation is file-level only (§7).
- `CAMPAIGN_STARTING_CASH`'s own hardcoded-constant/`V2Config`-default
  reconciliation gap (§7) remains open for release integration.
- A retrospective "cash never historically overcommitted" invariant
  check was not added to `_v2_reconcile()` (§9) — the enforcement-time
  mechanism already prevents the condition from occurring.
