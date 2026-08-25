# F6_FADE_V1 — Frozen Spec

Machine-readable source of truth: `f6_fade_v1_spec.json`. Fingerprint: `f6_fade_v1_fingerprint.json`. Derived from Task 67B's `family_06_opening_later` discovery (source SHA `926fb01d6992684d67ca70a2c5cf5a678be2bf92`).

## Rule, in one paragraph

At 14:00:00 UTC (10:00 ET / 15:00 BST, both DST-active on 2026-08-25) each trading day, for each of the 35 universe symbols: compute `opening_return = (window_close - window_open) / window_open` over the completed 13:30–14:00 UTC opening window (requires ≥20 of the nominal 30 bars, else `DATA_NOT_READY`). If `|opening_return| >= 0.013391316345271645` (the frozen DEVELOPMENT top-tertile cutoff — never recomputed live), fade it: go SHORT if the open was up, LONG if the open was down. Enter at the **next** bar's open after the decision bar (never the decision bar's own price — no same-bar lookahead). Exit 60 minutes later at that bar's close, capped at RTH close (20:00 UTC) if needed. No stop-loss (none was established in discovery). One trade per symbol per session, no pyramiding, no overnight.

## Why this definition, this direction, this exit

- **Definition A (`opening_return_magnitude`)** was selected over B (SPY-relative) and C (volume-based) for simplicity (no cross-asset or leave-one-day-out dependency) and because it had the marginally larger, equally CI-clean 60m excess in Task 67B's own comparison — not because a new sweep found it "best."
- **Direction is a fade**, the *opposite* of Family 6's original "continuation" hypothesis — Task 67B's own pooled, direction-adjusted excess was coherently negative across all 4 horizons (CI excludes zero at 15m/60m/120m).
- **60-minute exit**, not 120m: both horizons were discovery-consistent (CI excludes zero either way); 60m is chosen for shorter/simpler market exposure, explicitly *not* because it had the better raw number — 120m's raw magnitude was nominally larger.
- **No stop, no risk-based sizing**: Task 67B never tested or validated a stop-loss or risk unit, so none is invented here.

## What changed vs. the Task 67B screening (deliberately, for causal safety)

The screening used the decision bar's own close as `entry_price` (a same-bar convenience). Per Task 68A's explicit requirement, F6_FADE_V1 instead enters at the **next** bar's open — one minute more conservative, verified on DEVELOPMENT data to produce the same 735-trade count (no bars were lost to this extra delay in practice).

## Full field-by-field detail

See `f6_fade_v1_spec.json`. Key fields: `signal_threshold`, `signal_direction_semantics`, `entry_rule`/`entry_price_semantics`, `exit_rule`, `stop_rule`, `sizing_rule`, `data_readiness_rule`/`missing_data_rule`, `primary_cost_bps`/`diagnostic_cost_bps`.

## Status

**FROZEN** as of fingerprint `6beb8eebe50053aae27cab90226534b5d4392c46bd6e9c094873f7ad37466084`. Not validated. Not deployed. Alpha status: UNPROVEN.
