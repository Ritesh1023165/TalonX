"""Explicit acquisition coverage per window and input category (no global date constants are mutated).

Every request the acquirer builds is guarded with (category, content_from, content_to) taken from this table, BEFORE
the request exists. DEV reproduces the frozen Phase D / R3 / V2.1 development coverage exactly; A and B are the
[MAP->W] substitutions. Endpoints whose response necessarily contains content beyond the request scope are listed in
BROAD_ENDPOINTS with the rule applied to them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

# Task75 reserved windows (frozen identity.TASK75_RESERVED): skipped for DEV identity renames, exactly as frozen
TASK75_RESERVED = ((date(2024, 6, 1), date(2024, 9, 2)), (date(2024, 10, 21), date(2024, 12, 20)))
FROZEN_POST2023_RENAME_RANGES = (("2024-01-01", "2024-05-31"), ("2024-09-03", "2024-10-20"),
                                 ("2024-12-21", "2024-12-31"), ("2025-01-01", "2025-12-31"),
                                 ("2026-01-01", "2026-09-30"))


def quarters(a: date, b: date) -> list[tuple[int, int]]:
    out, y, q = [], a.year, (a.month - 1) // 3 + 1
    while (y, q) <= (b.year, (b.month - 1) // 3 + 1):
        out.append((y, q))
        y, q = (y + 1, 1) if q == 4 else (y, q + 1)
    return out


def year_ranges(a: date, b: date) -> list[tuple[str, str]]:
    """Calendar-year request ranges covering [a, b], the last clipped to b (never past b)."""
    return [(max(date(y, 1, 1), a).isoformat(), min(date(y, 12, 31), b).isoformat()) for y in range(a.year, b.year + 1)]


@dataclass(frozen=True)
class AcquisitionPeriod:
    window_id: str
    events_from: date                 # gap-day window (V2.1 / [MAP->W])
    events_to: date
    bars_from: date                   # ALL + raw bars incl. warm-up (eligibility look-back, D-1)
    corporate_actions_from: date      # sources B / C and in-period renames (candidate + identity)
    corporate_actions_to: date
    identity_rename_ranges: tuple     # post-period rename ranges used ONLY for symbol relabelling identity
    identity_f345_from: date          # R3 identity resolution (frozen: the period quarters)
    evidence_f345_from: date          # V2.1 dated ticker evidence (from 2018Q1)
    filings_from: date                # R3 dev_filings / R7 sic_end window
    filings_to: date
    sp500_from: date                  # point-in-time S&P lists used (source D and V2.1 S&P evidence)
    sp500_to: date
    etf_dividends_from: date
    etf_dividends_to: date
    notes: tuple = field(default=())

    def f345_quarters(self, frm: date) -> list[str]:
        return [f"{y}q{q}" for y, q in quarters(frm, self.events_to)]

    def master_quarters(self) -> list[str]:
        return [f"{y}/QTR{q}" for y, q in quarters(self.filings_from, self.filings_to)]

    def coverage_table(self) -> list[dict]:
        d = self
        return [
            {"category": "bars", "from": d.bars_from, "to": d.events_to, "required": True},
            {"category": "assets_current", "from": None, "to": "download date", "required": True},
            {"category": "corporate_actions", "from": d.corporate_actions_from, "to": d.corporate_actions_to, "required": True},
            {"category": "identity_renames", "from": [r[0] for r in d.identity_rename_ranges][:1],
             "to": [r[1] for r in d.identity_rename_ranges][-1:], "required": True},
            {"category": "sec_reference_current", "from": None, "to": "download date", "required": True},
            {"category": "form345", "from": d.evidence_f345_from, "to": d.events_to, "required": True},
            {"category": "master_idx", "from": d.filings_from, "to": d.filings_to, "required": True},
            {"category": "submissions", "from": "history", "to": d.filings_to, "required": "per CIK (404 = absent)"},
            {"category": "filing_headers", "from": "history", "to": d.events_to, "required": "per accession (404 = absent)"},
            {"category": "sp500_pit", "from": d.sp500_from, "to": d.sp500_to, "required": True},
            {"category": "etf_cash_dividends", "from": d.etf_dividends_from, "to": d.etf_dividends_to, "required": False},
        ]


PERIODS = {
    "DEV": AcquisitionPeriod(
        "DEV", date(2019, 1, 2), date(2023, 12, 29), date(2018, 11, 1), date(2019, 1, 1), date(2023, 12, 31),
        FROZEN_POST2023_RENAME_RANGES, date(2019, 1, 1), date(2018, 1, 1), date(2019, 1, 2), date(2023, 12, 29),
        date(2019, 1, 1), date(2023, 12, 31), date(2019, 1, 1), date(2023, 12, 31),
        ("frozen development coverage (Phase D, R3, V2.1 audit)",)),
    "A": AcquisitionPeriod(
        "A", date(2024, 1, 2), date(2024, 12, 31), date(2023, 11, 1), date(2024, 1, 1), date(2024, 12, 31),
        (("2025-01-01", "DOWNLOAD_DATE"),), date(2024, 1, 1), date(2018, 1, 1), date(2024, 1, 2), date(2024, 12, 31),
        date(2024, 1, 1), date(2024, 12, 31), date(2024, 1, 1), date(2024, 12, 31),
        ("post-window renames through the bar download date are identity-only and need explicit release scope",)),
    "B": AcquisitionPeriod(
        "B", date(2024, 1, 2), date(2026, 9, 30), date(2023, 11, 1), date(2024, 1, 1), date(2026, 9, 30),
        (("2026-10-01", "DOWNLOAD_DATE"),), date(2024, 1, 1), date(2018, 1, 1), date(2024, 1, 2), date(2026, 9, 30),
        date(2024, 1, 1), date(2026, 9, 30), date(2024, 1, 1), date(2026, 9, 30),
        ("post-window renames through the bar download date are identity-only and need explicit release scope",)),
}

# Endpoints whose response is necessarily broader than any date scope. Rule: the request is guarded under its
# category with content_to = the retrieval date (so a protected period always requires an explicit release scope
# naming the category); on receipt, rows dated after the period's scope end are never parsed (builder / scope readers
# drop them before reading other fields); raw bytes are archived for provenance.
BROAD_ENDPOINTS = {
    "assets_current": "Alpaca /v2/assets: current asset list (no history); names + exchanges for source A",
    "sec_reference_current": "SEC company_tickers.json and cik-lookup-data.txt: current reference files",
    "submissions": "SEC submissions JSON: full filing history to the retrieval date (rows > scope end dropped)",
    "sp500_pit": "fja05680 point-in-time S&P 500 CSV: whole history file (rows > scope end dropped; coverage "
                 "must be stated by the source as-of date >= scope end)",
}


def quarter_start(d: date) -> date:
    return date(d.year, 3 * ((d.month - 1) // 3) + 1, 1)


def quarter_end(d: date) -> date:
    from datetime import timedelta
    q = (d.month - 1) // 3 + 1
    return (date(d.year + 1, 1, 1) if q == 4 else date(d.year, 3 * q + 1, 1)) - timedelta(days=1)


def scope_envelopes(p: AcquisitionPeriod, download_date: date) -> dict:
    """category -> [[content_from | None, content_to]]: the EXACT acquisition scope of one window, as the acquirer
    guards it (None = history). A release must name exactly this (no wider, no narrower, no other category)."""
    dd = download_date.isoformat()
    iso = lambda d: d.isoformat()  # noqa: E731
    return {
        "bars": [[iso(p.bars_from), iso(p.events_to)]],
        "assets_current": [[None, dd]],
        "corporate_actions": [[iso(p.corporate_actions_from), iso(p.corporate_actions_to)]],
        "identity_renames": [[a, dd if b == "DOWNLOAD_DATE" else b] for a, b in p.identity_rename_ranges],
        "sec_reference_current": [[None, dd]],
        "form345": [[iso(quarter_start(p.evidence_f345_from)), iso(quarter_end(p.events_to))]],
        "master_idx": [[iso(quarter_start(p.filings_from)), iso(p.filings_to)]],
        "submissions": [[None, dd]],
        "filing_headers": [[None, iso(p.filings_to)]],
        "sp500_pit": [[None, dd]],
        "etf_cash_dividends": [[iso(p.etf_dividends_from), iso(p.etf_dividends_to)]],
    }
