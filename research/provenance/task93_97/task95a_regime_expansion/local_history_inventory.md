# TASK 95A — Phase 1 — Local Historical Data Forensic Inventory

**Scope of search:** `data/historical_1m/` (all sub-packages), `results/**` (esp.
`results/task93_alpha_foundation/_canonical_data/`), `talonx_ingest/market_data/`,
`results/task52_historical_ab_freeze/`, repo-wide `find` for `*historical*` / `*_1m*` / `*bars*` /
`*ohlcv*` / `*market_data*` directories. `.gitignore` confirms `/data/` and `/results/` are
untracked, provider-licensed, regenerable — not versioned.

## Headline finding

**Every 1-minute dataset on this machine starts on or after 2025-01-24.** There is **zero pre-2025
history** anywhere locally. This is exactly the coverage gap Task 93 §2 and Task 94's
residual-risk note flagged, and it is the reason Task 95A exists.

## Inventory table (all `data/historical_1m/` packages)

| Package | Files | Symbols | Bars | Earliest | Latest | Provider / feed | Adjust | RTH/ext | Prior use | Notes |
|---|---:|---:|---:|---|---|---|---|---|---|---|
| `task63_orpb_v1_validation` | 35 | 35 | 1,307,932 | 2025-01-24 | 2025-05-05 | Alpaca / **SIP** (omitted-feed default; confirmed by task63r diagnostic) | raw | ext | **Task 93 canonical Segment A (first half)** | contiguous with task61r, no gap |
| `task61r_fprc_v1_validation` | 35 | 35 | 1,257,750 | 2025-05-06 | 2025-08-14 | Alpaca / SIP | raw | ext | **Task 93 canonical Segment A (second half)** | |
| `task7b_alpaca_long_history` | 10 | 10 | 1,903,044 | 2025-08-15 | 2026-08-14 | Alpaca / SIP | raw | ext | **Task 93 canonical Segment B** (deep-10) + Task 74S | AAPL AMD AMZN GOOGL META MSFT NVDA PYPL STX TSLA |
| `task54_extended_windows` | 105 | 35 | 1,770,708 | 2025-09-15 | 2026-05-18 | Alpaca / SIP | raw | ext | Task 54; **Task 93/94 secondary untouched holdout** | 3 scattered windows W1/W2/W3 |
| `task56_holdout` | 75 | 25 | 1,164,619 | 2025-12-11 | 2026-07-09 | Alpaca / SIP | raw | ext | Task 56; secondary untouched holdout | 3 windows H1/H2/H3, the 25 non-deep symbols |
| `task37_universe_windows` | 105 | 35 | 600,363 | 2025-08-29 | 2026-07-31 | Alpaca / SIP | raw | ext | Task 37; secondary untouched holdout | 3 windows A/B/C |
| `task46_validation_windows` | 105 | 35 | 309,838 | 2025-10-27 | 2026-06-09 | Alpaca / SIP | raw | ext | Task 46 | 3 windows X/Y/Z |
| `task53_warmup_windows` | 105 | 35 | 597,861 | 2025-10-13 | 2026-06-02 | Alpaca / SIP | raw | ext | Task 53 warm-up probes | |
| `task4_trade_lifecycle` | 10 | 10 | 137,648 | 2026-07-27 | 2026-08-14 | **yfinance** | — | ext | Task 4 fixtures | **volume == 0.0** (yfinance 1-min quirk) — unusable for volume features |
| `task22_oos` | 10 | 10 | 27,490 | 2026-08-17 | 2026-08-19 | yfinance | — | ext | Task 22 OOS | volume == 0.0 |
| `smoke_test`, `smoke_test_v2` | 5+5 | 5 | 28,651 ea | 2026-08-07 | 2026-08-14 | Alpaca | raw | ext | CI smoke fixtures | tiny |
| `task7_provider_probe`, `task7b_alpaca_probe` | 1+1 | 1 | 1,919 / 4,332 | 2026-08-10 | 2026-08-14 | Alpaca/yf | raw | ext | provider probes | tiny |
| `task56_independent_family_holdout` | 0 | 0 | — | — | — | — | — | — | empty dir |

`results/task93_alpha_foundation/_canonical_data/` — 35 per-symbol CSVs, **4,468,726 bars**,
2025-01-24 → 2026-08-14, fingerprint `sha256 796893860a2733b3ffd689c81f2ce68adf96a6096cfcbbc942d7924a34e37474`.
This is the concatenation of task63 + task61r (+ task7b for the deep 10). **This is the Task 94
discovery/validation/holdout source and the comparability anchor for Task 95A.**

`talonx_ingest/market_data/` — code only (no data files). `results/task52_historical_ab_freeze/` —
A/B freeze metadata, no raw bars.

## Feed / provider provenance (critical for comparability)

- `results/task63r_orpb_v1_feed_remediation/feed_diagnostic.json`:
  `persisted_task63_feed = "SIP"`, `implicit_omitted_matches_persisted = true`,
  `sip_available = true`. The `download_historical_1m.py` Alpaca path omits the `feed` parameter;
  on this account that **resolves to SIP** (full consolidated volume), not IEX.
- All Task 93 canonical data, and every non-yfinance package above, is therefore **Alpaca SIP,
  `adjustment=raw` (unadjusted), extended hours included, UTC tz-aware**.
- yfinance packages (`task4_trade_lifecycle`, `task22_oos`) carry **volume == 0** and are excluded
  from any Task 95A use.

## Known contamination / limitations carried forward from Task 93

- UNADJUSTED prices → a split shows as a single-bar ~50% jump (audited per-year in Phase 5).
- Individual-security series, not point-in-time universe → mild survivorship bias (all 35 are
  prominent 2026 names).
- Alpaca omits zero-volume minutes in thin pre/post sessions → benign intra-session "gaps".
- 1 known MINOR bad pre-market print (AMD 2025-10-06 12:07 UTC) — left unmodified in Task 93.

## Decision

Pre-2025 history **must be acquired** (none exists). It can be pulled from the **same provider and
feed** as Task 93 (Alpaca SIP) — see `target_history_spec.md` (Phase 2) and the Phase 3 entitlement
probe (`_probe_alpaca_depth.json`). 2025-01-24 → 2026-08-14 is **not** re-downloaded; it is spliced
from Task 93 canonical after a seam check (Phase 5).
