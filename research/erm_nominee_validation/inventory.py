"""ERM nominee validation plumbing -- required-input inventory (DECLARATIVE; never queries any source).

Each input is categorised:
  PRICE_OUTCOME          bars that determine eligibility, gaps and returns (ALL + raw)
  IDENTITY_METADATA      dated facts used to reconstruct identity / instrument / R1a / S&P / SIC on D
  DESCRIPTIVE_METADATA   inputs of the never-gating descriptive subset only
Coverage is derived from the configuration. For the development configuration the archived sources are listed; for a
validation window every input is NOT_ACQUIRED and every input whose coverage intersects a locked range is GUARDED.
"""
from __future__ import annotations

from datetime import date, timedelta

from research.erm_nominee_validation.config import ValidationConfig

LOCKED = (("EXCLUDED_2024", date(2024, 1, 1), date(2024, 12, 31)),
          ("FUTURE_CONFIRMATION_2025_ONWARD", date(2025, 1, 2), date(9999, 12, 31)))
TASK75_RESERVED = ((date(2024, 6, 1), date(2024, 9, 2)), (date(2024, 10, 21), date(2024, 12, 20)))
EVIDENCE_HISTORY_FROM = date(2018, 1, 1)          # V2.1: dated Form 3/4/5 and S&P evidence from 2018Q1
PRICE_LOOKBACK_CAL_DAYS = 45                      # >= 21 sessions before the first gap day (20-session ADV + D-1)

DEV_SOURCES = {
    "bars_all_raw": r"C:\workspace\TalonX-erm\results\event_response_map_v1\_archive\alpaca (+ alpaca_diag)",
    "form345": r"_archive\sec\{2019..2023}q*_form345.zip.gz + results\erm_nominee_audit\_sec_v2\2018q*_form345.zip.gz",
    "renames": r"_renames_2019_2023.json + _archive\alpaca_meta_renames_post2023.json (Task75 windows not queried)",
    "submissions": r"_archive\sec\sub_CIK*.json.gz + results\erm_nominee_audit\_sec_v2\sub_CIK*.json.gz",
    "master_idx": r"_archive\sec\master_{2019..2023}_QTR*.idx.gz",
    "filing_headers": r"_archive\sec\hdr_* + results\erm_nominee_audit\_sec_pit\ + _sec_v2\ ",
    "sp500_pit": r"C:\workspace\TalonX\results\task95g_broad_cross_sectional\_fja05680_pit.csv",
    "etf_cash_dividends": r"results\erm_nominee_audit\_alpaca_v2\etf_cash_dividends.json (2019-2023)",
    "candidates": r"candidates.json / candidates_r3.json (frozen development candidate universe)",
}


def _locked(a: date, b: date) -> list[str]:
    return [n for n, lo, hi in LOCKED if a <= hi and b >= lo]


def _task75(a: date, b: date) -> bool:
    return any(a <= hi and b >= lo for lo, hi in TASK75_RESERVED)


def inventory(cfg: ValidationConfig) -> list[dict]:
    s, e = cfg.start, cfg.end
    items = [
        ("bars_all_raw", "PRICE_OUTCOME", s - timedelta(days=PRICE_LOOKBACK_CAL_DAYS), e,
         "Alpaca SIP 1Day ALL (returns, gaps, benchmarks) + raw (eligibility, traded flag) for the window candidate "
         "download scope (R1-kept + R1a-removed, as in development); benchmarks ALL only"),
        ("candidates", "IDENTITY_METADATA", s, e,
         "candidate sources A|B|C|D rebuilt with window dates [MAP->W] (asset list, renames, mergers, PIT S&P)"),
        ("form345", "IDENTITY_METADATA", EVIDENCE_HISTORY_FROM, e,
         "SEC insider data sets 2018Q1 .. quarter of the window end: dated issuer-trading-symbol observations <= D"),
        ("renames", "IDENTITY_METADATA", EVIDENCE_HISTORY_FROM, None,
         "provider name changes through the bar DOWNLOAD date (relabelling is resolved at download time)"),
        ("submissions", "IDENTITY_METADATA", None, e,
         "per-issuer filing history (all years) <= window end: periodic filings (R1a), 8-K 5.06 transitions, "
         "company-filing accessions for point-in-time SIC"),
        ("master_idx", "IDENTITY_METADATA", None, e, "EDGAR full-index periodic filings (R1a availability) <= window end"),
        ("filing_headers", "IDENTITY_METADATA", None, e, "header SIC of the latest company filing <= D (per event)"),
        ("sp500_pit", "IDENTITY_METADATA", EVIDENCE_HISTORY_FROM, e, "point-in-time S&P 500 lists"),
        ("etf_cash_dividends", "DESCRIPTIVE_METADATA", s, e, "provider cash-dividend records of the 7 benchmark ETFs"),
    ]
    out = []
    for name, cat, a, b, desc in items:
        a_ = a or date(1993, 1, 1)
        b_ = b or date(9999, 12, 31)
        locked = _locked(a_, b_)
        if cfg.window_id == "DEV":
            status = "ARCHIVED_DEVELOPMENT"
        else:
            status = "NOT_ACQUIRED" + ("+GUARDED" if locked else "")
        out.append({"input": name, "category": cat, "coverage_from": a.isoformat() if a else "history",
                    "coverage_to": b.isoformat() if b else "bar download date",
                    "locked_ranges": locked, "task75_reserved_overlap": _task75(a_, b_),
                    "status": status, "dev_source": DEV_SOURCES.get(name, "") if cfg.window_id == "DEV" else "",
                    "description": desc})
    return out
