# V2 Release Integration Task RI-1 — Campaign Identity + End-to-End Execution Spine

**Status: EVIDENCE BUNDLE.** See the final report (delivered in-conversation) for
the RI1_* verdict. Packages 1-5's own evidence bundles are unmodified — this is
a new, separate location.

## 0. Repository state

- Repository: `Ritesh1023165/TalonX`, branch `feature/task131-option-a-integration`.
- Starting SHA: `c752af0` (Package 5, clean tree) — verified to match the reported HEAD exactly.
- Production-safety check (re-run at the start of this task, not assumed from
  Package 5): confirmed no live TalonX process running — the only `python.exe`
  processes present were this task's own earlier background `pytest`
  invocations (command-line-inspected). No `talonx.pids.json`. **No launch,
  restart, stop, or production-DB mutation was performed anywhere in this
  task.** `v2_lane.db`'s mtime was checked before and after every step that
  could plausibly have touched it and found unchanged (`2026-09-15`, see also
  §17).

## 1. Scope discipline

This is **RI-1, not Package 6**: no strategy tuning, no filter change, no
V2Config strategy-semantic change, no universe change, no provider change, no
Telegram/broker/real-capital action, no broad architecture audit. Every code
change below is either (a) additive schema/identity plumbing, or (b) a
narrowly-scoped, directly-justified fix to a concrete integration-dependency
defect RI-1's own work exposed (the fingerprint LF-normalization fragility,
§14).

## 2. RI1-A — Existing identity map (pre-RI-1)

| Component | Pre-RI-1 identity | Persisted? | Campaign-aware? | Risk if ambiguous | Action taken |
|---|---|---|---|---|---|
| Account ID | `V2_ACCOUNT_ID = "V2"`, a hardcoded module constant | Used as the key for every `account_blocks` row | No | None today (one account per file, by convention only) | RI1-B: `V2Store.account_id` is now an instance attribute, derived from `campaign_id` |
| Strategy name | Hardcoded default `'INSIDER_BUY_CLUSTER_V2'` on `positions.strategy_profile` | Yes, per-row | No campaign link | None today | RI1-B: also recorded once on the new `campaign` table |
| Strategy version | `V2_VERSION = "INSIDER_BUY_CLUSTER_V2@1"`; persisted on `positions`/`pending_entry_intents`/`v2_alert_outbox` | Yes, per-row | No campaign link | None today | RI1-B: also recorded once on `campaign` |
| Config fingerprint | Computed on demand (`v2_release_fingerprint()`), never persisted | No | N/A | No permanent record of which fingerprint was active when a given campaign was created | RI1-B: `campaign.config_fingerprint` — a LINK, explicitly not the campaign's identity (see §6 note) |
| Execution mode | Not modeled at all — implicitly always PAPER (`allow_real_capital=False`, frozen) | No | N/A | None today (single mode exists) | RI1-B: new explicit `execution_mode` field, default `"PAPER"` |
| Campaign | **Not modeled at all** | No | N/A | **The central gap** — see §3 | RI1-B: new `campaign` table |
| Ledger/database | One file per logical account, by convention/`db_path` only | De facto (file boundary) | Implicit only | An operator could point two configs at the same file with no internal check | RI1-J/K: `campaign_id` is now itself persisted and checked; a mismatch is visible (identity never silently rewritten) |
| Cash record | `portfolio` table, singleton row (`id=1`) | Yes | No | None today | Unchanged — remains the live, mutable balance; `campaign.starting_cash_usd` is the new, separate immutable seed record |
| PENDING intent / reservation | `pending_entry_intents.strategy_version` persisted; no campaign linkage | Yes | No | None today | Unchanged table; classified by `talonx_v2/cutover.py` (RI1-D/E) using the SAME store (= SAME campaign, by file boundary) |
| Position | `positions.strategy_profile`/`strategy_version` persisted; no campaign linkage | Yes | No | None today | Unchanged — RI1-L reconstructs campaign identity via the OWNING store's `campaign_identity()`, not a per-row column |
| Exit | Same `positions` row (no separate exit-identity table) | Yes | No | None today | Unchanged |
| Reconciliation | `talonx_ops/prospective/close.py::_v2_reconcile()` used a single, GLOBAL, hardcoded `CAMPAIGN_STARTING_CASH = 300_000.0` | N/A (a constant, not campaign data) | **No — the actual ambiguity** | A second campaign seeded at $100,000 would reconcile against the WRONG $300,000 baseline | RI1-C: `campaign_cash.authoritative_starting_cash()` — see §5, new `OPS-024` |
| Account block | `account_blocks` table, keyed by `account_id` | Yes | Implicit (file boundary) | None today | RI1-H: boundary explicitly justified (§9) |
| Clearance | `block_clearances`, keyed transitively via `block_id` | Yes | Implicit | None today | Unchanged |
| Alert/event record | `v2_alert_outbox.strategy_version` persisted; no campaign linkage | Yes | No | None today | Unchanged — not required for RI-1's own acceptance standard |

