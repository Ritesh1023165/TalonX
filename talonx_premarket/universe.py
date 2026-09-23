"""
Broad universe: US-listed common equities, deterministic and auditable.

Sources (free, already used by TalonX):
* Alpaca ``/v2/assets`` (status/tradable/exchange/name)
* SEC ``company_tickers.json`` (registrant ticker -> CIK), cached by Intelligence at
  ``~/.talonx/intelligence/company_tickers.json``

Every symbol ends in exactly one bucket: ELIGIBLE or EXCLUDED:<reason>. Rules are listed in
order; the first matching rule decides. Output is sorted by symbol.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

LISTED_EXCHANGES = ("NYSE", "NASDAQ", "AMEX", "ARCA", "BATS")
_SYMBOL_RE = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")
# instrument-type exclusions by issue name (case-insensitive). ADRs ("American Depositary") are kept.
_NAME_RULES: tuple[tuple[str, re.Pattern], ...] = (
    ("FUND_ETF_ETN", re.compile(r"\b(ETFs?|ETNs?|Fund|Index|iShares|ProShares|Direxion|SPDR|Leveraged|Inverse)\b", re.I)),
    ("WARRANT", re.compile(r"\bWarrants?\b", re.I)),
    ("RIGHT", re.compile(r"\bRights?\b", re.I)),
    ("UNIT", re.compile(r"\bUnits?\b", re.I)),
    ("PREFERRED", re.compile(r"\bPreferred\b|\bPfd\b|\bSeries [A-Z] Cumulative\b", re.I)),
    ("NOTE_DEBT", re.compile(r"\bNotes?\b|\bDebentures?\b|%", re.I)),
    ("DEPOSITARY_NON_ADR", re.compile(r"(?<!American )Depositary Shares", re.I)),
)


@dataclass(frozen=True)
class UniverseMember:
    symbol: str
    name: str
    exchange: str
    cik: str | None
    status: str          # ELIGIBLE | EXCLUDED
    reason: str          # "" or the exclusion reason code


def _sec_map(company_tickers: dict | list) -> dict[str, str]:
    rows = company_tickers.values() if isinstance(company_tickers, dict) else company_tickers
    out: dict[str, str] = {}
    for r in rows:
        t = str(r.get("ticker", "")).upper()
        if t and t not in out:
            out[t] = str(r.get("cik_str", r.get("cik", ""))).zfill(10)
    return out


def classify(asset: dict, sec: dict[str, str]) -> UniverseMember:
    sym = str(asset.get("symbol", "")).upper()
    name = str(asset.get("name", "") or "")
    exch = str(asset.get("exchange", ""))
    cik = sec.get(sym) or sec.get(sym.replace(".", "-"))

    def ex(reason: str) -> UniverseMember:
        return UniverseMember(sym, name, exch, cik, "EXCLUDED", reason)

    if asset.get("class") != "us_equity":
        return ex("NOT_US_EQUITY")
    if asset.get("status") != "active":
        return ex("INACTIVE")
    if not asset.get("tradable"):
        return ex("NOT_TRADABLE")
    if exch not in LISTED_EXCHANGES:
        return ex("NOT_LISTED_EXCHANGE")
    if not _SYMBOL_RE.match(sym):
        return ex("MALFORMED_OR_NON_COMMON_SYMBOL")
    for code, rx in _NAME_RULES:
        if rx.search(name):
            return ex(code)
    if cik is None:
        return ex("NOT_SEC_REGISTRANT_TICKER")
    return UniverseMember(sym, name, exch, cik, "ELIGIBLE", "")


def build_universe(assets: list[dict], company_tickers: dict | list) -> list[UniverseMember]:
    sec = _sec_map(company_tickers)
    return sorted((classify(a, sec) for a in assets), key=lambda m: m.symbol)


def summarize(members: list[UniverseMember]) -> dict:
    from collections import Counter
    eligible = [m for m in members if m.status == "ELIGIBLE"]
    return {"total": len(members), "eligible": len(eligible), "excluded": len(members) - len(eligible),
            "excluded_by_reason": dict(sorted(Counter(m.reason for m in members if m.reason).items())),
            "eligible_by_exchange": dict(sorted(Counter(m.exchange for m in eligible).items()))}


def save(members: list[UniverseMember], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"summary": summarize(members), "members": [asdict(m) for m in members]},
                               indent=1), encoding="utf-8")


def load(path: Path) -> list[UniverseMember]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [UniverseMember(**m) for m in raw["members"]]
