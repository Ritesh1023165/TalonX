"""ERM nominee correction rules V2.1 -- PURE functions (no I/O, no prices differenced across time, no outcomes).

Used by v2_manifest.py (metadata manifest) and tests/test_erm_nominee_v2_rules.py (fixtures). Every rule decides from
evidence dated on/before the gap day D (or from retrospective records of facts that applied on D) and never from
holding-period outcomes.

Evidence types (inputs):
  edges        [(old_ticker, new_ticker, process_date)]  dated rename records (provider corporate actions)
  f345         {ticker: [(filing_date, issuer_cik)]}     dated issuer-trading-symbol observations (Form 3/4/5)
  vol          {date: raw_volume}                        one requested series (archive), dates = sessions
  sp_rows      [(list_date, {tickers})]                  point-in-time S&P 500 lists
"""
from __future__ import annotations

from bisect import bisect_right
from datetime import date, timedelta

RULES_VERSION = "ERM_NOMINEE_CORRECTION_V2.1"
SENSITIVITY_LABEL = "NO_DETECTED_STOCK_ADJUSTMENT_OR_ETF_CASH_DIVIDEND"

ZERO_RUN_BREAK = 5           # >= 5 consecutive zero-volume sessions = a break in a series' trading continuity
PRICE_TOL = 0.005            # raw prices are quoted in cents: identical series agree within half a cent
MIN_COMMON_TRADED = 20       # duplicate corroboration needs >= 20 common positive-volume sessions
S_P_EVIDENCE_FROM = date(2018, 1, 1)   # dated Form 3/4/5 evidence begins 2018Q1 (archived + 2018 acquisition)
FACTOR_TOL_ABS = 0.0051      # |ALL - m*RAW| per price: half-cent raw rounding (<= 0.005*m <= 0.005) + 0.0001 ALL rounding


# ------------------------------------------------------------------------------------------------ identity
def ticker_at(symbol: str, d: date, edges: list) -> tuple[str | None, list, str | None]:
    """Ticker under which the REQUESTED series traded on d.

    The provider resolves a requested symbol to its holder on the download day and relabels that holder's predecessor
    tickers (documented `asof` behaviour). A symbol renamed away after its last rename-in has no download-day holder
    through that chain (raw-symbol history; no relabelling). Walk rename-INTO edges dated after d backwards.
    Returns (ticker, chain_of_edges_used, problem)."""
    into, out = {}, {}
    for o, n, pd_ in edges:
        into.setdefault(n, []).append((pd_, o))
        out.setdefault(o, []).append(pd_)
    t, chain, seen = symbol, [], {symbol}
    last_in = max((x for x, _ in into.get(symbol, [])), default=None)
    if last_in is not None and any(x > last_in for x in out.get(symbol, [])):
        return symbol, [], None                       # renamed away after its last rename-in: raw-symbol history
    bound = None                                       # a predecessor edge must PRECEDE the edge it feeds: an
    while True:                                        # in-edge dated after the out-edge is a later ticker REUSE
        later = sorted((pd_, o) for pd_, o in into.get(t, []) if pd_ > d and (bound is None or pd_ < bound))
        if not later:
            return t, chain, None
        if len({o for _, o in later}) > 1:
            return None, chain, "AMBIGUOUS_RELABEL_CHAIN"
        pd_, o = later[0]
        if o in seen:
            return None, chain, "CYCLIC_RELABEL_CHAIN"
        chain.append((o, t, pd_))
        seen.add(o)
        t, bound = o, pd_


def zero_run_between(vol: dict, a: date, b: date) -> bool:
    """True if the series has >= ZERO_RUN_BREAK consecutive zero-volume sessions with dates in (a, b]."""
    run = 0
    for d_ in sorted(x for x in vol if a < x <= b):
        run = run + 1 if vol[d_] == 0 else 0
        if run >= ZERO_RUN_BREAK:
            return True
    return False


