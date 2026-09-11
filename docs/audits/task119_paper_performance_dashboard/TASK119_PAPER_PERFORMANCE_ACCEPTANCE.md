# Task 119 — attributable paper-performance dashboard: acceptance

> **2026-09-12 (Task119A) correction — do not treat this document's claims
> below as the final state.** Task 119 added a SEPARATE "Paper Performance"
> tab alongside the pre-existing "Paper / EOD" tab, duplicating
> Original/Experimental's numbers across two destinations with different
> period labels and no reconciliation between them. It also mislabelled
> Original/Experimental's costs as blanket "UNMODELED" when
> `talonx_paper.engine.apply_spread()` in fact DOES simulate a bid-ask
> spread (baked into every fill price) — only explicit commissions/fees
> are unmodeled. It also approximated the regular-session open as
> `close - 6h30m`, which is wrong on an early-close (half) day. All three
> are corrected in Task 119A — see
> `docs/audits/task119a_paper_eod_integration/TASK119A_CORRECTIONS_AND_INTEGRATION.md`
> for the full account, and the workflow lesson: **acceptance must cover
> the actual requested user journey (one destination for paper portfolios
> and reconciliation), not merely passing fixtures for a different,
> additional-tab implementation that technically worked but did not match
> what was asked.** The screenshots and reconciliation table referenced
> below still accurately describe the tab AS IT EXISTED at Task 119's own
> completion; that tab no longer exists post-Task-119A — its data is now
> folded into Paper/EOD and Active V2, per the corrected document above.

**Branch**: `hotfix/task119-paper-performance-dashboard`, parent `d4177b3`
(release `research/talonx-strategy-validation`'s HEAD at task start —
verified, not assumed, at start of this task).
**Status**: implemented, tested, rendered, **not merged into the release
branch** — a reviewed candidate for the next session (see §Candidate
activation below), consistent with "the output is a candidate for the
next session, not an automatic activation."

## What this task is, and is not

This **extends** the existing `:8787` unified cockpit
(`talonx_ops.dashboard_read.DashboardReadModel`, `dashboard_web.py`,
`dashboard_web_static/index.html`) with one new, additive, read-only
section — **Paper Performance** — that answers the one question the
existing `paper_eod()` section deliberately leaves shallow (open-position
counts and cash only, no P&L, no marks, no reconciliation). It does **not**
create a second dashboard, a second ledger, or a new accounting engine:
every number is read from the exact same authoritative sources
`paper_eod()` already reads (`talonx_paper.store`'s schema for
Original/Experimental, `v2_lane.db` for V2), with one additional read
(`latest_prices`) for marks.

## Source mapping

| lane | source db(s) | tables read |
|---|---|---|
| Original | `paper_trading.db` | `portfolio_state`, `positions`, `trade_history`, `latest_prices` |
| Experimental | `experimental/experimental_paper.db` | same schema (same store class); marks fall back to `paper_trading.db.latest_prices` when the lane's own `latest_prices` has no row for that symbol (Experimental's engine does not write its own price feed — confirmed by reading the real `~/.talonx` state this session) |
| V2 | `v2_lane.db` (env `TALONX_V2_DB_PATH` or repo-root default, same resolution `v2_active_strategy()` already uses) | `portfolio`, `positions`, `trades`; marks read from `paper_trading.db.latest_prices` (V2 carries no `latest_prices` table of its own) |
| PIV | — | `NOT_CHECKED` (a real position/order read requires a network call to Alpaca's paper endpoint, which this read-only surface does not perform — labelled, not silently a `0`) |
| Intelligence | — | no attributable paper ledger exists; explicitly labelled, none invented |

New module: `talonx_ops/paper_performance.py` (one accounting
implementation, shared by Original and Experimental via one internal
helper — see its own docstring for the full design-constraint list).
Wired in via `DashboardReadModel.paper_performance()` (new method,
`paper_eod()` unchanged) → `dashboard_web.py`'s `_UNIFIED_SECTIONS` (now 8
sections, was 7) → a new `Paper Performance` tab in `index.html`.