**No implementation was attempted before this map was complete** (RI1-A's own
instruction) — this table was produced first, entirely from direct code
reads (`talonx_v2/{config,store,paper,service}.py`,
`talonx_ops/{account_blocks.py,prospective/{__init__,close,ledger_guard}.py}`),
before any file listed in §14 was edited.

## 3. RI1-B — Canonical campaign model

**Design choice, and why**: the codebase already has an established
"one logical account per ledger file" model (`V2Store`'s own comment,
`V2_ACCOUNT_ID`, `db_path` fully configurable via `TALONX_V2_DB_PATH`).
RI-1 **extends this existing pattern** rather than building a
multi-campaign-per-file abstraction — a new campaign is a new `V2Store`
opened against a new `db_path` with an explicit `campaign_id`. This is
the smallest coherent model that satisfies every required invariant, and
gives the STRONGEST possible isolation guarantee for free: two campaigns
in two separate SQLite files cannot accidentally share capital/accounting
state, because they are not even the same connection.

**New table** (`talonx_v2/store.py`), one row per ledger file, written
**exactly once**:

```sql
CREATE TABLE campaign (
    id                          INTEGER PRIMARY KEY CHECK (id = 1),
    campaign_id                 TEXT NOT NULL,
    strategy                    TEXT NOT NULL,
    strategy_version            TEXT NOT NULL,
    execution_mode               TEXT NOT NULL,
    starting_cash_usd           REAL,   -- NULL only for an unbackfilled legacy campaign
    per_position_allocation_usd REAL,
    config_fingerprint           TEXT,   -- a LINK, not the identity itself
    provenance                   TEXT NOT NULL,  -- SEEDED_AT_CREATION | LEGACY_MIGRATED[_BACKFILLED:...]
    created_at_utc               TEXT NOT NULL
);
```

