"""
talonx_ops.intel_queue -- operator breakdown of the Intelligence delivery queue (Session 03 A5)
===============================================================================================
Read-only. The /ping line used to show ALL-TIME state totals ("pending, sent, expired/held,
failed"), which mixes the live queue with ~47k historical EXPIRED rows produced when the
backlog recovery pass enriches months-old filings (correctly expired by the 24 h DIGEST
staleness cutoff). This separates:

  LIVE_PENDING  -- rows still waiting to send (PENDING/RETRY/IN_FLIGHT), split by route
  LIVE_FAILED   -- FAILED/AMBIGUOUS rows updated in the last 24 h (needs attention)
  HELD          -- rows held (no transport / not qualified); not a failure
  EXPIRED       -- expired in the last 24 h, and all-time (stale-by-design, not a failure)
  DRAIN_RATE    -- SENT in the last 1 h / 24 h
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

_WAITING = ("PENDING", "RETRY", "IN_FLIGHT")


def delivery_queue_breakdown(con, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    d1 = (now - timedelta(hours=24)).isoformat()
    h1 = (now - timedelta(hours=1)).isoformat()
    q = lambda sql, *a: con.execute(sql, a).fetchall()  # noqa: E731
    ph = ",".join("?" * len(_WAITING))
    pending_by_route = {r or "UNKNOWN": n for r, n in q(
        f"SELECT route, COUNT(*) FROM intelligence_delivery WHERE state IN ({ph}) GROUP BY route", *_WAITING)}
    oldest = q(f"SELECT MIN(enqueued_at_utc) FROM intelligence_delivery WHERE state IN ({ph})", *_WAITING)[0][0]
    oldest_min = None
    if oldest:
        try:
            t = datetime.fromisoformat(oldest)
            t = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
            oldest_min = round((now - t).total_seconds() / 60.0, 1)
        except ValueError:
            oldest_min = None

    def count(sql, *a) -> int:
        return int(q(sql, *a)[0][0] or 0)

    return {
        "LIVE_PENDING": sum(pending_by_route.values()),
        "LIVE_PENDING_BY_ROUTE": pending_by_route,
        "LIVE_PENDING_OLDEST_MIN": oldest_min,
        "LIVE_FAILED_24H": count("SELECT COUNT(*) FROM intelligence_delivery WHERE state IN ('FAILED','AMBIGUOUS') "
                                 "AND updated_at_utc >= ?", d1),
        "HELD": count("SELECT COUNT(*) FROM intelligence_delivery WHERE state = 'HELD'"),
        "EXPIRED_24H": count("SELECT COUNT(*) FROM intelligence_delivery WHERE state = 'EXPIRED' "
                             "AND updated_at_utc >= ?", d1),
        "EXPIRED_ALL_TIME": count("SELECT COUNT(*) FROM intelligence_delivery WHERE state = 'EXPIRED'"),
        "SENT_1H": count("SELECT COUNT(*) FROM intelligence_delivery WHERE state = 'SENT' AND sent_at_utc >= ?", h1),
        "SENT_24H": count("SELECT COUNT(*) FROM intelligence_delivery WHERE state = 'SENT' AND sent_at_utc >= ?", d1),
        "LAST_SENT_UTC": q("SELECT MAX(sent_at_utc) FROM intelligence_delivery WHERE state = 'SENT'")[0][0],
    }


def format_breakdown(b: dict) -> list[str]:
    routes = ", ".join(f"{k.lower()} {v}" for k, v in sorted(b["LIVE_PENDING_BY_ROUTE"].items())) or "none"
    oldest = f", oldest {b['LIVE_PENDING_OLDEST_MIN']} min" if b["LIVE_PENDING_OLDEST_MIN"] is not None else ""
    return [
        f"  Discovery informational queue -- LIVE_PENDING: {b['LIVE_PENDING']} ({routes}{oldest}), "
        f"LIVE_FAILED (24h): {b['LIVE_FAILED_24H']}, HELD: {b['HELD']}",
        f"  Drain -- sent 1h: {b['SENT_1H']}, sent 24h: {b['SENT_24H']}; EXPIRED 24h: {b['EXPIRED_24H']} "
        f"(all-time {b['EXPIRED_ALL_TIME']:,}; stale backlog cards expire by design)",
        "  Last successful discovery delivery: " + (b["LAST_SENT_UTC"] or "none in retained history"),
    ]