## Accounting definitions used

- **Equity** = `cash + marked open-position value` (never cash alone). If
  any open position lacks a usable mark, equity is `PARTIAL` (cash floor
  still shown, never silently filled with a fabricated mark).
- **Reconciliation**: `expected_cash = initial_balance − open_position_cost_basis_total
  + total_realized_pnl_usd` (Original/Experimental) or
  `starting_campaign_cash($300,000) − open_position_cost_basis_total +
  realized_pnl_campaign_to_date` (V2), compared against the ledger's own
  `current_cash`/`cash` — an **arithmetic** check against raw ledger
  values, not a copied summary string.
- **Costs**: confirmed by reading `talonx_paper/engine.py` that no
  commission/fee/slippage is modelled anywhere in the paper-trading
  engine — every P&L figure is gross-equals-net, reported as `UNMODELED`,
  never silently subtracted twice and never presented as a modelled zero.
- **Valuation timestamp classification**: `PRE_MARKET` / `REGULAR_SESSION`
  / `POST_CLOSE` / `STALE_HISTORICAL` / `UNAVAILABLE`, using
  `talonx_signals.market_sessions.session_close_utc` — the SAME
  `exchange_calendars`-backed regular-close instant already authoritative
  elsewhere in this repo (Task 99G) — never a re-derived approximation. A
  post-close mark is explicitly labelled "NOT an official regular-session
  closing price" and never combined with an "as of 20:00Z" label.
- **Recovery-affected**: an explicit, evidence-sourced constant
  (`RECOVERY_AFFECTED_EXPERIMENTAL_TRADE_IDS = {6,7,8,9}`, citing
  `docs/research/SESSION_2026-09-11_OUTCOMES.md` and the Task 118A fix
  commit `c88f4d4`) — never inferred from "any SELL row," never mutates
  the underlying `trade_history` row, and does not silently expand to
  future sessions' exits (proven by
  `test_recovery_affected_flag_tied_to_known_ids`).
- **Session vs. campaign**: `trade_counts.{entries,exits}_today` filtered
  by the trade's own UTC calendar date against `session_date`; `_campaign_to_date`
  counts every row ever. Verified against the real Sept-11 ledger: 5
  campaign entries (Sept 9–10), 0 entries today, 4 exits today — the exact
  distinction Task 118H's own instruction required ("do not call them five
  entries today without ledger evidence").

## Friday (2026-09-11) reconciliation

Reproduced as an **isolated fixture** (`spa/make_fixture.py`'s
`friday_reconciled` scenario) from the exact real ledger rows read
read-only from `~/.talonx` at the start of this task (see
`docs/research/SESSION_2026-09-11_FINAL.md`, Task 118H) — not re-derived,
not guessed:

| field | expected (Task 118H evidence) | this surface | match |
|---|---|---|---|
| Original trades today | 0 | 0 | YES |
| Experimental campaign entries | 5 (span Sept 9–10) | 5 | YES |
| Experimental exits today | 4 | 4 | YES |
| Experimental realized P&L | −324.4662160270568 | −324.4662160270568 | YES |
| SPCX mark | $151.2100 @ 2026-09-11T20:08:00Z | $151.2100 @ 2026-09-11T20:08:00Z | YES |
| SPCX mark classification | POST_CLOSE (after 20:00Z regular close) | `POST_CLOSE`, note: "NOT an official regular-session closing price" | YES |
| SPCX unrealized P&L | ≈ +$50.30 | +$50.30 (+2.01%) | YES |
| V2 cash / trades | $300,000, 0/0/0 | $300,000, 0 trades | YES |
| Experimental/V2 reconciliation | should tie out exactly | `EXACT` both lanes | YES |

Full machine-checked table (27 field checks, all match): see
`results/task119_paper_performance/spa/value_reconciliation.md`.

Intelligence activity is kept a separate measure throughout — 6 cards → 1
digest message is never conflated with a paper-trade count (Intelligence
has no attributable paper ledger and none is surfaced here).

## Tests

