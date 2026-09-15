# TalonX Operational Findings Tracker

**Created**: 2026-09-15, during the Session 2 documentation pass
(`DECISION_LOG.md` Session 2). This is the first entry in this file —
no prior operational-issue tracker existed in this repository at the
product-experience layer. It is a **separate domain** from the other
trackers in this repository:

- `REQUIREMENTS_TRACKER.md` — product-experience **requirements**
  (what the product should do, agreed with the owner).
- `docs/research/TALONX_OWNER_DECISIONS.md` — Original's
  strategy-tuning parameters specifically.
- `docs/research/TALONX_RESEARCH_LEDGER.md` — the append-only
  chronological history of every research/validation task.
- **This file** — operational/runtime **findings**: things discovered
  during live inspection, EOD closures, or reviews that describe a gap
  or risk in the running system's own operational behavior (not a
  product-direction decision, and not a research-alpha finding).

Same discipline as the other trackers: append-only, stable IDs
(`OPS-<sequence>`), never silently edited — a later update adds a
dated note under the original entry.

---

## OPS-001 — EOD Closure 2026-09-15: review/correction note

**Status**: `CLOSED` (documentation review only — no code/runtime
issue; this is a scope-qualification note, not a defect).

**Raw report**: `docs/research/evidence/eod_closure_2026-09-15/
EOD_CLOSURE_REPORT.md` (preserved as originally written — this entry
does not edit it, it appends a linked review note to the report itself
and indexes that note here).

**Review note** (recorded 2026-09-15, Session 2 documentation pass):
the original EOD closure report is accurate as a timestamped,
evidenced record of what was inspected, reconciled, and shut down on
2026-09-15 — it is **not** re-litigated here. What this note adds is a
scope qualification that the original report did not itself state
explicitly:

> **EOD accounting and controlled shutdown were supported by the
> report. This does not establish readiness for current-session V2
> paper execution.** A clean EOD reconciliation (zero mismatches among
> checked components, a graceful shutdown with zero residual
> processes) demonstrates that the accounting and process lifecycle
> are sound as of that closure. It does not, by itself, demonstrate
> that V2 is currently able to correctly price and execute a fresh
> opportunity — see `OPS-002` below, found during this same
> documentation pass, for the specific gap this qualification refers
> to.

This qualification has also been appended directly to
`EOD_CLOSURE_REPORT.md` (a new §8, dated and linked back to this
entry) so a reader of that report alone sees the same caveat.

**Evidence references**: `docs/research/evidence/eod_closure_2026-09-15/
EOD_CLOSURE_REPORT.md` §8 (Review note, Session 2 pass).

---

## OPS-002 — V2 current-price availability and freshness reporting incomplete

**Status**: `OPEN` — implementation requires a separately authorized
corrective task. Not implemented, not fixed, not worked around by this
documentation pass.

**Found**: 2026-09-15, first during the EOD closure task (same-day),
re-reviewed and formally tracked during the Session 2 documentation
pass.

**Reported evidence** (from `EOD_CLOSURE_REPORT.md` §4, re-verified by
targeted code re-reading this pass, not re-run):

- Runtime pricing mode was `csv` (`talonx_v2/service.py`,
  `V2Service.__init__`).
- In `pricing_mode == "csv"`, `self._resolver` is **never constructed**
  (`if pricing_mode != "csv": self._resolver = _pricing.make_resolver
  (...)`) — the price-validation/freshness-tracking resolver object
  simply does not exist in this mode.
- The `pricing_adapter` status field's `"csv:frozen_bar_dirs"` value is
  a **hardcoded fallback string**, not a real registered adapter's own
  name — it is emitted whenever `self._resolver` is `None`.
- `pricing_unavailable_recent` reads from `self._resolver.last`, which
  doesn't exist in this mode — the field is **structurally always
  empty**, not "checked and found healthy."
- The actual default bar directory in use (no `--bar-dir` override in
  the live launch argv, confirmed via `session.pids.json`) —
  `results/task95g_broad_cross_sectional/_daily/` — has its latest
  usable row (`AAPL.csv`) dated **2026-08-14**, roughly 22 trading days
  stale relative to the 2026-09-15 EOD closure date.
- `CsvBarAdapter.session(symbol, date)` returns `None` (not a stale or
  incorrect substitute price) for a date it doesn't have — confirmed by
  direct code reading, not assumed.

