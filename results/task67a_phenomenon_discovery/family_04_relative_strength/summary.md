# Family 4 -- Relative Strength vs SPY / Sector ETF -- Stage 1 Screening Summary

Question: does stock-specific residual strength relative to market/sector predict subsequent continuation? A naive `stock_return - SPY_return` ("raw RS") is contaminated by beta; this family separates the two via a causal, fail-closed beta adjustment and treats the SPY-beta-ADJUSTED residual, not raw RS, as the verdict-relevant effect.

Data: DEVELOPMENT role, 35 symbols, 63 trading days (2026-05-15..2026-08-14; brief's nominal figure is ~62, actual observed unique days used throughout). Friction assumption: 5.0bps one-way / 10.0bps round-trip.

**Family rollup:** 0/3 PHENOMENON_PRESENT, 3/3 WEAK_SIGNAL, 0/3 PHENOMENON_NOT_OBSERVED, 0/3 INSUFFICIENT_DATA -- definitions are NOT averaged into one number; each is reported independently, per the brief. Verdicts are the BETA-ADJUSTED (SPY-adjusted) ones, not raw RS.

## Calibration / application calendar split

- Calibration half: 31 days (2026-05-15..2026-06-30)
- Application half: 32 days (2026-07-01..2026-08-14)
- Beta (`beta_spy`, `beta_sector`) is estimated ONCE, using ONLY calibration-half 1-min bars. ALL Family 4 candidate events (all 3 definitions) are restricted to the application half only.

## Beta estimation -- fail-closed summary

- Minimum paired 1-min return observations required: **2000** (~2 trading days of continuous 1-min bars at this dataset's ~900 bars/session pace).
- 35 symbols total. Failed closed on beta_spy: **0**. Failed closed on beta_sector: **0**. Failed closed on EITHER (excluded from beta-adjusted analysis): **0**.
- beta_spy (trustworthy symbols, n=35): median=0.891, range=[-0.183, 3.346]
- beta_sector (trustworthy symbols, n=35): median=0.910, range=[0.112, 1.715]

## Definition: `rs_trailing_30m`

RAW RS = causal 30m trailing stock return - causal 30m trailing SPY return, event fires when RAW RS is in the top/bottom 10% of pooled application-half values. Direction = sign(RAW RS). Application-half-only, excludes first 30m of RTH, >=15min lead before close.

- Dedup: group_keys=['symbol'], min_gap_minutes=15.0
- Raw events: 76987 -> Deduplicated events: 4093 (symbols=35, days=32)
- RS tail thresholds (application-half pool, n=678633): q_lo=-0.00578246034674904, q_hi=0.005676496993816119
- Trustworthy-beta subset used for beta adjustment: 4093 events, 35 symbols

### RAW RS (matched-control excess, before beta adjustment) -- reported, NOT the verdict basis

- Economic classification (raw): **ECONOMICALLY_TOO_SMALL**
- Data sufficiency: **ADEQUATE**
- Effect surface instability flagged: False (9 populated cells (n>=5): same_sign_frac=0.67 (overall sign=+), max|mean|/median|mean|=2.77.)
- MFE median (%, at max horizon): 0.56379202338692; MAE median (%): 0.555476410950458

| Horizon | n events | n matched pairs | raw mean % | matched control mean % | excess mean % | excess 95% CI |
|---|---|---|---|---|---|---|
| 15m | 4093 | 4078 | 0.0209 | -0.0103 | 0.0311 | [0.0081, 0.0562] |
| 30m | 4093 | 4078 | 0.0287 | -0.0276 | 0.0565 | [0.0163, 0.0998] |
| 60m | 4093 | 4078 | 0.0204 | -0.0116 | 0.0318 | [-0.0131, 0.0808] |
| 120m | 4093 | 4078 | 0.0242 | 0.0234 | 0.0012 | [-0.0457, 0.0505] |
- Raw-RS verdict (informational only): **WEAK_SIGNAL** -- Some structure present (3/6 early-kill checks passed) but 2/8 PHENOMENON_PRESENT requirements unmet -- breadth, magnitude, or certainty is too weak for a strong claim, but not weak enough to call this a clean non-observation.

### BETA-ADJUSTED residual (RAW / SPY-adjusted / sector-adjusted side by side) -- THE verdict basis

| Horizon | n | raw mean % [95% CI] | SPY-adjusted mean % [95% CI] | sector-adjusted mean % [95% CI] |
|---|---|---|---|---|
| 15m | 4093 | 0.0209 [0.0036, 0.0389] | 0.0157 [-0.0002, 0.0317] | 0.0108 [-0.0023, 0.0235] |
| 30m | 4093 | 0.0287 [0.006, 0.0522] | 0.0253 [0.0053, 0.0455] | 0.0146 [-0.0022, 0.031] |
| 60m | 4093 | 0.0204 [-0.0092, 0.0498] | 0.0264 [-0.0001, 0.0531] | 0.0154 [-0.0063, 0.0375] |
| 120m | 4093 | 0.0242 [-0.0073, 0.0559] | 0.0389 [0.0127, 0.0657] | 0.0239 [-0.0009, 0.0482] |

- Economic classification (SPY-adjusted, 60m primary horizon): **ECONOMICALLY_TOO_SMALL**

### VERDICT (beta-adjusted basis): **WEAK_SIGNAL**

Some structure present (3/6 early-kill checks passed) but 2/8 PHENOMENON_PRESENT requirements unmet -- breadth, magnitude, or certainty is too weak for a strong claim, but not weak enough to call this a clean non-observation.

## Definition: `rs_trailing_60m`

RAW RS = causal 60m trailing stock return - causal 60m trailing SPY return, event fires when RAW RS is in the top/bottom 10% of pooled application-half values. Direction = sign(RAW RS). Application-half-only, excludes first 30m of RTH, >=15min lead before close.

- Dedup: group_keys=['symbol'], min_gap_minutes=30.0
- Raw events: 82564 -> Deduplicated events: 2208 (symbols=35, days=32)
- RS tail thresholds (application-half pool, n=666645): q_lo=-0.008534478798994612, q_hi=0.008321857326403446
- Trustworthy-beta subset used for beta adjustment: 2208 events, 35 symbols

### RAW RS (matched-control excess, before beta adjustment) -- reported, NOT the verdict basis

- Economic classification (raw): **ECONOMICALLY_TOO_SMALL**
- Data sufficiency: **ADEQUATE**
- Effect surface instability flagged: False (9 populated cells (n>=5): same_sign_frac=0.67 (overall sign=+), max|mean|/median|mean|=2.26.)
- MFE median (%, at max horizon): 0.6128597483993994; MAE median (%): 0.5823889355975616

| Horizon | n events | n matched pairs | raw mean % | matched control mean % | excess mean % | excess 95% CI |
|---|---|---|---|---|---|---|
| 15m | 2208 | 2205 | 0.0413 | -0.022 | 0.0634 | [0.0272, 0.1003] |
| 30m | 2208 | 2205 | 0.0701 | -0.0302 | 0.1005 | [0.0371, 0.1685] |
| 60m | 2208 | 2205 | 0.0551 | 0.0137 | 0.0419 | [-0.0326, 0.1183] |
| 120m | 2208 | 2205 | 0.0595 | 0.064 | -0.004 | [-0.0946, 0.0876] |
- Raw-RS verdict (informational only): **WEAK_SIGNAL** -- Some structure present (3/6 early-kill checks passed) but 2/8 PHENOMENON_PRESENT requirements unmet -- breadth, magnitude, or certainty is too weak for a strong claim, but not weak enough to call this a clean non-observation.

### BETA-ADJUSTED residual (RAW / SPY-adjusted / sector-adjusted side by side) -- THE verdict basis

| Horizon | n | raw mean % [95% CI] | SPY-adjusted mean % [95% CI] | sector-adjusted mean % [95% CI] |
|---|---|---|---|---|
| 15m | 2208 | 0.0413 [0.0126, 0.071] | 0.0276 [0.0054, 0.0518] | 0.0204 [0.001, 0.0409] |
| 30m | 2208 | 0.0701 [0.0317, 0.108] | 0.0638 [0.0314, 0.0982] | 0.0429 [0.0153, 0.0719] |
| 60m | 2208 | 0.0551 [0.0142, 0.0974] | 0.0636 [0.0255, 0.1043] | 0.0423 [0.0081, 0.078] |
| 120m | 2208 | 0.0595 [0.0059, 0.1127] | 0.07 [0.0227, 0.1179] | 0.046 [0.0038, 0.0906] |

- Economic classification (SPY-adjusted, 60m primary horizon): **ECONOMICALLY_TOO_SMALL**

### VERDICT (beta-adjusted basis): **WEAK_SIGNAL**

Some structure present (4/6 early-kill checks passed) but 1/8 PHENOMENON_PRESENT requirements unmet -- breadth, magnitude, or certainty is too weak for a strong claim, but not weak enough to call this a clean non-observation.

## Definition: `rs_trailing_90m`

RAW RS = causal 90m trailing stock return - causal 90m trailing SPY return, event fires when RAW RS is in the top/bottom 10% of pooled application-half values. Direction = sign(RAW RS). Application-half-only, excludes first 30m of RTH, >=15min lead before close.

- Dedup: group_keys=['symbol'], min_gap_minutes=45.0
- Raw events: 86470 -> Deduplicated events: 1652 (symbols=35, days=32)
- RS tail thresholds (application-half pool, n=655074): q_lo=-0.010881938590922772, q_hi=0.010631297925694424
- Trustworthy-beta subset used for beta adjustment: 1652 events, 35 symbols

### RAW RS (matched-control excess, before beta adjustment) -- reported, NOT the verdict basis

- Economic classification (raw): **ECONOMICALLY_TOO_SMALL**
- Data sufficiency: **ADEQUATE**
- Effect surface instability flagged: True (9 populated cells (n>=5): same_sign_frac=0.78 (overall sign=+), max|mean|/median|mean|=4.40.)
- MFE median (%, at max horizon): 0.6582682859772695; MAE median (%): 0.6099095588987783

| Horizon | n events | n matched pairs | raw mean % | matched control mean % | excess mean % | excess 95% CI |
|---|---|---|---|---|---|---|
| 15m | 1652 | 1650 | 0.0312 | -0.0061 | 0.0374 | [-0.0038, 0.0800] |
| 30m | 1652 | 1650 | 0.0704 | -0.0266 | 0.097 | [0.0468, 0.1492] |
| 60m | 1652 | 1650 | 0.0739 | 0.0085 | 0.0657 | [-0.0132, 0.1497] |
| 120m | 1652 | 1650 | 0.0755 | 0.0016 | 0.0742 | [-0.0221, 0.1841] |
- Raw-RS verdict (informational only): **PHENOMENON_NOT_OBSERVED** -- 4/6 early-kill checks failed (near-zero/incoherent excess effect, unstable effect surface, non-asymmetric MFE/MAE, high concentration, or a clustered-bootstrap CI for excess that straddles zero) -- most of the early-kill checklist holds, so this definition is treated as PHENOMENON_NOT_OBSERVED rather than cherry-picked into a weaker positive verdict.

### BETA-ADJUSTED residual (RAW / SPY-adjusted / sector-adjusted side by side) -- THE verdict basis

| Horizon | n | raw mean % [95% CI] | SPY-adjusted mean % [95% CI] | sector-adjusted mean % [95% CI] |
|---|---|---|---|---|
| 15m | 1652 | 0.0312 [-0.0017, 0.0635] | 0.028 [-0.0045, 0.0595] | 0.0162 [-0.0086, 0.0409] |
| 30m | 1652 | 0.0704 [0.0298, 0.1119] | 0.074 [0.0323, 0.1165] | 0.0463 [0.0123, 0.0801] |
| 60m | 1652 | 0.0739 [0.0196, 0.1322] | 0.0838 [0.027, 0.1436] | 0.0561 [0.0108, 0.1033] |
| 120m | 1652 | 0.0755 [0.0137, 0.1391] | 0.096 [0.031, 0.1625] | 0.0633 [0.0108, 0.1161] |

- Economic classification (SPY-adjusted, 60m primary horizon): **ECONOMICALLY_TOO_SMALL**

### VERDICT (beta-adjusted basis): **WEAK_SIGNAL**

Some structure present (3/6 early-kill checks passed) but 2/8 PHENOMENON_PRESENT requirements unmet -- breadth, magnitude, or certainty is too weak for a strong claim, but not weak enough to call this a clean non-observation.
