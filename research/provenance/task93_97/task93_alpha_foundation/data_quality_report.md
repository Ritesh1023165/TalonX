# TASK 93 — Phase 3: Data Quality Audit

Audited: `results/task93_alpha_foundation/_canonical_data/` — 35 symbols, 4,468,726 1-minute bars,
2025-01-24 → 2026-08-14. Method: (a) per-file structural probe (pandas), (b) the backtest engine's own
`talonx_backtest.data.check_data_quality` checks (Requirement-18 set), (c) targeted scans for
corporate-action discontinuities, stale/repeated bars, look-ahead risk, warmup sufficiency. The engine
also writes `baseline_data_quality.json` as part of the Phase-5 replay (cross-check on completion).

## Structural checks — all PASS

| Check | Result across all 35 symbols / 4.47M bars | Class |
|---|---|---|
| Duplicate timestamps | **0** | PASS |
| Out-of-order timestamps (in-file order) | **0** (every file monotonic increasing) | PASS |
| NaN values (OHLCV) | **0** | PASS |
| Infinite values | **0** | PASS |
| Non-positive price (any of O/H/L/C ≤ 0) | **0** | PASS |
| Negative volume | **0** | PASS |
| Invalid OHLC relationship (`high<low`, `open`/`close` outside `[low,high]`) | **0** | PASS |
| Timezone | tz-aware UTC everywhere; session logic in `America/New_York` | EXPECTED |
| Bar interval | 1-minute inferred everywhere | EXPECTED |

## Issues found

### 1. Intra-day missing minutes — `EXPECTED`
~218,117 gaps > 2 min that are not overnight/weekend, across 35 symbols over 18.7 months (~6.2k per
symbol; heavily weighted to thin names and pre/after-hours). Alpaca emits **no bar for a minute with
zero trades** — there are **0 zero-volume bars** precisely because empty minutes are omitted rather
than zero-filled. Identical to the pattern Task 26 documented ("3,906–4,775 unexpected gaps/symbol")
and deferred. The frozen strategy consumes bars as an event stream and its buffers are gap-tolerant
(continuous ATR across session boundaries by 2026-08-16 design — Task 38). **No action; not a defect.**

### 2. AMD 2025-10-06 12:07 UTC — single bad pre-market print — `MINOR`
| bar (UTC) | open | high | low | close |
|---|---|---|---|---|
| 12:06 | 211.72 | 211.81 | 210.04 | 211.76 |
| **12:07** | 211.76 | 213.64 | **165.00** | **165.30** |
| 12:08 | 213.60 | 215.10 | 213.52 | 215.06 |

`low` and `close` on the 12:07 bar (~$165) are erroneous against a ~$212 context; `open` and `high`
are consistent with neighbours. This is 08:07 ET **pre-market** on the day of the real AMD–OpenAI news
move (AMD genuinely ran ~$208→$227 that session — that part is legitimate). A single erroneous
low/close.
- **Impact on this study:** negligible. (a) Pre-market bars face `PREMARKET_LIQUIDITY` / session gates.
  (b) The frozen strategy publishes ≈0 signals regardless. (c) There is no trade population for it to
  contaminate. A spurious −22 %/+30 % pair could transiently inflate 1-min ATR(14) for ≤14 bars and
  could spawn one spurious pre-market candidate on AMD on 2025-10-06 — if any Phase-7 candidate/signal
  anchors to this exact bar it will be flagged and excluded from counterfactual analysis.
- **Action:** documented here; **data not modified** (no silent cleaning). Recorded so downstream
  phases can special-case it if needed.

### 3. Corporate-action discontinuities — `EXPECTED` / none material
Scan for |1-min close move| > 25 %: exactly **one** hit — the AMD bad print above. No split-shaped
~50 % single-bar step in any of the 35 symbols over the window. Prices are UNADJUSTED, so any real
split *would* show; none did (none of the 35 split in 2025-01 → 2026-08 within the covered ranges).
Dividends on 1-min bars are sub-tick and immaterial to an intraday R-multiple strategy.

### 4. Stale / repeated bars — `MINOR` / `EXPECTED`
Flat bars (`O==H==L==C`) occur in thin pre/after-hours minutes (a single print repeated as the bar).
This is normal low-liquidity behaviour, concentrated outside the regular session, and the strategy's
own `PREMARKET_LIQUIDITY` gate + session gates handle it. Not separately quantified per-symbol here;
no evidence of long runs of identical bars inside the regular session.

### 5. Look-ahead contamination — `PASS` (by construction)
The `talonx_backtest` engine evaluates only **closed** bars, fills on the **next** bar's open, and
computes indicators from the trailing buffer only (`docs/backtesting.md`; engine module docstring; the
31-test reproducibility suite + Task 25A/26 look-ahead tests). Task 93 introduces **no** engine change,
so no new look-ahead path. The dataset itself carries no future columns.

### 6. Survivorship — `MATERIAL_NONBLOCKING`
Individual-security backtest over a fixed 35-name list chosen for liquidity as of 2026, not a
point-in-time universe. Over an 18.7-month window the bias is modest but real (no delisted/acquired
names, no 2025 IPO that later failed). The engine prints this disclaimer in every summary. Carried
into the Phase 13 verdict as a caveat, not a blocker.

### 7. Warmup / pre-roll sufficiency — `PASS`
The strategy needs ~120 1-min bars + completed 15-min and 60-min buffers before it evaluates a symbol
(Task 38/44). Segment A starts 2025-01-24 with full extended-hours coverage; every symbol has
thousands of bars before the first regular session it could act on. Task 74S separately confirmed HTF
warmup is immaterial over a multi-month window. Phase 5's replay is a single chronological pass with
no synthetic pre-roll — the first ~1 session per symbol is warmup and simply produces no gate
evaluation (correct, matches live `run_talonx.py` startup preseed semantics).

## Classification summary

| Issue | Class |
|---|---|
| Structural checks (dupes / ordering / NaN / Inf / prices / volume / OHLC) | all **PASS** |
| Intra-day missing minutes (~218k) | **EXPECTED** |
| AMD 2025-10-06 12:07 UTC bad print | **MINOR** (documented; data unchanged) |
| Corporate-action discontinuities | **EXPECTED** (none material) |
| Stale/flat pre/post-market bars | **MINOR / EXPECTED** |
| Look-ahead | **PASS** |
| Survivorship | **MATERIAL_NONBLOCKING** (caveat in verdict) |
| Warmup sufficiency | **PASS** |

**No `BLOCKING` issue.** The dataset supports meaningful research. `TASK93_BLOCKED_DATA_OR_ENGINE` is
**not** returned on data-quality grounds. Nothing was silently cleaned; the one `MINOR` bad print is
recorded above with the data left as-is.