**Distinction clarified in this pass** (per this task's own
instruction not to overstate what was established): **this does not
mean V2 performs no price lookup.** `CsvBarAdapter.session()` is the
actual fill/valuation lookup the entry/exit code paths use — it is a
real, functioning lookup against the configured bar directory, and it
fails safely (returns `None`, never a stale/wrong number) when a date
is missing. What is missing is the **separate diagnostic resolver/
freshness-tracker** object (`self._resolver`) that the `"csv"` mode
never constructs — so the *operational visibility* into staleness
(the `pricing_unavailable_recent` telemetry field) is absent, even
though the underlying lookup mechanism itself exists and behaves
safely. **Configured vs. fallback path**: the `"csv:frozen_bar_dirs"`
label is a fallback string used only for status display, not a sign
that the wrong data source is being read — the actual data source
(`results/task95g_broad_cross_sectional/_daily/`) is the one genuinely
in use, confirmed via the live launch argv, and it genuinely is stale.

**Explicit implications** (as instructed, none silently assumed away):

- Missing-price handling may correctly prevent an invented fill, but
  it may equally prevent a valid, currently-qualifying opportunity
  from entering or being valued — a safe failure mode, but not a free
  one.
- Execution scope count (`execution_scope_count: 626`,
  `EOD_CLOSURE_REPORT.md` §4) is not the same claim as price coverage
  for those 626 symbols on the current session date.
- GATED admission (`durable_store_gate_enabled: true`) is an admission
  gate, not a pricing-readiness gate — the two are independent.
- Zero trades in the current campaign does not prove zero qualifying
  opportunities existed — it is also consistent with a stale-price
  rejection having silently occurred (fails safe, but not
  distinguishable from "no qualifying opportunity" in the telemetry
  currently available).
- Zero trades does not prove price lookup was never attempted — the
  lookup mechanism runs regardless; only its *diagnostic visibility* is
  what's missing.
- Empty freshness telemetry (`pricing_unavailable_recent: []`) must
  not be read as "prices are fresh and healthy" — it is structurally
  empty in this mode regardless of actual price condition.

**Future corrective work — NOT IMPLEMENTED here, requires a separately
authorized task**:

1. Trace the authoritative V2 entry/exit/valuation price paths
   end-to-end (beyond `CsvBarAdapter.session()` alone).
2. Verify configured paths, symbol coverage, and usable date ranges
   against the live watchlist.
3. Restore a supported current-price path using authorized existing
   sources (no new paid data, no unapproved provider).
4. Preserve and disclose reference-price/provisional-bar semantics —
   do not silently mask a stale mark as current.
5. Test current-session, missing, provisional, and stale-price
   behavior explicitly (isolated tests, not live trading).
6. Expose price readiness independently from process/ingestion health
   in the dashboard/status surfaces (distinct from S2-12's dashboard-
   presentation requirement, though related — S2-12 is about how a
   missing valuation is *shown*; this item is about the upstream
   *data* the display would draw from).
7. Reconcile "strategy rejected the opportunity" vs. "price was
   unavailable" as distinguishable rejection reasons, not conflated.

**Acceptance criteria** (for the future corrective task, not met by
this documentation pass):

- Relevant price coverage and dates are visible (not structurally
  empty).
- A current target-session request behaves under an explicit, declared
  policy (not an undocumented `None`-on-miss with no visibility).
- Missing/provisional data yields an explicit disposition, not silence.
- Stale or absent telemetry cannot produce a misleading "healthy"
  verdict.
- No silent provider/strategy change, and no fabricated fill, at any
  point in the fix.

**Explicitly out of scope for this entry**: no provider was changed,
no data was downloaded or refreshed, no path was repaired, and no code
was modified to produce this finding — it is a disclosed, tracked gap
only, per this documentation task's own restrictions.

**Evidence references**: `talonx_v2/service.py` (`V2Service.__init__`,
the `pricing_mode != "csv"` conditional); `talonx_v2/pricing.py`
(`CsvBarAdapter.session`); `results/task95g_broad_cross_sectional/
_daily/AAPL.csv` (last row date); `docs/research/evidence/
eod_closure_2026-09-15/EOD_CLOSURE_REPORT.md` §4 (original finding).

**Related but distinct**: `REQUIREMENTS_TRACKER.md` `S2-12`
(dashboard presentation of missing/stale valuations — a display-layer
requirement) and `S2-06`/`S2-05` (live-vs-replay parity) both touch
adjacent ground but do not resolve this upstream data-freshness gap.

---

*See `REQUIREMENTS_TRACKER.md` for product-requirement tracking,
`DECISION_LOG.md` for the session-by-session product-owner record, and
`docs/research/TALONX_RESEARCH_LEDGER.md` for the research/validation
task history. This file tracks operational/runtime findings only.*
