"""EVENT_RESPONSE_MAP_V1 -- DESIGN LOCK (discovery infrastructure only; no outcomes). Single source of truth for every
rule, threshold, metric, CI definition, cost, screen and integrity tolerance. Committed BEFORE any price data exists.
The fingerprint covers this SPEC and the code that implements it (fingerprint.py). Any change = a new version.
"""
from __future__ import annotations

PROGRAM = "EVENT_RESPONSE_MAP_V1"
STATUS = "DISCOVERY_ONLY -- nothing produced by this program is validated; at most ONE hypothesis may later be nominated, frozen and pre-registered in a separate task"

SPEC = {
    "program": PROGRAM,
    "status": STATUS,
    "lock_revision": 3,
    "revision_3_changes (owner, 2026-10-01; no data existed)": {
        "R1_FIX_a_sp500_exemption": "point-in-time S&P 500 members (any day 2019-2023) are exempt from R1a (index membership = operating common stock); R1b still applies where a CIK exists",
        "R1_FIX_b_identity_resolution": "before R1a, candidate tickers are resolved to CIKs (research/event_response_map_v1/identity.py): forward dated Alpaca rename chain (2019-2023 + post-2023 renames, identity only, Task75 reserved windows NOT queried) to a current SEC ticker; SEC company_tickers / submissions 'tickers' (never for a ticker that was renamed away); backward rename chain; issuer trading symbol on Form 3/4/5 2019-2023 when it names exactly one issuer CIK; unique normalized name across cik-lookup-data + submissions name/formerNames. Metadata only, R5 guard. R1a counts reported by source (B, C, D) and reason at: rev2 | +S&P exemption | +identity resolution",
        "R1_FIX_c_survivorship_diagnostic": "NON-GATING: Phase D also downloads development bars (ALL + raw eligibility) for every symbol still removed by R1a (separate archive alpaca_diag); reports how many pass $5/$20M by bucket x year; for SCREEN_PASS cells only, re-computes the cell with those symbols' events added (NO_EVENT not re-drawn) and flags EXCLUSION_DEPENDENT if the cell no longer passes",
        "R6_dated_attribution": "each 8-K is assigned to the ONE ticker valid for its CIK on the FILING DATE via the dated rename chain (validity: from the processing date of the rename into the ticker until the rename out of it); bar presence on the entry date is a consistency check only; AMBIGUOUS (several valid, e.g. dual share classes), NO_VALID_TICKER and DISAGREE (assigned ticker lacks the entry bar while another ticker of the CIK has it) are excluded and counted. Audit of every one-ticker-per-CIK use: (1) 8-K attribution -> dated rule; (2) sector benchmark -> dated symbol->CIK on the entry date, else SPY; (3) Form 4 symbol -> dated ticker of the issuer CIK on the filing date, reported symbol must agree, else excluded and counted; (4) the rev-1 UNMAPPED_INACTIVE_CIK map is retired (a CIK without development filings simply yields no 8-K/Form-4 events)",
        "R7_point_in_time_sic": "CHOSEN: dated SIC. sic_end = SIC in the EDGAR filing header (-index-headers.html) of the CIK's last company filing (10-K/10-Q/8-K/20-F/40-F/6-K/S-1/S-4/DEF 14A and /A) dated <= 2023-12-29; if the CIK filed an 8-K item 5.06 (change in shell company status) in the period, the header SIC of its last company filing before that 8-K applies before it and sic_end from it on. Fallback when no company filing exists in the period: current submissions SIC (counted). R1b: a symbol is removed if its CIK's SIC is 6770 for the whole period; otherwise symbol-days inside a 6770 window are masked from eligibility. Cost ~1 header per CIK + 1 per 5.06 CIK (~6-7k SEC requests, ~40 min at <= 2.9/s, off-hours). Residual limitation: an SIC reclassification without an item 5.06 inside the period is not dated (sic_end applies)",
        "R3_result": "10,772 in -> 7,613 kept; R1a 2,769 after identity resolution (rev2 3,467 -> +S&P exemption 3,420 -> final 2,769; final by reason: no CIK 2,628, CIK without 10-K/10-Q 141); R1b dated SIC 6770 whole period 390 removed, 46 symbols day-masked; PIT S&P 500 metadata coverage 100 % every year 2019-2023; 8-K (filing x target item) at metadata stage: 195,210 assigned, 14,099 NO_VALID_TICKER + 5,530 AMBIGUOUS excluded, 1,212 assigned to R1-removed symbols; DISAGREE measured in Phase D",
        "frozen_list": "results/event_response_map_v1/candidates_r3.json (sha256 pinned in design_lock.json) supersedes candidates_r1.json for Phase D",
    },
    "revision_2_changes (owner, Gate C; no data existed)": {
        "approved_decisions": "1 raw as-traded D-1 data for ELIGIBILITY ONLY (returns stay adjustment=all); 2 gap entry D+1 open; 3 8-K conservative dual acceptance reading; 4 directional cost test",
        "R1_instrument_filter": "a candidate WITHOUT a known name is kept only if it maps to a CIK with a 10-K/10-K/A/10-Q/10-Q/A filed 2019-01-01..2023-12-31 (EDGAR full-index master.idx 2019Q1-2023Q4); ANY candidate whose mapped CIK has SIC 6770 (blank checks; current EDGAR SIC) is excluded; applied before any price download; frozen as candidates_r1.json (sha256 pinned); counts per rule reported",
        "R1_result": "10,772 in -> 7,027 kept; removed 3,745 = R1a 3,467 (3,415 unnamed with no CIK + 52 unnamed CIK without 10-K/10-Q) + R1b 279 (SIC 6770), 1 removed by both; SIDE EFFECT: R1a removes 47 of 614 PIT S&P 500 members 2019-2023 (e.g. BK, MMC, AVB, EQR, EA, HES, WBA) whose tickers changed or delisted after 2023; PIT S&P coverage after R1: 2019 91.74 %, 2020 92.94 %, 2021 92.95 %, 2022 93.35 %, 2023 94.82 %",
        "R2_null_calibration": "if ANY NO_EVENT cell is SCREEN_PASS the map is MAP_MISCALIBRATED and no candidate may be nominated until explained (all nominatable flags forced False); the NO_EVENT SCREEN_PASS count is the FIRST line of report.md",
        "R3_missing_exits": "per cell missing_exit_rate = exits missing (entry bar present, exit bar absent) / (valid + missing); a cell with > 2 % cannot be SCREEN_PASS; for cells <= 2 % a NON-GATING bound sensitivity fills missing exits with (LONG -100 %, SHORT 0 %) and the mirror (LONG 0 %, SHORT -100 %) as sector-relative values",
        "R4_coverage": "the D0 bar-coverage report breaks out by liquidity bucket x year (eligible symbol-days, distinct symbols, ALL-bar present rate, missing-exit rate), in addition to sources and the PIT S&P 500",
        "R5_off_hours": "Alpaca and SEC network calls refused on a weekday between 09:00 and 16:30 America/New_York (regular hours +/- 30 min, zoneinfo, DST-aware; US DST ends 2026-11-01)",
        "phase_d_schedule": "weekend (Sat 2026-10-03 or Sun 2026-10-04), live engine in CLOSED phase, --eligibility-raw-approved",
    },
    # ---------------------------------------------------------------------------------------------- C2 periods
    "periods": {
        "DEVELOPMENT_events": ["2019-01-02", "2023-12-29"],
        "data_lookback_start": "2018-11-01",
        "EXCLUDED_2024": ["2024-01-01", "2024-12-31"],
        "FUTURE_CONFIRMATION_LOCKED": ["2025-01-02", "open-ended"],
        "horizon_rule": "an event enters a horizon cell only if that horizon's exit session is <= 2023-12-29 (no 2024 bar is ever needed or read)",
        "guard": "research/common/locked_range_guard.py EVENT_RESPONSE_MAP_V1 (download AND load layers)",
    },
    # ---------------------------------------------------------------------------------------------- C1 universe
    "universe": {
        "definition": "point-in-time liquid US common stocks, decided with data as of D-1 only",
        "candidate_sources": {
            "A": "Alpaca /v2/assets us_equity, status active AND inactive, exchanges NYSE/NASDAQ/AMEX/ARCA/BATS, symbol ^[A-Z]{1,5}(\\.[A-Z])?$, instrument-type name rules reused from talonx_premarket/universe.py::_NAME_RULES (status, tradable and CIK NOT required)",
            "B": "Alpaca /v1/corporate-actions name_change 2019-2023: every old_symbol (pre-rename ticker) is a candidate",
            "C": "Alpaca /v1/corporate-actions cash/stock/stock-and-cash mergers 2019-2023: every acquiree_symbol is a candidate",
            "D": "Task95F point-in-time S&P 500 membership (fja05680/Wikipedia): every ticker that was a member on any day 2019-2023",
        },
        "how_delisted_and_renamed_enter": "delisted names enter via A(inactive) if Alpaca still lists them, else via C (acquirees) or D (former S&P members); renamed names enter under their OLD ticker via B and their NEW ticker via A; whether Alpaca returns bars for each candidate symbol is MEASURED in Phase D step D0 (per-year bar coverage reported) -- a symbol without bars cannot enter",
        "not_used": "today's DTU / ELIGIBLE list is NEVER used for history",
        "eligibility_D_minus_1": {
            "close_min_usd": 5.0, "adv20_min_usd": 20_000_000,
            "adv20_definition": "mean over the 20 sessions ending D-1 of (as-traded close x as-traded volume); >= 20 prior sessions required",
            "price_basis": "AS-TRADED (adjustment=raw) daily close/volume of D-1, used ONLY for this point-in-time eligibility test -- never for returns, features or benchmarks. Reason: adjustment=all back-adjusts past prices by FUTURE splits/dividends (3,178 splits/spin-offs in 2019-2023, 2,670 of them reverse splits), so an adjusted $5 or $ADV floor would be look-ahead.",
            "owner_approval_required": "YES (Gate C): this raw ELIGIBILITY_ONLY pull deviates from the instruction 'all downloads adjustment=all'. If not approved, V1 is not run; a V1.1 lock would derive as-traded values from ALL bars + CA factors before any data.",
        },
        "liquidity_buckets_adv20_usd": {"L1": [20_000_000, 100_000_000], "L2": [100_000_000, 1_000_000_000], "L3": [1_000_000_000, None]},
        "survivorship_limitation": "NOT survivorship-free. Alpaca's asset list omits some names delisted/renamed after 2023 (e.g. K, EA, IPG, HOLX, PXD, SIVB, DISCA, FLT absent from active AND inactive). Metadata coverage of the point-in-time S&P 500 by sources A|B|C: 2019 93.6 %, 2020 94.5 %, 2021 94.3 %, 2022 94.7 %, 2023 95.2 % (source D adds the remainder as candidate symbols; bar availability measured in D0). Coverage of smaller liquid names has no free reference and is presumed no better. Results are conditional on this universe. Instrument-type name rules apply to source A (and to B tickers that inherit a name); C/D-only symbols without a name (3,552 of 10,772 have no name) are not instrument-filtered and are counted in the integrity report. Frozen candidate list: results/event_response_map_v1/candidates.json (10,772 symbols; A 6,764 | B 1,454 | C 3,242 | D 614; only-D 37), sha256 pinned in design_lock.json.",
        "cik_and_sic": "CIK: SEC company_tickers.json (current); a pre-rename ticker (source B) inherits the CIK of its new_symbol; else an exact normalized-name match (upper-case, punctuation and INC/CORP/CO/LTD/PLC/HOLDINGS suffixes removed) in SEC cik-lookup-data.txt, accepted only if UNIQUE; a mapping is kept only if that CIK has >= 1 EDGAR filing dated 2019-01-02..2023-12-29 (guards against recycled tickers), else UNMAPPED_INACTIVE_CIK; SIC from EDGAR submissions JSON. No CIK -> no 8-K events for that symbol and SIC unknown -> benchmark SPY (per SIC_ETF_MAP_V1 default). Both counts are reported.",
    },
    # ---------------------------------------------------------------------------------------------- data (C-DATA)
    "data": {
        "returns_and_benchmarks": "Alpaca SIP 1Day adjustment=all for equities, SPY and sector ETFs (XLE, XBI, XLV, XLK, XLI, XLF) -- ONE downloader module (research/event_response_map_v1/data.py), identical parameters; only R1-kept candidates are requested",
        "off_hours": "R5: weekday 09:00-16:30 America/New_York refused for Alpaca and SEC",
        "eligibility_only": "same downloader module, adjustment=raw, purpose=ELIGIBILITY_ONLY (see universe.eligibility_D_minus_1.owner_approval_required)",
        "filings": "EDGAR submissions JSON per CIK (items + acceptanceDateTime + sic); EDGAR full-index master.idx 2019Q1-2023Q4 (R1 periodic-filer test); SEC Form 3/4/5 quarterly bulk 2019Q1-2023Q4 for FORM4_CLUSTER",
        "archive": "archived bytes are authoritative; manifest with per-file sha256, aggregate hash, download UTC, missing / duplicate sessions, 0 synthetic bars",
    },
    # ---------------------------------------------------------------------------------------------- C3 events
    "events": {
        "GAP_UP_3": "open_D/close_{D-1} - 1 >= +3 %  (ALL bars)", "GAP_UP_5": ">= +5 %", "GAP_UP_10": ">= +10 %",
        "GAP_DOWN_3": "<= -3 %", "GAP_DOWN_5": "<= -5 %", "GAP_DOWN_10": "<= -10 %",
        "gap_note": "thresholds are NESTED (a +12 % gap is in GAP_UP_3, _5 and _10), as specified; the trial ledger counts every cell",
        "gap_causal_timestamp": "D 09:30 ET opening print; the gap is observable only AT the print, so under the strict entry rule entry = OPEN of session D+1 (trading the gap-day open itself would not be causal)",
        "8K_2.02": "8-K item 2.02", "8K_1.01": "item 1.01", "8K_5.02": "item 5.02", "8K_7.01": "item 7.01", "8K_8.01": "item 8.01",
        "8k_rules": "form 8-K only (8-K/A excluded); a filing with several items counts once in each item cell; filings with filingDate outside 2019-01-02..2023-12-29 are dropped at parse time before any field is used (the submissions endpoint has no date filter); causal timestamp = EDGAR acceptanceDateTime under CONSERVATIVE_DUAL_INTERPRETATION: the LATER of reading it as UTC and as ET (EDGAR surfaces have been inconsistent; this is causal under either)",
        "FORM4_CLUSTER": "talonx_v2.cluster_engine.detect_episodes (V2@1 definition, unchanged) on SEC bulk code-P rows; causal = end of the activation filing day; LABEL: KNOWN_UNSUPPORTED_BASELINE (calibration, never nominatable)",
        "NO_EVENT": "control: for each (entry date, liquidity bucket) with k distinct event stock-days, draw k eligible stock-days with NO event of any type whose entry falls within +/-2 sessions; sorted candidates, seed 670067; LABEL: CONTROL (never nominatable)",
        "dedup": "one observation per (event type, symbol, entry session)",
    },
    # ---------------------------------------------------------------------------------------------- C4 entry / horizons
    "entry": "OPEN of the first regular session that STARTS strictly after the causal timestamp (an event after the 16:00 ET close, or on a non-session day, belongs to the next session; acceptance before 09:30 ET enters that day's open). No intraday entry.",
    "horizons": {"H0": "close of the entry session", "H1": "close of entry + 1 session", "H3": "+3", "H5": "+5", "H10": "+10"},
    "directions": {"LONG": "exit/entry - 1", "SHORT": "-(exit/entry - 1); RESEARCH_SHORT_REFERENCE"},
    # ---------------------------------------------------------------------------------------------- C5 metrics
    "metrics": ["n", "distinct_dates", "distinct_symbols", "mean_raw", "median_raw", "mean_spy_relative",
                "mean_sector_relative (SIC_ETF_MAP_V1, docs/research/preregistration/rs_sector_mapping_v1.json)",
                "hit_rate (sector-relative gross > 0)", "dispersion (sd of sector-relative gross)",
                "date_cluster_ci (sector-relative gross; research.common.research_stats.bootstrap_ci_clustered, group=entry date, 10,000 resamples, 95 %, seed 670067)",
                "top1/top3/top5 removal (sector-relative gross)", "per-year sign stability 2019..2023 (years with n < 20 count as NOT stable)"],
    "relative_returns": "benchmark return over the SAME entry-open -> exit-close interval from ALL bars; benchmark missing -> event dropped (counted)",
    # ---------------------------------------------------------------------------------------------- C6 costs
    "costs_round_trip_bps": {"L1": 30, "L2": 20, "L3": 12, "label": "RESEARCH ASSUMPTIONS, declared up front, never tuned"},
    # ---------------------------------------------------------------------------------------------- C7 screen
    "screen": {
        "SCREEN_PASS_all_of": ["n >= 300", "distinct_dates >= 150",
                               "mean sector-relative gross IN THE CELL'S DIRECTION >= 2 x bucket cost (i.e. |mean| >= 2x cost with the sign matching the direction; LONG/SHORT cells are mirrors, so 390 cells = 195 independent sign tests and a pair can pass at most once)",
                               "date-cluster 95 % CI of mean sector-relative gross excludes zero on the side of the mean",
                               "sign of yearly mean sector-relative gross equals the overall sign in >= 4 of 5 development years",
                               "removing the top 5 trades (by sector-relative gross in the cell's direction) does not flip the sign",
                               "R3: missing-exit rate <= 2 %"],
        "null_calibration": "R2: any NO_EVENT SCREEN_PASS -> MAP_MISCALIBRATED, nomination blocked until explained",
        "scope": "a screening rule for THIS program only, not a permanent TalonX law",
        "non_nominatable": ["FORM4_CLUSTER (known unsupported baseline)", "NO_EVENT (control)"],
    },
    "trial_ledger": "every evaluated cell is recorded (metrics + screen result); the trial count is the number of cells evaluated",
    "cells": "13 event types x 2 directions x 5 horizons x 3 liquidity buckets = 390",
    # ---------------------------------------------------------------------------------------------- integrity tolerances
    "integrity_tolerances": {
        "synthetic_bars": "NONE -- no interpolation, no forward fill",
        "missing_bar": "missing entry-open bar -> dropped, DATA_MISSING_ENTRY; missing benchmark bar -> dropped, BENCH_MISSING; missing exit-close bar (entry present) -> DATA_MISSING_EXIT, kept as a flagged row for the R3 rate/gate/bounds, excluded from every metric",
        "duplicate_session": "a symbol-session with duplicate daily rows is excluded entirely and counted",
        "suspect_adjustment": "|close_t / close_{t-1} - 1| > 75 % on ALL bars inside an event's entry..exit window -> event RETAINED, flagged SUSPECT_ADJUSTMENT, counted; a pre-declared NON-GATING sensitivity (flagged events excluded) is reported",
        "eligibility_raw_missing": "no as-traded D-1 bar -> not eligible that day",
        "cent_rounding": "NOT APPLICABLE and NOT carried over from Task75 (this program never compares RAW and ALL prices)",
        "tolerance_changes": "none permitted after data exists; any change = new version",
    },
    "run_once": "Phase D runs the locked extraction and metrics exactly once; outputs results/event_response_map_v1/{cells.csv, screen.csv, trial_ledger.json, report.md}",
}