def identity_at(symbol: str, d: date, edges: list, f345: dict, vol: dict) -> dict:
    """VERIFIED_HISTORICAL_IDENTITY  issuer = issuer of the latest dated Form 3/4/5 observation of the ticker the series
                                     traded under on d, with (i) no rename-out of that ticker and (ii) no break in the
                                     series' trading (zero-volume run) between that observation and d.
       UNRESOLVED_IDENTITY           ABSENT (no dated observation <= d) or CONTRADICTORY (ambiguous chain, two issuers on
                                     the latest observation date, rename-out or trading break after the evidence)."""
    t, chain, prob = ticker_at(symbol, d, edges)
    res = {"ticker_at_D": t, "relabel_chain": chain, "issuer": None, "evidence_date": None}
    if prob:
        return {**res, "identity": "UNRESOLVED_IDENTITY", "reason": "CONTRADICTORY:" + prob}
    obs = [(fd, c) for fd, c in f345.get(t, []) if fd <= d]
    if not obs:
        return {**res, "identity": "UNRESOLVED_IDENTITY", "reason": "ABSENT:NO_DATED_TICKER_EVIDENCE"}
    fd = max(x for x, _ in obs)
    issuers = {c for x, c in obs if x == fd}
    if len(issuers) > 1:
        return {**res, "identity": "UNRESOLVED_IDENTITY", "reason": "CONTRADICTORY:TWO_ISSUERS_SAME_DATE"}
    for o, n, pd_ in edges:
        if o == t and fd < pd_ <= d:
            return {**res, "identity": "UNRESOLVED_IDENTITY", "reason": "CONTRADICTORY:RENAMED_AWAY_AFTER_EVIDENCE"}
    if zero_run_between(vol, fd, d):
        return {**res, "identity": "UNRESOLVED_IDENTITY", "reason": "CONTRADICTORY:TRADING_BREAK_AFTER_EVIDENCE"}
    return {**res, "issuer": next(iter(issuers)), "evidence_date": fd, "identity": "VERIFIED_HISTORICAL_IDENTITY",
            "reason": "DATED_F345" + ("+RENAME_RECORDS" if chain else "")}


def mapping_class(identity: dict, frozen_cik: str | None) -> str:
    if identity["identity"] != "VERIFIED_HISTORICAL_IDENTITY":
        return "UNRESOLVED_IDENTITY"
    return "VERIFIED_HISTORICAL_IDENTITY" if identity["issuer"] == frozen_cik else "VERIFIED_DIFFERENT_SECURITY"


# ------------------------------------------------------------------------------------------------ duplicates
def same_series(a: dict, b: dict) -> str:
    """a/b: {'vol': {date: v}, 'open': {date: p}, 'close': {date: p}, 'window': [dates], 'key': [D-1, D, entry]}.
    -> 'NOT_CANDIDATE' | 'DIFFERENT_PRICES' | 'INSUFFICIENT_OVERLAP' | 'SAME_DATA'."""
    if any(a["vol"].get(x) != b["vol"].get(x) or not a["vol"].get(x) for x in a["key"]):
        return "NOT_CANDIDATE"
    common = [x for x in a["window"] if x in a["vol"] and x in b["vol"]]
    if any(a["vol"][x] != b["vol"][x] for x in common):
        return "NOT_CANDIDATE"
    traded = [x for x in common if a["vol"][x] > 0]
    if len(traded) < MIN_COMMON_TRADED:
        return "INSUFFICIENT_OVERLAP"
    for x in traded:
        for f in ("open", "close"):
            pa, pb = a[f].get(x), b[f].get(x)
            if pa is None or pb is None or abs(pa - pb) > PRICE_TOL:
                return "DIFFERENT_PRICES"
    return "SAME_DATA"


