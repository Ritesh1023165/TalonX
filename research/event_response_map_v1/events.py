"""EVENT_RESPONSE_MAP_V1 C3/C4 -- event extraction and causal entry mapping (pure functions, synthetic-testable)."""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ET = ZoneInfo("America/New_York")
UTC = timezone.utc
DEV_START, DEV_END = date(2019, 1, 2), date(2023, 12, 29)
GAP_THRESHOLDS = (3, 5, 10)
EIGHT_K_ITEMS = ("2.02", "1.01", "5.02", "7.01", "8.01")
HORIZONS = {"H0": 0, "H1": 1, "H3": 3, "H5": 5, "H10": 10}
EVENT_TYPES = tuple([f"GAP_UP_{t}" for t in GAP_THRESHOLDS] + [f"GAP_DOWN_{t}" for t in GAP_THRESHOLDS]
                    + [f"8K_{i}" for i in EIGHT_K_ITEMS] + ["FORM4_CLUSTER", "NO_EVENT"])
NON_NOMINATABLE = ("FORM4_CLUSTER", "NO_EVENT")
CONTROL_SEED = 670067
CONTROL_EXCLUSION_SESSIONS = 2


def session_open_utc(d: date) -> datetime:
    return datetime.combine(d, time(9, 30), ET).astimezone(UTC)


def entry_session(causal_utc: datetime, sessions: list[date]) -> date | None:
    """First session whose 09:30 ET open is STRICTLY after the causal instant."""
    for d in sessions:
        if session_open_utc(d) > causal_utc:
            return d
    return None


def edgar_acceptance_causal(raw: str) -> datetime:
    """EDGAR acceptanceDateTime is labelled 'Z' but its zone has been inconsistent across EDGAR surfaces. Locked rule
    (CONSERVATIVE_DUAL_INTERPRETATION): take the LATER of the UTC reading and the ET reading -- causal under either."""
    naive = datetime.fromisoformat(raw.replace("Z", "").split(".")[0])
    return max(naive.replace(tzinfo=UTC), naive.replace(tzinfo=ET).astimezone(UTC))


def gap_events(bars: pd.DataFrame, sessions: list[date]) -> pd.DataFrame:
    """bars: ALL-adjusted [symbol, date, open, close]. Gap on D needs a bar on D and on the previous MARKET session.
    The gap is observable only at D's opening print, so (strict entry rule) entry = open of the NEXT session."""
    nxt = {d: sessions[i + 1] for i, d in enumerate(sessions[:-1])}
    prev = {d: sessions[i - 1] for i, d in enumerate(sessions) if i}
    out = []
    for sym, g in bars.sort_values("date").groupby("symbol", sort=True):
        close = dict(zip(g["date"], g["close"]))
        for d, o in zip(g["date"], g["open"]):
            p = prev.get(d)
            if p is None or p not in close or not (DEV_START <= d <= DEV_END) or d not in nxt:
                continue
            gap = o / close[p] - 1.0
            for t in GAP_THRESHOLDS:
                if gap >= t / 100:
                    out.append({"event_type": f"GAP_UP_{t}", "symbol": sym, "event_date": d, "entry_date": nxt[d], "gap": gap})
                if gap <= -t / 100:
                    out.append({"event_type": f"GAP_DOWN_{t}", "symbol": sym, "event_date": d, "entry_date": nxt[d], "gap": gap})
    return pd.DataFrame(out, columns=["event_type", "symbol", "event_date", "entry_date", "gap"])


