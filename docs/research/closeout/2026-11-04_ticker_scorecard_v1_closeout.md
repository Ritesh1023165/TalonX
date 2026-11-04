# TICKER_SCORECARD_V1 Closeout (2026-11-04)

Full write-up (editable): https://claude.ai/artifact/NVUYhkf18DQVDHuBVoJf8u

## Verdict

No horizon passed. Pre-registered action: close the scorecard lane; TalonX stays a descriptive Risk and Event Intelligence
product; no variants of this study. Single pass, final, nothing re-run or re-cut after HOLDOUT was read. No leakage audit is
required because nothing passed.

## HOLDOUT results (2025-01-02 to 2026-06-30, read once)

| Horizon | Composite | Outcome | Gates passed | Mean rank IC | IC lower 95% | Top decile excess | Bottom decile excess | Positive months | Beat-SPY rate bull / bear | Calibration error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1D | RIDGE | FAIL_NO_VALUE | G1, G4 | 0.0162 | 0.0012 | -2 bp | -5 bp | 78% | 50.0% / 47.6% | 0.5 pt |
| 1W | RIDGE | FAIL | G3 | 0.0088 | -0.0195 | -12 bp | -28 bp | 56% | 48.9% / 48.0% | 1.8 pt |
| 1M | EQ | FAIL | none | 0.0165 | -0.0269 | +19 bp | +33 bp | 67% | 48.8% / 47.9% | 2.0 pt |
| 3M | EQ | FAIL | G2 | 0.0519 | -0.0223 | +66 bp | +163 bp | 56% | 48.3% / 43.2% | 3.0 pt |

- 1D: real but tiny ranking skill; the top decile does not clear the 20 bp cost hurdle.
- 1W: G3 passed because both deciles lagged SPY (a level effect), not because of skill.
- 1M, 3M: positive IC but wide error bars (78 weekly rank dates; about six independent 3-month windows), and the bottom decile
  out-earned the top, so a Bearish call would have lost money.

## Record

| Step | Code | Result file |
| --- | --- | --- |
| Freeze | 3d55f85 | results/scorecard_v1/freeze/freeze.json |
| Fit (TRAIN) | d2053e8 | results/scorecard_v1/fit/fit.json |
| Validate | 8d4714b | results/scorecard_v1/validate/choice.json |
| Holdout | 1ab024f | results/scorecard_v1/holdout/verdict.json |

Panel sha256 f392ea89c468f3d2c03e23f15774784fa9479dab9fde66c7bf203a23092b457c. Spec fingerprint 81ddf67e19cf. Seven amendments are in
`docs/research/preregistration/2026-11-04_amendment_1_gate1_scope.md`.

## Limitations

- Survivorship bias: the symbol list is SEC's current ticker file, so companies delisted since 2019 are missing. This may overstate the
  positive 1M and 3M IC; it does not weaken the negative verdict.
- Short HOLDOUT, so little power at 1M and 3M.
- F11 (risk-factor change) not built; V1 ran with 11 live features (Amendment 6).
- Gross profitability exists for 42% of universe-days; insider data is blank after 2026 Q3.
- Filing times are assumed to be after the 16:00 ET cutoff on the filing date (conservative).
- Sector-ETF IC, next-open returns and the S&P 500 subset were not produced (never decisive).
