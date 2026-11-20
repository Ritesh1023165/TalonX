"""V2 passive record (owner decision 2026-11-20).

``INSIDER_BUY_CLUSTER_V2@1`` was closed as ``V2_NO_EDGE_CONFIRMED`` (2026-11-01 forward closeout). The companion keeps
running as a passive, read-only descriptive record of insider-buy clusters (episodes, paper ledger, dashboard), but V2
sends nothing: no BUY/SELL alert to the Signal bot and no V2-produced OPERATIONS notification, whatever flags the
companion is started with. The shared OPERATIONS outbox (other components' messages) is still drained by the companion.

Deliberately outside ``V2Config``: the frozen strategy fingerprint (``e2acf6454789217e``) does not change.
"""
from __future__ import annotations

V2_PASSIVE = True
SUPPRESS_REASON = ("SUPPRESSED_V2_PASSIVE: owner decision 2026-11-20 -- V2 is a passive descriptive record; "
                   "no V2 message is ever sent")
_UNSENT = ("PENDING", "RETRY", "HELD")


def suppress_outbox(store) -> dict:
    """Retire every not-yet-sent V2 alert as EXPIRED with an explicit reason (idempotent; terminal, so a later change of
    configuration can never replay it). SENT / FAILED / EXPIRED / AMBIGUOUS rows are left exactly as they are."""
    rows = [r for r in store.all_outbox() if r["state"] in _UNSENT]
    for r in rows:
        store.update_outbox(r["event_id"], state="EXPIRED", last_error=SUPPRESS_REASON)
    return {"transport": "PASSIVE", "considered": len(rows), "sent": 0, "suppressed": len(rows)}