def eight_k_events(filings: pd.DataFrame, cik_to_symbol: dict, sessions: list[date]) -> pd.DataFrame:
    """filings: [cik, form, filingDate, acceptanceDateTime, items]. 8-K only (8-K/A excluded). Filings dated after
    the development period are dropped at parse time before any field is used."""
    out = []
    for r in filings.itertuples(index=False):
        fd = date.fromisoformat(str(r.filingDate)[:10])
        if r.form != "8-K" or not (DEV_START <= fd <= DEV_END):
            continue
        sym = cik_to_symbol.get(str(r.cik).zfill(10))
        if not sym:
            continue
        causal = edgar_acceptance_causal(str(r.acceptanceDateTime))
        ent = entry_session(causal, sessions)
        if ent is None:
            continue
        items = {x.strip() for x in str(r.items or "").split(",")}
        for it in EIGHT_K_ITEMS:
            if it in items:
                out.append({"event_type": f"8K_{it}", "symbol": sym, "event_date": fd, "entry_date": ent,
                            "causal_utc": causal.isoformat()})
    return pd.DataFrame(out, columns=["event_type", "symbol", "event_date", "entry_date", "causal_utc"])


def eight_k_events_dated(filings: pd.DataFrame, intervals: dict, sessions: list[date],
                         has_bar) -> tuple[pd.DataFrame, dict]:
    """LOCK REV 3 (R6). filings: [cik, form, filingDate, acceptanceDateTime, items] (development period only).
    Each 8-K is assigned to the ONE ticker valid for its CIK on the FILING DATE via the dated rename chain
    (identity.assign). Bar presence on the entry date is a CONSISTENCY CHECK only:
      AMBIGUOUS (several tickers valid) or NO_VALID_TICKER     -> excluded, counted
      DISAGREE  (assigned ticker has no ALL bar on the entry date but another ticker of the CIK does) -> excluded
      NO_BAR_ANY (no ticker of the CIK has a bar)               -> kept (becomes DATA_MISSING_ENTRY downstream)
    has_bar(symbol, date) -> bool."""
    from research.event_response_map_v1.identity import assign
    counts = {"ASSIGNED_CONSISTENT": 0, "AMBIGUOUS": 0, "NO_VALID_TICKER": 0, "DISAGREE": 0, "NO_BAR_ANY": 0}
    out = []
    for r in filings.itertuples(index=False):
        fd = date.fromisoformat(str(r.filingDate)[:10])
        if r.form != "8-K" or not (DEV_START <= fd <= DEV_END):
            continue
        items = {x.strip() for x in str(r.items or "").split(",")} & set(EIGHT_K_ITEMS)
        if not items:
            continue
        cik = str(r.cik).zfill(10)
        sym, status = assign(cik, fd, intervals)
        if sym is None:
            counts[status] += len(items)
            continue
        causal = edgar_acceptance_causal(str(r.acceptanceDateTime))
        ent = entry_session(causal, sessions)
        if ent is None:
            continue
        if not has_bar(sym, ent):
            others = [s for s, _, _ in intervals.get(cik, []) if s != sym and has_bar(s, ent)]
            if others:
                counts["DISAGREE"] += len(items)
                continue
            counts["NO_BAR_ANY"] += len(items)
        else:
            counts["ASSIGNED_CONSISTENT"] += len(items)
        for it in sorted(items):
            out.append({"event_type": f"8K_{it}", "symbol": sym, "event_date": fd, "entry_date": ent,
                        "causal_utc": causal.isoformat()})
    return pd.DataFrame(out, columns=["event_type", "symbol", "event_date", "entry_date", "causal_utc"]), counts


def form4_rows_dated(rows: list[dict], intervals: dict) -> tuple[list[dict], dict]:
    """LOCK REV 3 (R6) Form 4 symbol mapping: the row's symbol is the ticker valid for its ISSUER CIK on the filing
    date (dated rule). The reported issuer trading symbol must agree (normalized), else DISAGREE -> excluded.
    AMBIGUOUS / NO_VALID_TICKER / CIK_NOT_IN_UNIVERSE -> excluded. All counted."""
    from research.event_response_map_v1.identity import assign, norm_ticker
    counts = {"MATCH": 0, "DISAGREE": 0, "AMBIGUOUS": 0, "NO_VALID_TICKER": 0, "CIK_NOT_IN_UNIVERSE": 0}
    out = []
    for r in rows:
        cik = str(r.get("issuer_cik") or "").zfill(10)
        if cik not in intervals:
            counts["CIK_NOT_IN_UNIVERSE"] += 1
            continue
        fd = r["filing_date"] if isinstance(r["filing_date"], date) else date.fromisoformat(str(r["filing_date"])[:10])
        sym, status = assign(cik, fd, intervals)
        if sym is None:
            counts[status] += 1
            continue
        if norm_ticker(r.get("issuer_sym")) != sym:
            counts["DISAGREE"] += 1
            continue
        counts["MATCH"] += 1
        out.append({**r, "issuer_sym": sym})
    return out, counts