def duplicate_link(data_status: str, ident_a: dict, ident_b: dict) -> str:
    """VERIFIED_DUPLICATE   same data AND lineage: both series traded under the SAME ticker on D (rename records)
                            and resolve to the same verified issuer -> the same economic security observed twice.
       UNRESOLVED_DUPLICATE same data, lineage not established (different tickers on D without a rename link, or an
                            unresolved identity) -> conservative exclusion of every member.
       NOT_DUPLICATE        not the same data (different prices / volumes) -> each row judged on its own.
       Share classes of one issuer trade under different tickers with different volumes and prices, so they are
       never merged by issuer alone."""
    if data_status != "SAME_DATA":
        return "NOT_DUPLICATE" if data_status in ("NOT_CANDIDATE", "DIFFERENT_PRICES") else "UNRESOLVED_DUPLICATE"
    ok = (ident_a["identity"] == ident_b["identity"] == "VERIFIED_HISTORICAL_IDENTITY"
          and ident_a["ticker_at_D"] == ident_b["ticker_at_D"] and ident_a["issuer"] == ident_b["issuer"])
    return "VERIFIED_DUPLICATE" if ok else "UNRESOLVED_DUPLICATE"


VERIFIED_DUPLICATE, NOT_DUPLICATE, UNRESOLVED_DUPLICATE = "VERIFIED_DUPLICATE", "NOT_DUPLICATE", "UNRESOLVED_DUPLICATE"
GRAPH_EDGE_CLASSES = (VERIFIED_DUPLICATE, UNRESOLVED_DUPLICATE)   # NOT_DUPLICATE never creates an edge


def duplicate_groups(nodes: list, links: dict) -> tuple[list, set]:
    """nodes: row ids; links: {(i, j): VERIFIED_DUPLICATE | NOT_DUPLICATE | UNRESOLVED_DUPLICATE} for candidate pairs.
    Edges = VERIFIED and UNRESOLVED links only (a NOT_DUPLICATE pair -- e.g. identical volumes but different prices --
    never joins two rows, so it can never cause an otherwise valid row to be excluded).
    Groups = connected components over those edges. A group is accepted only if EVERY pair inside it is
    VERIFIED_DUPLICATE (all-pairs verification; no chaining through partial links). Otherwise every member is
    unresolved -- this covers an UNRESOLVED edge, a pair with no candidate link (different data), and a pair explicitly
    NOT_DUPLICATE inside the same component (a contradiction: identical-to-B but different-from-C).
    -> (verified_groups, unresolved_member_ids)."""
    adj = {n: set() for n in nodes}
    for (i, j), st in links.items():
        if st in GRAPH_EDGE_CLASSES:
            adj[i].add(j)
            adj[j].add(i)
    seen, groups, unresolved = set(), [], set()
    for n in sorted(nodes):
        if n in seen or not adj[n]:
            continue
        comp, stack = set(), [n]
        while stack:
            x = stack.pop()
            if x in comp:
                continue
            comp.add(x)
            stack.extend(adj[x] - comp)
        seen |= comp
        members = sorted(comp)
        ok = all(links.get((a, b), links.get((b, a))) == VERIFIED_DUPLICATE
                 for k, a in enumerate(members) for b in members[k + 1:])
        (groups.append(members) if ok else unresolved.update(members))
    return groups, unresolved


def representative(members: list, info: dict) -> tuple[str, str]:
    """info[id] = {'symbol', 'ticker_at_D', 'traded_in_window'}. Outcome-free choice:
       1 the member requested under the security's own ticker on D;  2 more positive-volume sessions in the 20-session
       window (data quality);  3 lexically smallest symbol (only if still equivalent)."""
    own = [m for m in members if info[m]["symbol"] == info[m]["ticker_at_D"]]
    if len(own) == 1:
        return own[0], "OWN_TICKER_ON_D"
    pool = own or members
    best = max(info[m]["traded_in_window"] for m in pool)
    pool = [m for m in pool if info[m]["traded_in_window"] == best]
    if len(pool) == 1:
        return pool[0], "MORE_TRADED_SESSIONS"
    return sorted(pool, key=lambda m: info[m]["symbol"])[0], "LEXICAL_TIE_BREAK"