**Identity fields**: `campaign_id` (explicit, `V2Config.campaign_id`,
env `TALONX_V2_CAMPAIGN_ID`, default `"V2"` — reproduces the EXISTING
production campaign's identity exactly), `strategy`, `strategy_version`
(`V2_VERSION`), `execution_mode` (`V2Config.execution_mode`, env
`TALONX_V2_EXECUTION_MODE`, default `"PAPER"`).

**Persistence / stability / restart semantics**: seeded inside the SAME
transaction as `portfolio`'s own seed-once check (`V2Store._init()`) —
either both are freshly created together (`SEEDED_AT_CREATION`) or
neither is touched again on every later open. A SECOND `V2Store(...)`
call against the same file, even with completely different constructor
arguments, **never** rewrites the already-seeded row — directly proven
by `test_ri1b_identity_is_stable_and_restart_safe`.

**Campaign identity vs. strategy fingerprint** (explicit distinction,
per this task's own instruction): `campaign.config_fingerprint` is
recorded as a **link** — "this is the code/config fingerprint that was
active when this campaign was created" — never used AS the campaign's
own primary identity. The campaign's actual identity is
`(campaign_id, strategy, strategy_version, execution_mode)`, which is
stable even if the fingerprint later changes for a non-strategy reason
(exactly as happened in §14 of this very task).

**Account ID / campaign ID boundary** (RI1-H's own required
justification): `V2Store.account_id` now equals `campaign_id` for that
instance (default `"V2"`, unchanged for the existing production
account). Since campaigns are already isolated by **separate files**
(the strongest possible boundary), this string never needs to
discriminate between two campaigns that could otherwise share state —
it is a per-file label, not a lookup key across campaigns. Directly
proven: `test_ri1b_account_id_and_campaign_id_coincide_by_construction`,
`test_ri1h_block_on_campaign_a_does_not_affect_campaign_b`.

## 4. RI1-C — Capitalization authority

**The ambiguity found** (`OPS-024`): `V2Config.starting_cash_usd`
(env `TALONX_V2_STARTING_CASH_USD`, default $100,000 — the actual
mechanism seeding `portfolio.cash`) and
`talonx_ops.prospective.CAMPAIGN_STARTING_CASH` (a SEPARATE hardcoded
module constant, $300,000, used only by reconciliation/continuity
checks) were two independent numbers. They agreed only because an
operator manually kept both in sync for the ONE existing production
campaign — a second campaign at the new $100,000 default would have
reconciled against the wrong baseline.

**The fix — ONE authoritative path**: `talonx_ops/prospective/
campaign_cash.py::authoritative_starting_cash(con)` — reads the
campaign's own persisted `starting_cash_usd` FIRST; falls back to the
pre-RI-1 `CAMPAIGN_STARTING_CASH` constant only when that column is
absent (a pre-RI-1 db) or NULL (a legacy campaign not yet backfilled,
§8). Wired into both `close.py::_v2_reconcile()` and
`ledger_guard.py::check_ledger_continuity()` (previously two
independent copies of the same ambiguity).

**Seed-once proof**: `test_ri1c_new_campaign_receives_configured_cash_
exactly_once` — a second `V2Store(...)` open with a DIFFERENT
`starting_cash` argument does not change either `portfolio.cash` or
`campaign.starting_cash_usd`.

**Existing-account preservation**: `test_ri1c_existing_campaign_not_
reset_by_restart_or_config_change` — a real trade changes cash; a
later reopen with a different configured starting cash preserves both
the traded balance AND the original seed record.

**Independent campaigns**: `test_ri1c_independent_campaigns_have_
independent_capital` — two `V2Store`s, two files, a cash mutation on
one is provably invisible to the other (not just "should be" — directly
read back).

## 5. RI1-D/E — Version cutover

**New module**: `talonx_v2/cutover.py::classify_and_cancel_pending_at_
cutover(store, *, as_of_session, max_entry_staleness_sessions,
cutover_id, live=False)`.

Reuses (does not reinvent) Package 3's own recovery-deadline math —
extracted from `V2Service._recovery_deadline_session`/`_recovery_
deadline_passed` into free functions in `talonx_v2/calendar.py`
(`recovery_deadline_session`, `recovery_deadline_passed`), a
behavior-preserving refactor (`V2Service`'s own methods now delegate to
them; re-confirmed via `tests/test_package3_pricing_timing.py`, 19/19
unchanged).

**Classification** (per currently-PENDING intent only — anything
already terminal is untouched):
- `target_entry_session > as_of_session` → **genuinely future,
  unfilled** → `CANCELLED_CUTOVER` (a new terminal status).
- `target_entry_session <= as_of_session` AND recovery window not yet
  passed → **timely admitted, still recovering** → left completely
  alone (remains `PENDING`, governed by the OLD campaign's own
  continuing lifecycle rules until fill/expiry).
- `target_entry_session <= as_of_session` AND recovery window already
  passed → `EXPIRED_RECOVERY_DEADLINE` (mirrors exactly what the old
  campaign's own service tick would have produced — not a
  cutover-specific invention).

**Old campaign positions never move**: `talonx_v2/cutover.py` never
touches the `positions` table — only `pending_entry_intents`. Directly
proven: `test_ri1de_old_campaign_positions_never_move_to_new_campaign`.

**Idempotent**: relies on `V2Store.mark_entry_intent`'s own
`WHERE status='PENDING'` guard (a second invocation finds nothing left
to transition). A durable audit row is appended to the new
`campaign_cutover_log` table on every invocation, including repeats —
`test_ri1de_duplicate_cutover_invocation_is_idempotent` (0 further
state change, 2 audit rows).

**Required test coverage, all present**: future-unfilled → cancelled
(`test_ri1de_future_unfilled_intent_is_cancelled`); Session-2 recovery
→ retained (`..._session2_is_retained`); Session-3 recovery → retained
(`..._session3_is_retained`); expired recovery → terminal
(`test_ri1de_expired_recovery_is_terminal_no_new_exposure`); restart
during cutover (`test_ri1de_restart_during_cutover_leaves_state_
consistent`); duplicate invocation (above).

## 6. RI1-F — Entry integration

Drives the REAL internal spine (`V2Service._phase_post_close` for the
durable pre-open reservation, `V2Service._phase_open` for the fill —
the SAME two calls `tick()` itself makes, just without a heavier
InsiderStore/parquet discovery fixture RI-1 does not need — episode
DISCOVERY is already proven by Packages 1-3; this proves CAMPAIGN
IDENTITY flows correctly through the EXISTING, already-proven spine).

**Proven, with actual assertions** (`test_ri1f_full_entry_spine_
preserves_identity_and_capital_invariants`, durable-store gate
explicitly enabled so a real prior reservation is REQUIRED, not
optional):
- Correct campaign: `campaign_identity()` identical before and after
  the trade.
- Correct account: `V2Store.account_id` == the campaign's own id
  throughout.
- Correct price: `pos["entry_price"]` matches the bar's own open.
- Correct integer shares: `pos["shares"] == int(pos["shares"])`.
- Correct position cost: `== shares * price` (zero-cost baseline,
  disclosed).
- Cash debited once: `cash == BALANCE - position_cost`, exactly.
- Reservation consumed once: zero remaining `PENDING` rows for that
  episode after fill.
- No cross-campaign capital mutation:
  `test_ri1f_no_cross_campaign_capital_mutation_during_entry` — two
  independent campaigns, one trades, the other's cash is byte-identical
  to its own starting value.

**No Telegram required**: no `transport`/`router` argument is passed to
`V2Service` anywhere in `tests/test_ri1_campaign_identity.py` — every
assertion is made directly against `store`/`svc.store`, proving
execution is independent of notification delivery by construction (not
merely by claim).

## 7. RI1-G — Exit integration

**Session-10 exit**: `test_ri1g_full_session10_exit_preserves_identity_
and_settles_once` — `paper.close_position(...)` via the direct API
(same one Package 4's own tests use); campaign identity unchanged
before/after; cash increases by exactly the net exit proceeds; realized
P&L matches; **settlement idempotency** directly proven — a second
`close_position` attempt on the same already-closed position is refused
(`out2.settled is False`) and changes no cash.

**EXIT_UNRESOLVED**: `test_ri1g_exit_unresolved_retains_campaign_
identity_and_blocks_new_entries` — campaign identity survives; the
Package-2 account block correctly prevents a NEW admission
(`ACCOUNT_BLOCKED` reason).

**Delayed exit / fall-forward**: `test_ri1g_delayed_exit_fallforward_
still_settles_and_preserves_identity` — drives the real
`pipeline.settle_due_exits` path via `svc.tick()`, campaign identity
unchanged across the exit tick.

## 8. RI1-H — Account blocks

**Boundary, explicitly justified** (not invented, not a global policy):
within ONE ledger file, `account_id == campaign_id` by construction
(§3) — and since campaigns are ALREADY isolated by separate files, a
block recorded in campaign A's `account_blocks` table physically cannot
appear in campaign B's (different file, different table instance).
Directly proven, not merely argued:
- `test_ri1h_block_on_campaign_a_does_not_affect_campaign_b`.
- `test_ri1h_exit_unresolved_recovery_still_executes_while_blocked` —
  a block stops NEW exposure, never an EXISTING obligation's recovery
  (reconfirms Package 2's own accepted rule under campaign identity).
- `test_ri1h_block_survives_restart`.

Creating a new campaign (a new file) can **never** be used as a loophole
to bypass an existing block, because a genuinely new campaign is a
genuinely new, separately-capitalized economic entity — not a way to
"launder" an existing obligation. (An operator deliberately moving an
UNRESOLVED position's economic responsibility to a new campaign is
explicitly out of scope — RI1-D/E's own rule is that existing positions
never move between campaigns at all.)

## 9. RI1-I — Reconciliation by identity

`test_ri1i_reconciliation_never_mixes_two_campaigns` — two campaigns,
two starting-cash amounts ($100k / $250k), each reconciles independently
and correctly against its OWN `starting_cash`, never the other's.
`test_ri1i_reconciliation_derives_every_required_figure_per_campaign` —
confirms `_v2_reconcile()`'s output already carries every figure RI1-I
requires (cash, open positions, EXIT_UNRESOLVED, settled trades,
realized P&L) per the campaign it was pointed at; account blocks are
separately queryable via the same store (`active_account_blocks()`).

This is **release-safety reconciliation, not a new analytics
platform** — no new computation was added; only the starting-cash INPUT
became campaign-aware (§5).

## 10. RI1-J — Restart/recovery

All proven with **fresh `V2Store`/`V2Service` instances** (not the same
Python object — a genuinely new connection against the same file):
- Campaign identity survives (`test_ri1j_full_state_survives_restart_
  with_fresh_instances`).
- Cash survives, is NOT recapitalized (same test, `store2.cash() ==
  cash_before`, `store2.campaign_identity() == identity_before`).
- PENDING intents survive (`test_ri1j_restart_with_pending_intent_
  survives`).
- No duplicate fill after restart
  (`test_ri1j_restart_does_not_duplicate_fill_or_settlement`).
- Positions/blocks/cutover state surviving restart are directly proven
  by §3/§5/§8's own tests (each explicitly deletes and reopens the
  store instance).

## 11. RI1-K — Legacy data / schema compatibility

**Policy, evidence-backed, never fabricated**: a ledger file opened for
the first time under RI-1 code, which ALREADY had a `portfolio` row (a
pre-RI-1 file), gets a `campaign` row with `provenance =
"LEGACY_MIGRATED"` and `starting_cash_usd = NULL` — the current `cash`
balance already reflects realized trading P&L, so the TRUE original
seed amount cannot be safely reconstructed from it alone. This is
NEVER guessed.

**What CAN be derived safely**: `campaign_id`/`strategy`/
`strategy_version`/`execution_mode` (the CURRENT config's own values —
correct for the one existing production campaign, whose identity these
defaults were chosen to reproduce exactly).

**What CANNOT**: the historical starting cash. Reconciliation for such
a campaign falls back to the pre-RI-1 `CAMPAIGN_STARTING_CASH` constant
(§4) — an EXPLICIT, documented, already-known value for the one real
production account, not a guess.

**Explicit backfill, evidence-cited, one-time**:
`V2Store.set_legacy_starting_cash(amount, *, evidence_ref)` — refuses
to overwrite an already-known value (`SEEDED_AT_CREATION`, or an
already-backfilled legacy row); records the citation in `provenance`.
Directly proven: `test_ri1k_explicit_evidence_cited_backfill_of_
legacy_starting_cash` (including the refusal on a second attempt).

**Ambiguous rows do NOT block release admission** in this design —
they simply keep using the pre-RI-1 fallback constant, which is already
the CORRECT value for the one production campaign that exists today.
No additive migration was found insufficient; a full schema migration
was not required.

**Production implications**: `V2Store()` opening the REAL `v2_lane.db`
for the first time under this code would create exactly this
`LEGACY_MIGRATED` campaign row (`starting_cash_usd=NULL`, correctly
falling back to `CAMPAIGN_STARTING_CASH=300_000.0` for reconciliation —
byte-identical behavior to today). **This was NOT exercised against the
real file in this task** — `test_ri1k_production_db_is_never_opened_or_
migrated_by_these_tests` documents the invariant; all other RI1-K tests
use a purpose-built fixture (`_pre_ri1_shaped_db`) shaped like a legacy
ledger, never the real file. `v2_lane.db`'s mtime was independently
checked unchanged throughout this task (§0, §17).

## 12. RI1-L — Audit reconstruction

`test_ri1l_one_completed_trade_is_fully_reconstructable` — for one
complete entry→exit trade, every question RI1-L's own list poses is
answered from ALREADY-PERSISTED evidence, with no new event-sourcing
platform: strategy (`campaign.strategy`), version
(`campaign.strategy_version`), execution mode
(`campaign.execution_mode`), campaign (`campaign.campaign_id`),
account/capital (`campaign.starting_cash_usd`), price/shares/cost/exit/
P&L (`positions` row), admission evidence
(`episode_disposition() == "ENTERED"`), full trade history
(`trades()`, `["BUY", "SELL"]`).

## 13. Schema / code / document changes (file-by-file)

**New files**:
- `talonx_v2/cutover.py` — RI1-D/E cutover classification.
- `talonx_ops/prospective/campaign_cash.py` — RI1-C's one authoritative
  starting-cash resolver (extracted to its own module to avoid a
  `close.py`↔`ledger_guard.py` circular import).
- `tests/test_ri1_campaign_identity.py` — 35 targeted tests.
- This evidence bundle.

**Modified**:
- `talonx_v2/store.py` — new `campaign`/`campaign_cutover_log` tables;
  `V2Store.__init__` gained `campaign_id`/`strategy`/`strategy_version`/
  `execution_mode`/`per_position_allocation_usd`/`config_fingerprint`
  kwargs (all optional, defaults reproduce pre-RI-1 behavior exactly);
  `_init()` seeds the campaign row exactly once; new
  `campaign_identity()`/`campaign_starting_cash()`/
  `set_legacy_starting_cash()`/`record_cutover()`/`cutover_log()`
  methods; `V2_ACCOUNT_ID`-based block-check call sites switched to
  `self.account_id`.
- `talonx_v2/config.py` — new `campaign_id`/`execution_mode` fields
  (operational identity, same non-frozen category as
  `starting_cash_usd`/`per_position_allocation_usd`; NOT asserted by
  `validate_frozen()`, NOT in `v2_release_fingerprint()`'s hashed
  `cfg` dict — see §14 for the byte-level fingerprint consequence this
  still has).
- `talonx_v2/calendar.py` — new `recovery_deadline_session`/
  `recovery_deadline_passed` free functions (extracted from
  `V2Service`, reused by `talonx_v2/cutover.py`).
- `talonx_v2/service.py` — `_recovery_deadline_session` delegates to
  the new free function (byte-identical behavior); `_recovery_deadline_
  passed`'s deadline-SESSION computation delegates too, but its
  live-mode wall-clock read deliberately stays in this module (existing
  tests monkeypatch `service_module.datetime`, see the method's own
  comment); `V2Store(...)` construction threads the new campaign fields
  through; `V2_ACCOUNT_ID` block-check call site switched to
  `self.store.account_id`.
- `talonx_v2/paper.py` — `V2_ACCOUNT_ID` block-check call site switched
  to `store.account_id`.
- `talonx_v2/run.py` — `V2Store(...)` construction threads the new
  campaign fields through.
- `talonx_ops/prospective/close.py` — `_v2_reconcile()` uses
  `campaign_cash.authoritative_starting_cash()` instead of the
  hardcoded `CAMPAIGN_STARTING_CASH` import.
- `talonx_ops/prospective/ledger_guard.py` — same fix,
  `check_ledger_continuity()`.
- `talonx_ops/dashboard_read.py` — the one pre-existing fallback literal
  for `V2_FINGERPRINT_EXPECTED` (used only if the live import fails)
  updated to match; no other dashboard change (checked: no
  `starting_cash`/`campaign_id` presentation exists there yet to
  misrepresent — nothing further was narrowly required).
- `talonx_ops/watchlist_coverage.py` — the one static human-readable
  fingerprint string now reads the live constant instead of a
  duplicated literal.
- `talonx_ops/prospective/__init__.py` — `V2_FINGERPRINT_EXPECTED`
  updated `"11107198c5b81237"` → `"e2acf6454789217e"`, fully justified
  inline (§14).
- `research/scripts/task112_v2_release_fingerprint.py` — LF-
  normalization fix (§14, `OPS-023`).
- Five pre-existing test files (`tests/test_task114_prospective.py`,
  `tests/test_task117_deployment_rehearsal.py`, `tests/
  test_task117_overnight_e2e.py`, `tests/
  test_task117_phase0_source_readiness.py`, `tests/
  test_task117_spa_states.py`) — hardcoded fingerprint literals switched
  to reference the live `V2_FINGERPRINT_EXPECTED` constant (several
  already had this stale-duplicate defect, independent of RI-1's own
  fingerprint change).
- Three pre-existing test files (`tests/
  test_package1_settlement_integrity.py`, `tests/
  test_package2_account_blocks.py`, `tests/
  test_package4_sizing_accounting.py`) — `CAMPAIGN_STARTING_CASH`
  monkeypatch target retargeted to the new `campaign_cash` module; one
  test (`test_clear_block_ledger_mismatch_refuses_while_reconcile_
  still_fails`) redesigned to inject a genuine ledger-data mismatch
  directly, since patching the now-secondary fallback constant is no
  longer sufficient once a real campaign record exists (disclosed
  consequence of RI1-C's own correctness improvement, not a
  regression).
- `docs/product/OPERATIONAL_FINDINGS.md` — new `OPS-023`, `OPS-024`.
- `docs/product/REQUIREMENTS_TRACKER.md` — new `S13-15` (Package 5,
  retroactively recorded — it built no product-facing behavior, so had
  no prior row), `S13-16` (this task).

**Explicitly NOT touched**: `talonx_quant/*`, `talonx_paper/*` (Original,
untouched), any V2 strategy-semantic value inside `V2Config`
(`validate_frozen()`'s own asserted set), any dashboard page beyond the
one fallback-literal correction, any Telegram/provider/broker code.

## 14. The V2 fingerprint change, in full

Two SEPARATE things happened to the V2 release fingerprint in this
task, and they must not be conflated:

1. **A deliberate, disclosed content change**: `talonx_v2/config.py`
   (one of the 5 fingerprinted `_STRATEGY_FILES`) gained two new
   dataclass fields (`campaign_id`, `execution_mode`) — account/
   operational identity, the same category as the already-present,
   already-NOT-frozen `starting_cash_usd`/`per_position_allocation_usd`
   fields. This changes the FILE'S OWN BYTES, which the fingerprint
   hashes directly. Every individually-hashed STRATEGY value was
   re-verified byte-for-byte unchanged (§13, `v2_release_fingerprint()`
   output's own `"config"` dict).

2. **A pre-existing latent defect, found and fixed** (`OPS-023`):
   `v2_release_fingerprint()` had no line-ending normalization —
   directly confirmed unstable via a plain `git stash`/`git stash pop`
   roundtrip (zero real content change) shifting the computed value
   three different ways across three re-computations. Fixed with the
   IDENTICAL technique Task 137 already applied to V1's own fingerprint
   (`get_strategy_version()`) for the exact same class of defect.

The final, stable value (`"e2acf6454789217e"`) was recomputed directly
from the actual current file contents — never invented, never
back-solved to make a test pass.

## 15. Targeted tests

- `tests/test_ri1_campaign_identity.py` — **35 new tests, 35/35 pass**,
  covering all 29 minimum required scenarios from the task's own list
  (several get more than one test). Two tests initially exhibited
  test-ORDER-dependent flakiness in a combined run (a hardcoded,
  unreachable `eligible_entry_session` happened to still produce a
  "cold fill" only when the durable-store gate was OFF, which varied by
  suite ordering) — fixed by using a genuinely reachable
  `eligible_entry_session` for every entry-spine test, removing the
  dependency on gate state entirely; also fixed one genuinely vacuous
  restart test (`test_ri1j_restart_does_not_duplicate_fill_or_
  settlement`) that used a non-existent injection hook and passed only
  because zero trades occurred on either side of the "restart."
- Regression: `tests/test_package1_settlement_integrity.py` +
  `test_package2_account_blocks.py` + `test_package2_acceptance_review.py`
  + `test_package3_pricing_timing.py` + `test_package4_sizing_accounting.py`
  + `test_ri1_campaign_identity.py` + `test_task110_v2_integration.py` +
  `test_task111_v2_e2e.py` + `test_task112_tuesday_release.py` +
  `test_task113_stale_entry_guard.py` + `test_task114_prospective.py`:
  **277 passed, 2 failed** (both the pre-existing, unrelated `OPS-017`
  V1-fingerprint stale-literal failures, confirmed via `git stash`
  against clean `c752af0` before any RI-1 change existed). `tests/
  test_package5_intraday_causality.py` re-run standalone: unaffected
  (RI-1 touches no `talonx_backtest`/`talonx_quant` file).

## 16. Limitations / remaining release gaps

- `S12-23` (numerical execution-cost calibration) remains open — RI-1
  invented no new fee/slippage/spread assumption; V2's cost model stays
  explicitly zero-cost.
- The comprehensive `S12-01` prior-research review remains a separate,
  undischarged future task (unaffected by RI-1).
- `test_task117_deployment_rehearsal.py::
  test_bounded_controlled_deployment_rehearsal` fails on a PRE-EXISTING
  (confirmed via `git stash` against clean `c752af0`), UNRELATED
  production-`v2_lane.db`-byte-hash staleness (`EXPECTED_MD5` was
  recorded before the live campaign's own continued trading legitimately
  changed the file) — not caused by, and not fixed by, RI-1; recorded
  here per the task's own "record but do not expand" instruction.
- `OPS-017` (Original/V1 fingerprint stale-literal in two test files)
  remains open, unrelated to RI-1 (V1/Original untouched).
- RI-2 (Telegram/operations routing), dashboard/operator integration
  beyond the one bounded fallback-literal correction, provider
  qualification, and prospective paper validation are all explicitly
  NOT started.

## 17. Production safety

No `python.exe` process other than this task's own background `pytest`
invocations was found running at any point. `v2_lane.db`'s modification
time was independently checked before this task began and again at
evidence-writing time — unchanged. No `V2Store` in this task's own test
suite or investigation was ever constructed against the real
repository-root `v2_lane.db` path — every fixture uses `tmp_path`. No
Telegram send, broker call, or provider activation occurred anywhere in
this task.