def form4_cluster_events(episodes: list, sessions: list[date]) -> pd.DataFrame:
    """episodes: talonx_v2.cluster_engine.ClusterEpisode (V2@1, unchanged). Causal = end of the activation filing
    day (23:59:59 ET) -> entry = next session open."""
    out = []
    for e in episodes:
        if not (DEV_START <= e.activation_filing_date <= DEV_END):
            continue
        causal = datetime.combine(e.activation_filing_date, time(23, 59, 59), ET).astimezone(UTC)
        ent = entry_session(causal, sessions)
        if ent is not None:
            out.append({"event_type": "FORM4_CLUSTER", "symbol": e.symbol, "event_date": e.activation_filing_date,
                        "entry_date": ent})
    return pd.DataFrame(out, columns=["event_type", "symbol", "event_date", "entry_date"])


def dedup(ev: pd.DataFrame) -> pd.DataFrame:
    return ev.drop_duplicates(["event_type", "symbol", "entry_date"]).sort_values(
        ["event_type", "entry_date", "symbol"]).reset_index(drop=True)


def attach_bucket(ev: pd.DataFrame, elig: pd.DataFrame) -> pd.DataFrame:
    """Keep only events whose symbol is eligible on the ENTRY session (D-1 data relative to entry)."""
    e = elig[elig["eligible"]][["symbol", "date", "bucket"]].rename(columns={"date": "entry_date"})
    return ev.merge(e, on=["symbol", "entry_date"], how="inner")


def no_event_control(events: pd.DataFrame, elig: pd.DataFrame, sessions: list[date], seed: int = CONTROL_SEED) -> pd.DataFrame:
    """For each (entry_date, bucket) with k distinct event symbols, draw k eligible symbols of that bucket on that
    date with NO event of any type whose entry is within +/-2 sessions. Sorted candidates; one RNG, fixed order."""
    idx = {d: i for i, d in enumerate(sessions)}
    busy = set()
    for s, d in events[["symbol", "entry_date"]].drop_duplicates().itertuples(index=False):
        i = idx[d]
        for j in range(max(0, i - CONTROL_EXCLUSION_SESSIONS), min(len(sessions), i + CONTROL_EXCLUSION_SESSIONS + 1)):
            busy.add((s, sessions[j]))
    pool = elig[elig["eligible"]].groupby(["date", "bucket"])["symbol"].apply(lambda x: sorted(set(x))).to_dict()
    need = events.drop_duplicates(["symbol", "entry_date"]).groupby(["entry_date", "bucket"]).size()
    rng = np.random.default_rng(seed)
    out = []
    for (d, b), k in need.sort_index().items():
        cand = [s for s in pool.get((d, b), []) if (s, d) not in busy]
        if not cand:
            continue
        pick = rng.choice(len(cand), size=min(int(k), len(cand)), replace=False)
        out += [{"event_type": "NO_EVENT", "symbol": cand[i], "event_date": d, "entry_date": d, "bucket": b}
                for i in sorted(pick)]
    return pd.DataFrame(out, columns=["event_type", "symbol", "event_date", "entry_date", "bucket"])