# ------------------------------------------------------------------------------------------------ instrument / S&P / R1a
def sp_exempt(ticker: str | None, issuer: str | None, d: date, sp_rows: list, f345: dict, edges: list) -> str:
    """Historical S&P evidence tied to the VERIFIED security: the ticker it traded under on D appears on a point-in-time
    S&P 500 list dated t (S_P_EVIDENCE_FROM <= t <= D), a dated Form 3/4/5 observation links that ticker to the same
    issuer in [t - 365 d, D], and the ticker was neither renamed away nor reported by another issuer in [t, D].
    -> 'VERIFIED' | 'NO_MEMBERSHIP_BY_D' | 'UNVERIFIED_LINK'."""
    if not ticker or not issuer:
        return "UNVERIFIED_LINK"
    dates = [x for x, ts in sp_rows if ticker in ts and S_P_EVIDENCE_FROM.isoformat() <= x <= d.isoformat()]
    if not dates:
        return "NO_MEMBERSHIP_BY_D"
    t = date.fromisoformat(max(dates))
    obs = f345.get(ticker, [])
    link = any(c == issuer and t - timedelta(days=365) <= fd <= d for fd, c in obs)
    other = any(c != issuer and t <= fd <= d for fd, c in obs)
    away = any(o == ticker and t < pd_ <= d for o, _, pd_ in edges)
    return "VERIFIED" if (link and not other and not away) else "UNVERIFIED_LINK"


def r1a_available(periodic_dates: list, d: date) -> bool:
    """Availability-only R1a: a 10-K/10-K/A/10-Q/10-Q/A of the verified issuer with EDGAR filing date <= D, any year."""
    return any(x <= d.isoformat() for x in periodic_dates)


def instrument_status(sic_pit: str | None, sic_filing_date: str | None, transitions: list, sp: str,
                      d: date) -> tuple[str, str]:
    """Operating common-stock / SPAC status on D.

    transitions: [(report_date, filing_date)] of every 8-K reporting item 5.06 (change in shell company status). The
    cessation of shell status c is an EFFECTIVE date with report_date <= c <= filing_date (EDGAR reportDate = the
    earliest event in the 8-K; the filing date = PUBLICATION). A 5.06 says the registrant was a shell immediately
    before c -- it does NOT say since when, so a later 5.06 alone never establishes shell status on an earlier D.

    Evidence hierarchy (first applicable):
      1 cessation established by D: a 5.06 FILED <= D (so c <= D) and not older than the SIC source filing
                                                        -> OPERATING (sector from SIC unless 6770 -> unknown sector)
      2 cessation window straddles D (report_date <= D < filing_date): status on D not determinable from metadata
                                                        -> UNRESOLVED_INSTRUMENT
      3 explicit shell interval covering D: dated SIC 6770 in the header of the latest company filing <= D (interval
        start <= D) with no cessation by D (rules 1-2)  -> SPAC
      4 dated SIC known, not 6770: OPERATING_SECTOR_KNOWN -- unless a 5.06 is effective AFTER D (report_date > D):
        the registrant was a shell at some time before that cessation and no dated evidence fixes when, so
                                                        -> UNRESOLVED_INSTRUMENT
      5 no dated SIC, VERIFIED historical S&P membership by D -> OPERATING_SECTOR_UNKNOWN
      6 otherwise                                       -> UNRESOLVED_INSTRUMENT
    A company name or a current SIC is never evidence. -> (status, sic_used)."""
    dd = d.isoformat()
    filed_by = [f for r, f in transitions if f <= dd]
    straddle = [1 for r, f in transitions if r <= dd < f]
    later = [1 for r, f in transitions if r > dd]
    if filed_by and (not sic_filing_date or max(filed_by) >= sic_filing_date):
        return ("OPERATING_SECTOR_KNOWN", sic_pit) if sic_pit and sic_pit != "6770" else ("OPERATING_SECTOR_UNKNOWN", "")
    if straddle:
        return "UNRESOLVED_INSTRUMENT", ""
    if sic_pit == "6770":
        return "SPAC", sic_pit
    if sic_pit:
        return ("UNRESOLVED_INSTRUMENT", "") if later else ("OPERATING_SECTOR_KNOWN", sic_pit)
    if sp == "VERIFIED":
        return "OPERATING_SECTOR_UNKNOWN", ""
    return "UNRESOLVED_INSTRUMENT", ""


