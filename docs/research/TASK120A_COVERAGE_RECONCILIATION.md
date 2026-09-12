# Task 120A A4 — six-name price-coverage reconciliation

**Task 120's own coverage check was wrong.** It checked only
`results/task95g_broad_cross_sectional/_daily` and concluded 6 of the 39
live-scope names had no price history, "notably MSTR." That is false: the
already-successful Task 118 Deliverable A baseline (`run_baseline_a.py`)
checks **two** bar directories (`_daily` **and**
`results/task107a_form4_feasibility/_prices`), and MSTR is one of 4 trades
in that baseline's own N=10 result (`MSTR −36.0%, 4 trades, all losses`).
Task 120 never consulted the second directory before excluding these
names.

Verified directly, this task, by listing both directories:

| symbol | `_daily` | `_prices` | valid interval (from `_prices`, where present) | missing eligible sessions | corporate-action basis | action needed |
|---|---|---|---|---|---|---|
| ABCL | absent | **present** | 2019-01-02 → recent | not separately audited this task (present, usable) | Alpaca SIP, `adjustment=all` (same as `_daily`) | none — already usable |
| ACHR | absent | **present** | 2019-01-02 → recent | not separately audited this task | same | none — already usable |
| ADC | absent | **present** | 2019-01-02 → recent | not separately audited this task | same | none — already usable |
| AGNC | absent | **present** | 2019-01-02 → recent | not separately audited this task | same | none — already usable |
| MSTR | absent | **present** | 2019-01-02 → recent | not separately audited this task | same | none — already usable |
| SHOP | absent | **absent** | none | entire history | n/a | genuinely missing — see below |

**Category for the 5 corrected names**: none of these are "before
listing," "missing ticker mapping," or "missing filing history" — they
are simply present in `_prices` and absent from `_daily` (two separately
built, overlapping bar-directory artifacts from different prior tasks;
`_prices` was built specifically for Task 107A's coverage needs and
evidently pulled a wider symbol set than Task 95G's own build did). This
is a **directory-selection bug in Task 120's script**, not a genuine data
gap.

**SHOP**: absent from both. Category: **missing price file** (Task 118
Deliverable A already found and documented this exact gap — "SHOP is
uncovered by either bar directory," carried forward unchanged, not
re-investigated tonight). No SHOP cluster has been detected as entering a
trade in any run to date regardless (per Task 118 Deliverable A), so this
gap has not silently dropped a would-be trade — it is recorded as a
labelled exclusion, never a fabricated bar.

## Retrieval considered, not needed

Per this task's own instruction ("if genuinely missing data can be
retrieved using existing free access... inspect the live composite-yf
tail adapter's range and source precedence first before assuming it
supports full-history research acquisition"): the 5 corrected names
needed **no retrieval at all** — the data already exists in `_prices`.
For SHOP specifically, retrieval was **not attempted** this task (out of
the stated time budget; SHOP has never produced a trade in any prior run,
so its absence does not affect any result computed here) — its status
stays **coverage incomplete, quantified as 1/39 names, 0 affected
episodes observed to date**, not silently expanded or fabricated.

## Correction to Task 120's own claim

Task 120's `TASK120_ECONOMIC_DECISION.md` stated: "6 of the 39 live-scope
names ... have no local historical price coverage ... MSTR is among
them ... no historical replay of the 39-name scope to date has been
fully representative." **This is superseded, not deleted** — see the
correction blockquote appended to that document. The corrected count is
**1 of 39 (SHOP)**, unchanged from what Task 118 Deliverable A already
established and documented eleven hours earlier in the same overnight
session.