def outcomes(ev: pd.DataFrame, bars: pd.DataFrame, bench: dict[str, pd.DataFrame], symbol_bench: dict,
             sessions: list[date]) -> tuple[pd.DataFrame, dict]:
    """Per event x horizon: raw / SPY-relative / sector-relative gross LONG return, entry OPEN -> exit CLOSE, ALL bars.
    Exit session must be <= DEV_END. Missing ENTRY bar -> DATA_MISSING_ENTRY (dropped, counted). Missing benchmark
    bar -> BENCH_MISSING (dropped, counted). LOCK REV 2 (R3): entry bar present but EXIT bar missing ->
    DATA_MISSING_EXIT, emitted as a row with missing_exit=True and NaN returns, so each cell reports its missing-exit
    rate and the non-gating bound sensitivity. SUSPECT_ADJUSTMENT: any |close_t/close_{t-1} - 1| > 75 % inside
    entry..exit (retained, flagged)."""
    idx = {d: i for i, d in enumerate(sessions)}
    px = {s: g.set_index("date") for s, g in bars.groupby("symbol")}
    bpx = {k: v.set_index("date") for k, v in bench.items()}
    counts = {"DATA_MISSING_ENTRY": 0, "DATA_MISSING_EXIT": 0, "BENCH_MISSING": 0, "BEYOND_DEV_END": 0,
              "SUSPECT_ADJUSTMENT": 0}
    nan = float("nan")
    out = []
    for r in ev.itertuples(index=False):
        g = px.get(r.symbol)
        i0 = idx.get(r.entry_date)
        for h, k in HORIZONS.items():
            if i0 is None or i0 + k >= len(sessions) or sessions[i0 + k] > DEV_END:
                counts["BEYOND_DEV_END"] += 1
                continue
            d1 = sessions[i0 + k]
            if g is None or r.entry_date not in g.index:
                counts["DATA_MISSING_ENTRY"] += 1
                continue
            if d1 not in g.index:
                counts["DATA_MISSING_EXIT"] += 1
                out.append({"event_type": r.event_type, "symbol": r.symbol, "entry_date": r.entry_date,
                            "bucket": r.bucket, "horizon": h, "ret_raw": nan, "ret_spy_rel": nan,
                            "ret_sector_rel": nan, "benchmark": None, "suspect_adjustment": False,
                            "missing_exit": True})
                continue
            ret = g.at[d1, "close"] / g.at[r.entry_date, "open"] - 1.0
            sec = (symbol_bench(r.symbol, r.entry_date) if callable(symbol_bench)        # LOCK REV 3: dated
                   else symbol_bench.get(r.symbol, "SPY"))
            br = {}
            for name in ("SPY", sec):
                b = bpx[name]
                br[name] = (b.at[d1, "close"] / b.at[r.entry_date, "open"] - 1.0
                            if r.entry_date in b.index and d1 in b.index else None)
            if br["SPY"] is None or br[sec] is None:
                counts["BENCH_MISSING"] += 1
                continue
            win = g.loc[[d for d in sessions[max(0, i0 - 1):i0 + k + 1] if d in g.index], "close"]
            suspect = bool((win.pct_change().abs() > 0.75).any())
            counts["SUSPECT_ADJUSTMENT"] += suspect
            out.append({"event_type": r.event_type, "symbol": r.symbol, "entry_date": r.entry_date, "bucket": r.bucket,
                        "horizon": h, "ret_raw": ret, "ret_spy_rel": ret - br["SPY"], "ret_sector_rel": ret - br[sec],
                        "benchmark": sec, "suspect_adjustment": suspect, "missing_exit": False})
    return pd.DataFrame(out), counts


def sic_benchmark(sic, mapping: dict) -> str:
    """SIC_ETF_MAP_V1: first range containing the SIC, else the default (SPY)."""
    try:
        s = int(sic)
    except (TypeError, ValueError):
        return mapping["default"]
    for r in mapping["ranges"]:
        if r["sic_lo"] <= s <= r["sic_hi"]:
            return r["benchmark"]
    return mapping["default"]