def benchmark(status: str, sic: str, sic_to_etf) -> str:
    """Point-in-time benchmark: frozen SIC_ETF_MAP_V1 on the dated SIC; a known SIC outside the mapped ranges -> SPY
    (the frozen map default); a verified operating stock with unknown sector -> SPY (explicit fallback)."""
    if status == "OPERATING_SECTOR_KNOWN":
        return sic_to_etf(sic)
    if status == "OPERATING_SECTOR_UNKNOWN":
        return "SPY"
    return ""


# ------------------------------------------------------------------------------------------------ adjustment sensitivity
def leg_no_adjustment(bars: list) -> str:
    """bars: [(all_open, raw_open, all_close, raw_close)] for EVERY session from entry through exit (one leg).
    'NO_ADJUSTMENT' iff every observed price satisfies |ALL - m*RAW| <= FACTOR_TOL_ABS, m = median(ALL/RAW) over the
    interval (a step that later reverses still breaks the fit); 'ADJUSTED' otherwise; 'UNKNOWN' if any session lacks a
    raw/ALL pair (missing evidence is never 'no adjustment')."""
    pts = []
    for row in bars:
        if row is None or any(x is None for x in row) or not row[1] or not row[3]:
            return "UNKNOWN"
        pts += [(row[0], row[1]), (row[2], row[3])]
    if not pts:
        return "UNKNOWN"
    r = sorted(a / b for a, b in pts)
    m = r[len(r) // 2] if len(r) % 2 else (r[len(r) // 2 - 1] + r[len(r) // 2]) / 2
    return "NO_ADJUSTMENT" if all(abs(a - m * b) <= FACTOR_TOL_ABS for a, b in pts) else "ADJUSTED"


def sensitivity_member(stock_leg: str, etf_leg: str) -> str:
    """Descriptive subset SENSITIVITY_LABEL = NO_DETECTED_STOCK_ADJUSTMENT_OR_ETF_CASH_DIVIDEND (never gating).
    stock_leg: whole-interval raw/ALL comparison (leg_no_adjustment). etf_leg: provider CASH-DIVIDEND records only --
    other ETF actions are unverified, and absence of a cash-dividend record does not prove absence of all adjustments.
    Missing required evidence -> UNKNOWN (not in the subset)."""
    if stock_leg == "NO_ADJUSTMENT" and etf_leg == "NO_ADJUSTMENT":
        return "IN_SUBSET"
    if "UNKNOWN" in (stock_leg, etf_leg):
        return "UNKNOWN"
    return "OUT_OF_SUBSET"


# ------------------------------------------------------------------------------------------------ first reason
REASON_ORDER = ("BEYOND_WINDOW", "C1_NO_GAP_PLACEHOLDER", "C1_NOT_ELIGIBLE_PLACEHOLDER", "C1_ENTRY_PLACEHOLDER",
                "FROZEN_NOT_ELIGIBLE", "ID_UNRESOLVED", "DUP_UNRESOLVED", "DUP_NOT_REPRESENTATIVE",
                "R1A_NOT_AVAILABLE", "INSTRUMENT_SPAC", "INSTRUMENT_UNRESOLVED", "DATA_MISSING_ENTRY")


def first_reason(flags: set) -> str:
    for r in REASON_ORDER:
        if r in flags:
            return r
    return ""