`tests/test_task119_paper_performance.py` — 18 focused tests, isolated
`tmp_path` sqlite fixtures only, never opens `~/.talonx` or the repo-root
`v2_lane.db`:

1. Lane/source separation (no cash ever summed across lanes).
2. Session-vs-campaign counts (the exact 5-entries/4-exits-today case).
3. Equity including marked open-position value.
4. Cost handling — `UNMODELED`, never double-deducted.
5. Missing marks → `UNAVAILABLE`, never a fabricated `0` (two tests: a
   missing-mark open position, and the zero-open-positions valid-0 case).
6. Post-close vs. regular-session vs. stale-historical vs. unavailable
   valuation labelling (four tests against `classify_valuation_timestamp`).
7. Recovery provenance — tied to explicit evidenced ids, proven NOT to
   fire on an unrelated trade's id, proven to fire on the evidenced ids.
8. Reconciliation `EXACT` / `MISMATCH` / `UNAVAILABLE` (three tests).
9. No production writes (mtime-unchanged assertion) and no network socket
   opened (a monkeypatched `socket.socket` that raises if called).
10. `DashboardReadModel.paper_performance()` wiring + `all_sections()`.

`pytest tests/test_task119_paper_performance.py -q` → **18 passed**.

Changed-surface regression (dashboard/100C/112/114/119 keyword-selected —
the actual sections this task touches):
`pytest tests/ -k "dashboard or task100c or task114 or task119 or task112" -q`
→ **268 passed** (two pre-existing `test_task100c_unified_dashboard.py`
section-count assertions were legitimately updated from 7→8 sections;
their PASS is a deliberate acceptance of the extension, not a masked
failure). Full pytest run not performed (out of scope per this task's own
"avoid broad unrelated testing" instruction) — the section set this task
touches is fully covered.

**One unrelated failure disclosed, not masked**: `tests/test_task117_release_rehearsal.py::test_bounded_release_rehearsal`
fails identically with this task's changes stashed out (`git stash` +
re-run confirmed) — a pre-existing Delivery-Outbox/Telegram-card retry
test unrelated to this task's surface, not touched or fixed here.

## Rendered acceptance (real SPA, isolated fixtures)

`results/task119_paper_performance/spa/` — the **actual** `dashboard_web.py`
aiohttp server (not a standalone mockup), started against an isolated
`TALONX_HOME` + `TALONX_V2_DB_PATH` per scenario (port 8898, loopback
only; production `~/.talonx`, the repo-root `v2_lane.db`, and Redis are
never opened — `TALONX_REDIS_URL` points at a nonexistent db15 on a
non-standard port), headless-Chrome-captured at a realistic 1360×2600
viewport, hash-routed straight to the new tab (`#paper_performance`).
**Fixture pages, not live acceptance** — every page's `session_date` and
regular-close instant come from the isolated fixture data, not a
production feed.

| scenario | demonstrates | screenshot |
|---|---|---|
| `friday_reconciled` | the exact real Sept-11 evidence (table above) | `screenshots/friday_reconciled.png` |
| `no_trades` | every lane flat — `0` is a valid, non-fabricated state | `screenshots/no_trades.png` |
| `open_position_missing_price` | an open position with no usable mark anywhere → `UNAVAILABLE`/`PARTIAL`, never a fabricated `$0`; reconciliation still `EXACT` (isolates the one variable) | `screenshots/open_position_missing_price.png` |
| `stale_post_close_valuation` | two open positions, two distinct valuation labels side by side: `STALE_HISTORICAL` (prior calendar day, age shown) vs. `POST_CLOSE` (same day, after 20:00Z) | `screenshots/stale_post_close_valuation.png` |
| `recovery_affected_closed_trades` | all 4 closed Experimental trades flagged, plain-language evidence banner, not pooled with a clean record | `screenshots/recovery_affected_closed_trades.png` |
| `reconciliation_mismatch` | BOTH required variants in one page: Experimental ledger file absent → lane `UNKNOWN`/reconciliation `UNAVAILABLE`; V2 cash deliberately inconsistent → reconciliation `MISMATCH` with the arithmetic shown | `screenshots/reconciliation_mismatch.png` |

