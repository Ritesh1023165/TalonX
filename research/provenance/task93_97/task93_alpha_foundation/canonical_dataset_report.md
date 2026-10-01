# TASK 93 — Phase 2: Canonical Research Dataset

**Dataset id:** `task93_canonical_v1` · **fingerprint** `sha256 796893860a2733b3ffd689c81f2ce68adf96a6096cfcbbc942d7924a34e37474`
Machine-readable definition: `canonical_dataset_manifest.json`. Built dir:
`results/task93_alpha_foundation/_canonical_data/` (35 per-symbol CSVs, gitignored).

## Decision: **use existing local data — no new download.**

Adequate clean historical 1-minute data already exists locally. Per the task ("Do not immediately
download new data if adequate historical data already exists") and NB-7 (yfinance degradation is
irrelevant — every file below is Alpaca, already on disk, `status:FULL`), Task 93 composes its
canonical dataset from three already-validated Alpaca packages.

## Composition

| Segment | Symbols | Period | Bars | Source packages |
|---|---|---|---|---|
| **A — broad** | **35** | 2025-01-24 → 2025-08-14 | 2,565,682 | `task63_orpb_v1_validation` (2025-01-24→05-05) ⧺ `task61r_fprc_v1_validation` (2025-05-06→08-14) — **contiguous, no gap**, identical 35-symbol set |
| **B — deep** | 10 (⊂ the 35) | 2025-08-15 → 2026-08-14 | 1,903,044 | `task7b_alpaca_long_history` — the long-standing canonical-baseline universe (Tasks 4/7B→26→36→74S) |
| **Combined** | **35** | **2025-01-24 → 2026-08-14 (~18.7 months)** | **4,468,726** | |

**Universe (35):** AAPL ADBE ADI AMAT AMD AMZN AVGO BKNG CMCSA COST CSCO GILD GOOGL HON INTC INTU ISRG
KLAC LRCX MDLZ META MSFT MU NFLX NVDA PANW PEP PYPL QCOM REGN SBUX STX TSLA TXN VRTX — the
`talonx_piv.config.DEFAULT_UNIVERSE` / FPRC-ORPB validation universe. **Not** profitability-selected
(it predates and is independent of every economic result); it is the closest available proxy for the
operational 43-symbol watchlist.
**Deep-10:** AAPL AMD AMZN GOOGL META MSFT NVDA PYPL STX TSLA.

## Attributes

| Attribute | Value |
|---|---|
| Provider | Alpaca (SIP/IEX 1-min bars as delivered) |
| Granularity | 1-minute OHLCV |
| Adjustment | **UNADJUSTED** (no split/dividend back-adjustment) |
| Timezone | UTC, tz-aware. Engine classifies sessions in `America/New_York`. |
| Session handling | extended hours included — ~08:00 UTC (04:00 ET pre-market) to ~23:59 UTC (19:59 ET after-hours). Regular-session bars 2,811,653 (62.9 %), pre-market 945,699 (21.2 %), after-hours 711,374 (15.9 %). |
| Duplicates | **0** across all 80 source files / 4.47M bars |
| Ordering | **monotonic increasing** every file (in-file order) |
| NaN / Inf / non-positive price / negative volume / invalid OHLC | **0** every file |
| Zero-volume bars | **0** |
| Missing bars | ~218k intra-day gaps > 2 min across 35 symbols / 18.7 months (~6.2k/symbol) — Alpaca emits no bar for a minute with no trade; concentrated in thin names + pre/post-market. Benign, same pattern documented in Task 26. |
| Corporate-action / bad-print suspects | **1** — AMD 2025-10-06 12:07 UTC (08:07 ET pre-market): a single bar with erroneous `low`/`close` ≈ $165 against a ~$212 context (open/high are consistent). Classified `MINOR` in `data_quality_report.md`; data **not modified**. |

## Why this dataset is suitable

1. **Clean** — zero structural defects across 4.47M bars by the same checks the backtest spec requires
   (Requirement 18): no dupes, no out-of-order, no NaN/Inf, no invalid OHLC, no negative volume.
2. **Broad** — 35 symbols is the widest contiguous universe available and matches the operational
   strategy universe in character; not cherry-picked.
3. **Reproducible** — every file fingerprinted (`per_symbol[*].sha256` in the manifest); combined
   fingerprint fixed; the replay records `git_commit`, `strategy_version`, `config_hash`, `dataset_hash`.
4. **Continuity with prior work** — Segment B is exactly the Task 26/36/74S canonical dataset
   (`dataset_hash 5e5412a960bf`), so Task 93's Segment-B numbers reconcile directly against Task 74S
   (same `strategy_version 2ae6216bca70`).

## Why it is *not* ideal (limitations carried into the verdict)

1. **No pre-2025 history exists locally at all.** Earliest bar 2025-01-24. The task's "ideally
   2023–2026" is **not achievable** — there is no 2020-crash / 2022-bear regime in scope. Any edge
   verdict is conditioned on 2025-01 → 2026-08 market conditions only.
2. Segment A's broad universe spans ~6.7 months — effectively **one macro regime** (2025 H1
   rally-then-tariff-shock-then-recovery). Segment B's 10-symbol year adds regime variety but only for
   mega-caps.
3. UNADJUSTED prices — a split inside the window would appear as a ~50 % single-bar jump. Phase 3
   found none among the 35 (only the one AMD bad print).
4. Individual-security backtest, not point-in-time universe → mild survivorship bias (all 35 are
   prominent/liquid as of 2026). Flagged in every engine summary.

## Verdict

**Dataset is suitable for the Task 93 baseline** — clean, broad, reproducible, multi-symbol, ~18.7
months, two regime segments. It is **not** rich enough (no multi-year, no pre-2025 bear) to make a
*strong* positive edge claim on breadth of regime alone; that limitation is carried explicitly into
Phases 11 and 13. **Not** `TASK93_BLOCKED_DATA_OR_ENGINE` — the data is clean enough to support
meaningful research; the constraint is *history length/regime coverage*, not data quality.
