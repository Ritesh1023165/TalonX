# Task 71S-R1 -- Phase A: Evidence-Quality Audit

## 1-2. Branch/HEAD/clean status; full diff reviewed

- Branch: `research/talonx-strategy-validation`
- Starting HEAD: `d1764a8` (confirmed clean via `git status --short` before
  any edit).
- Full diff `54ae8ff..d1764a8` reviewed (`git diff 54ae8ff..d1764a8 --stat`):
  18 files changed -- 13 evidence/results/test artifacts plus exactly the 4
  runtime files Task 71S's own spec named
  (`talonx_piv/{freshness.py,gap_forensics.py,session_runner.py,events.py}`).
  No file outside `talonx_piv/`, `tests/`, and `results/` appears.

## 3-4. What evidence actually supported `CONFIRMED_NO_IEX_TRADE`

Inspected `gap_classification_evidence.csv` and
`talonx_piv/gap_forensics.py` directly.

**`gap_classification_evidence.csv`** only records two columns of
substance: `gap_type` and `classification` -- it carries no reference to
any trade-level data source at all.

**`gap_forensics.py`'s actual mechanism**
(`fetch_historical_minute_set` -> `_request_page`/`_parse_bars_page`,
reused from `alpaca_historical_warmup.py`) calls exactly one Alpaca
endpoint: `GET /v2/stocks/{symbol}/bars?timeframe=1Min` -- Alpaca's
**aggregate 1-minute BAR** endpoint. `classify_missing_minute` and
`classify_stale_event` then do nothing more sophisticated than: "is this
ET minute label present in the set of minutes that had an aggregate bar?"

**Verdict: the evidence was aggregate-bar absence ONLY.** Specifically:

- ❌ No trade-level IEX records were ever queried. Alpaca's separate
  `GET /v2/stocks/{symbol}/trades` endpoint (raw, tick-level prints) is
  never called anywhere in `gap_forensics.py` or
  `alpaca_historical_warmup.py`.
- ❌ No Alpaca-documented aggregation semantics were consulted or cited
  anywhere in the prior task's code, tests, or artifacts (no reference to
  Alpaca's own docs on what causes a 1-minute bar to be emitted or
  suppressed -- e.g. minimum trade conditions, odd-lot handling, or
  auction-cross treatment).
- ❌ Not "some combination" -- it was the single aggregate-bar-absence
  signal, presented as if it were stronger.

**The label `CONFIRMED_NO_IEX_TRADE` was an overclaim.** "Confirmed... no
trade" asserts trade-level verification that was never performed. What was
actually and legitimately established is narrower but still meaningful:
*the same aggregation Alpaca's IEX bar endpoint applies produced no bar for
that symbol/minute* -- a real, useful, and (per Phase B's coverage
analysis) internally consistent signal, but not a trade-level proof.

## 5. Correction applied

`CONFIRMED_NO_IEX_TRADE` is renamed, throughout `talonx_piv/gap_forensics.py`,
`talonx_piv/freshness.py`'s docstring, and
`tests/test_task71s_data_freshness_stabilization.py`, to
**`NO_IEX_BAR_OBSERVED`** -- an honest label that claims exactly what the
evidence supports (aggregate-bar absence) and nothing more. The
UNDERLYING LOGIC is unchanged (still: "neither of the two most-recent
minutes has a historical bar" for stale events; "the minute is absent from
the historical set" for missing opening minutes) -- only the name was
corrected, since the classification itself was never wrong, only
overstated.

The original `results/task71s_data_freshness_stabilization/` artifacts
(committed under `d1764a8`) are left untouched as a historical record of
what was concluded at the time, rather than silently rewritten -- this
audit, plus the corrected terminology in the code every future run will
use, is the transparent correction. Nothing in this repository still
claims trade-level confirmation for any 2026-08-26 gap.

## 6. Stale-exclusion guard cannot alter alpha except by preventing evaluation on unsafe data

See `stale_guard_path_audit.md` for the full trace. Summary: the guard
added in `session_runner.py`'s `process_tick`
(`decision_eligible = {s for s in decision_eligible if
self._freshness.state_of(s) not in (STALE, DATA_GAP)}`) is a pure **set
intersection/filter** -- it can only REMOVE a symbol from
`decision_eligible`, never add one, never reorder scoring, never change a
threshold. `talonx_quant/strategy.py` (candidate generation/scoring) is
never imported by this guard or anywhere in `talonx_piv/freshness.py` /
`gap_forensics.py`. The only way this guard can affect what happens to a
symbol is: EITHER it is included (in which case the symbol's actual bar
data flows to `decision_engine.on_bars` completely unmodified, exactly as
before this guard existed) OR it is excluded (in which case NOTHING about
that symbol reaches the strategy this tick). There is no third path.

## 7. `DATA_RECOVERED` cannot re-enable evaluation until existing readiness requirements are satisfied

`DATA_RECOVERED` fires from `FreshnessTracker.observe_fresh`'s `recovered`
return value, called only when a genuinely NEW bar (later timestamp than
previously seen) has just been recorded in `new_bars` this tick (see
`process_tick`). Clearing a symbol's STALE/DATA_GAP freshness state does
**not** bypass either of the two pre-existing, unmodified gates a symbol
must ALSO satisfy before `on_bars` ever sees it:

1. `symbol in self._ready_symbols` -- the 09:30-09:59 opening-window
   completeness gate (`readiness.py`, untouched by any Task 71S/71S-R1
   commit).
2. `symbol in self.decision_engine.warmup_ready_symbols` -- the historical
   1-minute-history gate (`warmup.py`, untouched).

A symbol whose freshness recovers but that never passed gate 1 (e.g. REGN,
which never entered `_ready_symbols` at all on 2026-08-26) still can never
reach `on_bars`, regardless of `DATA_RECOVERED` firing for it -- confirmed
directly by `test_integration_no_candidate_from_repeatedly_monitored_not_ready_symbol`
in this task's own new test file.

## 8. Unrelated decision/order behaviour introduced by Task 71S?

None found -- **NOT BLOCKED**. `talonx_piv/decision_engine.py`'s
`on_bars`, `talonx_piv/broker.py`, and `talonx_piv/lifecycle.py` do not
appear anywhere in the `54ae8ff..d1764a8` diff. Proceeding to Phase B/C/D.