Inspected for readability/clipping/table labels/timestamps directly (not
merely generated) — all six render cleanly at this viewport with no
overlapping or truncated text; two fixtures (`open_position_missing_price`,
`stale_post_close_valuation`) were caught with an internally-inconsistent
cash figure on first render (a fixture-authoring error, not a code defect
— the reconciliation check correctly flagged it as `MISMATCH`) and
corrected so each scenario isolates its one intended variable.

`spa/build_reconciliation_table.py` traces 27 displayed values back to
independently-stated expectations (not merely re-reading the same API
response the page rendered from) — `value_reconciliation.json` /
`value_reconciliation.md`, **27/27 match**.

## Production preservation

- `talonx_ops/paper_performance.py` opens every db `file:...?mode=ro` —
  physically cannot write.
- `test_never_writes_to_source_dbs` asserts file mtimes are unchanged
  across a full `build_paper_performance()` call against real-shaped
  fixture data.
- `test_no_network_import_side_effects` asserts the whole read path
  completes with `socket.socket` monkeypatched to raise.
- The real `~/.talonx` and repo-root `v2_lane.db` were opened **read-only**
  exactly once, at the start of this task, to confirm the exact live
  schema/values this module reads (documented above) — no write, no
  application process started or restarted.
- SPCX's outstanding obligation (stop $144.6133 / target $152.0633, open)
  and the closed-session's other final state are unchanged by this task —
  this task adds a read surface, it does not touch the session that
  Task 118H already closed.
- No production database, secret, or bulk private data is included in
  this commit — only source code, tests, and synthetic-fixture-derived
  screenshots/JSON (values are the real Sept-11 figures, reproduced from
  already-published research docs, not a raw db copy).

## Candidate activation / rollback

- **Exact code SHA**: this commit, on `hotfix/task119-paper-performance-dashboard`
  (parent `d4177b3`). **Not merged into `research/talonx-strategy-validation`
  in this task** — a reviewed candidate for the next session's operator to
  merge at preflight time, consistent with "not an automatic activation."
- **Migration requirement**: **none**. This is a pure read-only addition —
  no schema change, no new table, no write path. Merging it changes
  nothing about what any producer writes.
- **Rollback procedure**: revert the merge commit (or simply do not merge
  this branch) — `dashboard_read.py`'s `paper_eod()` and every other
  existing section are byte-unchanged; removing `paper_performance()` and
  the `paper_performance` tab reverts to the exact pre-Task-119 dashboard
  with zero other side effects.
- **Next-session verification**: after merging (if the operator elects
  to), `python -m talonx_ops.prospective preflight --expected-sha <new
  SHA>` should still show all 17 gates `[OK]` (no gate reads this
  surface); once the session is live, open `:8787#paper_performance` and
  confirm it agrees with the canonical EOD figures at close, exactly as
  the Friday reconciliation above does offline.
- **Known limitations**: PIV is always `NOT_CHECKED` (no network call
  performed by design); "last exit evaluation" is `NOT_TRACKED` for every
  open position (no dedicated exit-check log exists anywhere in the repo
  to read from — honestly labelled, not fabricated); the regular-session
  open boundary is approximated as close − 6h30m (correct for every
  actual NYSE session, including half-days, since NYSE never varies the
  9:30 ET open) rather than read per-day from `exchange_calendars`.

## Unresolved economic question and next research action

**Positive aggregate economics is still not established for any
live-scope lane** — this surface makes existing P&L legible and
attributable, it does not create profitability evidence; Experimental's
−$324.4662160270568 realized and SPCX's +$50.30 unrealized are both real,
both small-sample, and neither is treated as a track record.

One bounded next research action from the established programme (per
`docs/research/PRODUCT_REQUIREMENTS_AND_NEXT_DECISION.md`, Task 118E/F
protocol, not new strategy tuning): continue the pre-entry-volatility ×
net-return tracking already in progress for V2, now with this surface
available to read its realized/unrealized state consistently at every
future EOD without re-deriving it by hand.
