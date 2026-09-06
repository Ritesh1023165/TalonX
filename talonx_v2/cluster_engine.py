"""
talonx_v2.cluster_engine -- FROZEN Task 109 insider buy-cluster detector
======================================================================
Implements the Task 107B / Task 109 episode definition EXACTLY:

  * open-market PURCHASE transactions only  (SEC transaction code P)
  * same issuer
  * >= 2 DISTINCT reporting-owner CIKs
  * all filing dates within a rolling 10-TRADING-DAY window
  * greedy, NON-OVERLAPPING episodes per issuer
  * the episode is causally ACTIVE only when the 2nd distinct-owner
    filing is publicly observable (keyed on FILING_DATE)

NOT counted: duplicate transaction rows, multiple transactions by the
same owner as separate insiders, grants / gifts / option exercises /
tax-withholding / automatic-plan / derivative / any non-code-P event.

This mirrors ``research/scripts/task107a_episodes.py::build_episodes``
(the frozen research code) -- window measured in trading-day ordinals,
greedy non-overlapping.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from talonx_v2 import calendar as v2cal
from talonx_v2.config import V2Config


@dataclass(frozen=True)
class PurchaseRecord:
    """One de-duplicated open-market (code P) purchase line."""

    symbol: str
    issuer_cik: str
    owner_cik: str
    filing_date: date
    accession: str = ""
    transaction_date: date | None = None
    transaction_value: float | None = None
    is_officer: bool = False
    is_director: bool = False
    is_ten_percent: bool = False
    transaction_code: str = "P"

    def dedupe_key(self) -> tuple:
        return (
            self.accession, self.owner_cik, self.transaction_date,
            round(self.transaction_value or 0.0, 2),
        )


@dataclass
class ClusterEpisode:
    episode_id: str
    symbol: str
    issuer_cik: str
    distinct_owner_ciks: tuple[str, ...]
    n_distinct_owners: int
    n_filings: int
    first_filing_date: date
    activation_filing_date: date          # filing_date of the 2nd distinct owner (episode "fires")
    last_filing_date: date
    aggregate_purchase_value: float
    any_officer: bool
    any_director: bool
    any_ten_percent: bool
    # causal instant the signal became knowable = end of the activation filing day
    causal_event_ts: datetime
    eligible_entry_session: date         # first NYSE session strictly after causal_event_ts

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["distinct_owner_ciks"] = list(self.distinct_owner_ciks)
        for k in ("first_filing_date", "activation_filing_date", "last_filing_date",
                  "eligible_entry_session"):
            d[k] = d[k].isoformat()
        d["causal_event_ts"] = self.causal_event_ts.isoformat()
        return d


def _episode_id(symbol: str, owner_ciks: tuple[str, ...],
                first_filing: date, activation_filing: date) -> str:
    payload = "|".join([
        symbol.upper(),
        ",".join(sorted(owner_ciks)),
        first_filing.isoformat(),
        activation_filing.isoformat(),
    ])
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _dedupe(records: list[PurchaseRecord]) -> list[PurchaseRecord]:
    seen: set[tuple] = set()
    out: list[PurchaseRecord] = []
    for r in sorted(records, key=lambda x: (x.filing_date, x.owner_cik, x.accession)):
        k = r.dedupe_key()
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def detect_episodes_for_issuer(
    records: list[PurchaseRecord], *, config: V2Config | None = None,
) -> list[ClusterEpisode]:
    """Greedy non-overlapping >=2-distinct-owner code-P buy-cluster
    episodes for ONE issuer.  ``records`` may include non-P rows / dupes /
    same-owner repeats -- they are filtered here."""
    cfg = config or V2Config()
    recs = [r for r in records if (r.transaction_code or "").upper() == cfg.transaction_code
            and r.owner_cik and r.filing_date is not None]
    recs = _dedupe(recs)
    if len(recs) < cfg.min_distinct_owners:
        return []

    # trading-day ordinal of each filing_date (anchor on the next session
    # if the filing landed on a weekend/holiday -- the window is a
    # trading-day span, exactly as the research code measures it)
    def ordv(d: date) -> int:
        return v2cal._sessions().index(v2cal.next_session_on_or_after(d))

    recs.sort(key=lambda r: (r.filing_date, r.owner_cik))
    ords = [ordv(r.filing_date) for r in recs]

    episodes: list[ClusterEpisode] = []
    i = 0
    n = len(recs)
    while i < n:
        start_ord = ords[i]
        j = i + 1
        owners: dict[str, date] = {recs[i].owner_cik: recs[i].filing_date}
        while j < n and (ords[j] - start_ord) <= cfg.cluster_window_trading_days:
            owners.setdefault(recs[j].owner_cik, recs[j].filing_date)
            j += 1
        window = recs[i:j]
        distinct = list(dict.fromkeys(r.owner_cik for r in window))
        if len(distinct) >= cfg.min_distinct_owners:
            # activation = filing_date at which the min_distinct_owners-th
            # DISTINCT owner first appears (chronological)
            seen: list[str] = []
            activation_fd = window[-1].filing_date
            for r in window:
                if r.owner_cik not in seen:
                    seen.append(r.owner_cik)
                    if len(seen) == cfg.min_distinct_owners:
                        activation_fd = r.filing_date
                        break
            qualifying = [r for r in window if r.filing_date <= activation_fd]
            owner_ids = tuple(dict.fromkeys(r.owner_cik for r in qualifying))
            agg_val = round(sum(r.transaction_value or 0.0 for r in qualifying
                                if (r.transaction_value or 0.0) > 0), 2)
            causal_ts = datetime.combine(activation_fd, datetime.max.time().replace(microsecond=0),
                                         tzinfo=timezone.utc)
            entry = v2cal.next_session_strictly_after(activation_fd)
            ep = ClusterEpisode(
                episode_id=_episode_id(recs[i].symbol, owner_ids,
                                       window[0].filing_date, activation_fd),
                symbol=recs[i].symbol.upper(),
                issuer_cik=recs[i].issuer_cik,
                distinct_owner_ciks=owner_ids,
                n_distinct_owners=len(owner_ids),
                n_filings=len(qualifying),
                first_filing_date=window[0].filing_date,
                activation_filing_date=activation_fd,
                last_filing_date=qualifying[-1].filing_date,
                aggregate_purchase_value=agg_val,
                any_officer=any(r.is_officer for r in qualifying),
                any_director=any(r.is_director for r in qualifying),
                any_ten_percent=any(r.is_ten_percent for r in qualifying),
                causal_event_ts=causal_ts,
                eligible_entry_session=entry,
            )
            episodes.append(ep)
            # greedy: consume the whole window we scanned
            i = j
        else:
            i += 1
    return episodes


def detect_episodes(
    records: list[PurchaseRecord], *, config: V2Config | None = None,
) -> list[ClusterEpisode]:
    """All issuers.  Groups by symbol, then delegates."""
    by_sym: dict[str, list[PurchaseRecord]] = {}
    for r in records:
        by_sym.setdefault(r.symbol.upper(), []).append(r)
    out: list[ClusterEpisode] = []
    for sym in sorted(by_sym):
        out.extend(detect_episodes_for_issuer(by_sym[sym], config=config))
    out.sort(key=lambda e: (e.eligible_entry_session, e.symbol))
    return out
