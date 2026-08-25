# Task72 Part 5-7 -- Frozen Strategy: IDIOSYNCRATIC_RESIDUAL_MOMENTUM_LONG_V1

**Fingerprint:** `f3764b6794f2e00cc5262f73d241b5274ebf544dd65cc96e7a7ab175d7c6025a`
Source: `research/task72_residual_momentum/contracts.py` -> `fingerprint.py::compute_fingerprint()`.
Any semantic change to the contract after this point changes the hash; this
strategy must not be modified past this commit -- a new version (V2) would
be required instead.

## Signal

At 11:00 ET: `residual = stock_return(09:30->11:00) - beta_20d * SPY_return(09:30->11:00)`.
Beta is a causal trailing-20-trading-day OLS beta, strictly excluding the
current day (`research/task71_lib/features.py::causal_rolling_beta`, reused
unmodified). LONG fires when `residual >= 0.75%`. No SHORT side (Task71's
SHORT mirror failed cleanly and was rejected).

## Entry

First 1-minute bar OPEN strictly after the 11:00 ET decision timestamp.

## Stop

2.5% below the simulated entry price. Checked starting from the bar
strictly after entry ("first subsequent 1m bar"). If that bar's LOW
breaches the stop: fill at the stop price, UNLESS the bar's own OPEN
already gapped below the stop, in which case fill at that OPEN (never a
better fill than the bar itself permits). No trailing stop, no
take-profit target.

## Exit

Whichever occurs first: STOP, or TIME_EXIT at a fixed 180-minute horizon
(bounded by 16:00 ET session close -- no overnight holding ever).

## Freeze rationale (Parts 2-4, no development P&L was optimized to pick these)

- **Threshold = 0.75%** (not 1.50%): chosen for breadth/parameter
  stability/less selection pressure. Task71 development: 0.75% -> 217
  trades/35 symbols/26 days; 1.50% -> 93 trades/31 symbols/22 days. ALL 8
  of Task71's own predeclared cells (both bands x 4 horizons) were
  positive -- this is picking the broader of two already-positive cells,
  not searching for the best one.
- **Horizon = 180 minutes** (not EOD): both are in the same broad positive
  plateau in Task71's `family_c_residual_momentum_summary.csv` at
  threshold=0.75% (EOD net_10bps=0.1265%/PF=1.314; 180m
  net_10bps=0.1302%/PF=1.390 -- nearly identical, same 217/35/26
  population). 180m is preferred for a STRUCTURAL reason: a fixed
  180-minute hold is deterministic, independent of the closing-auction
  mechanism, and creates no ambiguity for offline/live parity or slippage
  measurement. Day-cluster ci_low is marginally worse for 180m (-0.142 vs
  -0.120) and top1_day_share marginally higher (0.224 vs 0.155) -- judged
  NOT a material robustness disadvantage since both remain inside the same
  broad positive plateau with symbol-cluster CIs excluding zero and stable
  signs across all 3 Task71 regimes/segments.
- **Stop = 2.5%**: Task71's `risk_stop_diagnostics.csv` 90th-percentile MAE
  for the primary cell is ~2.19%; 2.5% is a conservative rounded buffer
  above that observed DEVELOPMENT distribution, chosen as catastrophic
  risk containment, NOT searched/optimized against any P&L (no stop grid
  was run).
- **No development P&L optimization was performed at freeze time.** Every
  parameter above was read directly from already-existing Task71 artifacts;
  Task71's discovery grid was not rerun.

## Runtime

`research/talonx-strategy-validation` was not touched by this freeze.
