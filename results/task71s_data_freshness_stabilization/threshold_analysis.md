# 120-Second Stale Threshold -- Task 71S Analysis

## Question

Is `PivConfig.stale_seconds` (120s, i.e. tolerate one missed poll cycle
before flagging) suitable for all 35 symbols across premarket, regular
session, and postmarket?

## What the 2026-08-26 evidence actually covers

The session ran from ~06:31 ET (Task69R's authorized retry start) through
the 15:50 ET EOD flatten.

- **Premarket (06:31-09:30 ET, ~3 hours of polling):** zero STALE_DATA
  events fired. Every symbol produced a fresh bar at least once every two
  poll cycles throughout premarket that day.
- **Regular session (09:30 ET onward):** all 72 STALE_DATA events occurred
  here, spanning 09:32 ET through 15:28 ET. Every one was independently
  confirmed `CONFIRMED_NO_IEX_TRADE` (see `stale_event_timeline.csv`) --
  i.e. the threshold correctly detected genuine, real gaps; it produced
  **zero false positives** (no event was found to be a live-side miss)
  and, as far as this evidence can show, **zero false negatives** either
  (a symbol never silently sat on stale data without being flagged --
  every gap this task's forensic replay found in the historical record
  that met the >120s bar was also flagged live).
- **Postmarket:** the session's EOD flatten (15:50 ET) precedes the
  16:00 ET regular-session close and the process does not run into true
  postmarket hours at all -- there is no evidence either way for this
  window.

## Conclusion: retain the threshold, unchanged

The evidence does not support constructing a DIFFERENT threshold for
premarket vs. regular session vs. postmarket:

- Premarket: no data exists to show 120s is either too tight or too loose
  (zero events fired; introducing a looser premarket threshold would be
  pure speculation with nothing to validate it against).
- Regular session: 120s performed with a clean track record against real,
  independently-verified ground truth (100% of flags confirmed correct).
  There is no evidence of it being too sensitive (no confirmed false
  positive) or too lax (no confirmed missed/delayed detection).
- Postmarket: no operational data exists for this window under the current
  session-hours configuration.

Per this task's own instruction ("If the evidence does not support
relaxing the current readiness gate, retain fail-closed behaviour and
improve only classification, recovery and observability"), the same
principle is applied here: **`stale_seconds` stays at its current single
value of 120 for every symbol and every session window.** This task adds
richer classification, recovery, and observability (see
`talonx_piv/freshness.py`, `talonx_piv/gap_forensics.py`) without touching
the threshold itself, and without inventing an under-evidenced
session-aware scheme that the data does not justify.

## What WOULD justify revisiting this in a future task

- At least one confirmed case (via the same historical-archive
  cross-check this task built) of a genuine live-side miss during
  premarket or postmarket specifically, showing the threshold was too
  tight for that window's lower liquidity.
- At least one confirmed case of a stale flag lagging materially behind a
  real, actionable price move during regular-session hours, showing 120s
  is too loose for the strategy's own reaction-time requirements (a
  strategy-side concern, out of this task's scope regardless --
  `talonx_quant/strategy.py` was not touched).

Neither condition is present in the 2026-08-26 evidence.
