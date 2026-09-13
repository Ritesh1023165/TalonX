"""talonx_ops.official_dispatch -- Task 100B Phase 7.

ONE logical official external-send path, expressed as an adapter/router
boundary -- **not** a destructive merge of the three delivery stores Task 100A
found (Original ``dispatch_audit.db`` / Experimental ``exp_alerts.db`` /
Task 96F ``ingestion_ledger.db.intelligence_delivery``). Those stay separate,
each owning its own durable audit history.

What this module adds is a single, explicit decision point:

    router.decide(family, dedup_key) -> RoutingDecision

* Experimental families are ALWAYS ``eligible=False`` (routes to nothing) --
  this is :func:`talonx_signals.external_boundary.is_external_eligible`, stated
  once, here, for any caller.
* Original / approved Task 96 families are eligible per Original's own existing
  policy (unchanged) -- the router does not override it, it just names it.
* Dedup: the router asks each family's OWN store "have you already delivered
  this dedup_key?" via a read-only probe -- it never writes across stores and
  never rewrites history into one DB. "One logical alert, delivered once."

The actual send still happens where it always has (``DispatchAgent`` /
``ExperimentalDispatcher`` [dry-run] / the dormant 96F pipeline); Task 100B
does not move it. Task99H escaping, outbox semantics and retry/backoff are
therefore untouched. This module makes the *routing* explicit and testable.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from talonx_signals.external_boundary import is_external_eligible

_HOME = Path.home() / ".talonx"

# family -> (db relative to home, table, dedup column)
_FAMILY_STORE = {
    "original": ("dispatch_audit.db", "alerts", "dedup_key"),
    "official": ("dispatch_audit.db", "alerts", "dedup_key"),
    "actionable_alert": ("dispatch_audit.db", "alerts", "dedup_key"),
    "long_term_alert": ("dispatch_audit.db", "long_term_alerts", "id"),
    "radar": ("experimental/exp_alerts.db", "radar_alerts", "radar_id"),
    "radar_alerts": ("experimental/exp_alerts.db", "radar_alerts", "radar_id"),
    "event_update": ("experimental/exp_alerts.db", "event_updates", "event_id"),
    "event_updates": ("experimental/exp_alerts.db", "event_updates", "event_id"),
    "intelligence_card": ("ingestion_ledger.db", "intelligence_delivery", "card_id"),
}


@dataclass(frozen=True)
class RoutingDecision:
    family: str
    eligible: bool
    already_delivered: bool
    path: str                     # "official_telegram" | "none"
    reason: str
    origin: str = "PRODUCT_WATCHLIST"   # Task 131 Directive 5

    @property
    def should_send(self) -> bool:
        return self.eligible and not self.already_delivered


# Task 131 Directive 5: an explicit, env-driven, OFF-by-default toggle. A
# BROAD_DISCOVERY-origin alert (Task 131 Directive 4's expanded SEC-
# ingestion scope) is a SEPARATE, independent gate from V2Service's own
# execution_allowlist -- both must be explicitly enabled before a
# broad-discovery alert ever reaches a real Telegram send. Unset/false
# preserves EXACTLY the pre-Task-131 routing behaviour for every existing
# caller (none of which ever pass ``origin``).
ORIGIN_PRODUCT_WATCHLIST = "PRODUCT_WATCHLIST"
ORIGIN_BROAD_DISCOVERY = "BROAD_DISCOVERY"


def broad_discovery_dispatch_enabled() -> bool:
    import os
    return os.environ.get("TALONX_DISPATCH_ENABLE_BROAD_DISCOVERY", "").strip().lower() in (
        "1", "true", "yes", "on")

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family, "eligible": self.eligible,
            "already_delivered": self.already_delivered, "path": self.path,
            "reason": self.reason, "should_send": self.should_send,
        }


def _ro(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1.0)
        con.row_factory = sqlite3.Row
        return con
    except sqlite3.Error:
        return None


class OfficialExternalRouter:
    """The single routing-decision authority for official external sends.

    ``delivered_probe`` -- optional override ``(family, dedup_key) -> bool`` for
    tests; by default the router reads each family's own store read-only.
    """

    OFFICIAL_PATH = "official_telegram"
    NO_PATH = "none"

    def __init__(
        self,
        *,
        home: Path | None = None,
        delivered_probe: Callable[[str, str], bool] | None = None,
    ) -> None:
        self.home = home or _HOME
        self._delivered_probe = delivered_probe

    # -- dedup: ask the family's OWN store, never merge --------------------
    def already_delivered(self, family: str, dedup_key: str) -> bool:
        if self._delivered_probe is not None:
            try:
                return bool(self._delivered_probe(family, dedup_key))
            except Exception:  # noqa: BLE001
                return False
        spec = _FAMILY_STORE.get((family or "").strip().lower())
        if not spec or not dedup_key:
            return False
        rel, table, col = spec
        con = _ro(self.home / rel)
        if con is None:
            return False
        try:
            cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
            if col not in cols:
                # fall back to a generic id column if present
                col = "id" if "id" in cols else (cols[0] if cols else None)
                if col is None:
                    return False
            sent_cols = [c for c in ("telegram_sent", "sent", "delivered") if c in cols]
            where = f"{col}=?"
            if sent_cols:
                where += " AND " + " AND ".join(f"{c}=1" for c in sent_cols)
            row = con.execute(f"SELECT 1 FROM {table} WHERE {where} LIMIT 1", (dedup_key,)).fetchone()
            return row is not None
        except sqlite3.Error:
            return False
        finally:
            con.close()

    # -- the decision ----------------------------------------------------
    def decide(self, family: str, dedup_key: str = "", *,
              origin: str = ORIGIN_PRODUCT_WATCHLIST) -> RoutingDecision:
        fam = (family or "").strip().lower()
        if not is_external_eligible(fam):
            return RoutingDecision(
                family=fam, eligible=False, already_delivered=False, path=self.NO_PATH,
                reason=("experimental family -- structurally internal-only (Phase 6)"
                        if fam else "unknown family -- fail-closed (not eligible)"),
                origin=origin,
            )
        # Task 131 Directive 5: a BROAD_DISCOVERY-origin alert needs its OWN
        # explicit toggle, independent of the ingestion-side one (Directive
        # 4) and independent of V2Service's own execution_allowlist -- a
        # defense-in-depth gate specifically at the external-send boundary.
        if origin == ORIGIN_BROAD_DISCOVERY and not broad_discovery_dispatch_enabled():
            return RoutingDecision(
                family=fam, eligible=False, already_delivered=False, path=self.NO_PATH,
                reason="BROAD_DISCOVERY-origin alert -- dispatch toggle "
                       "(TALONX_DISPATCH_ENABLE_BROAD_DISCOVERY) is not enabled",
                origin=origin,
            )
        delivered = self.already_delivered(fam, dedup_key)
        if delivered:
            return RoutingDecision(
                family=fam, eligible=True, already_delivered=True, path=self.NO_PATH,
                reason="already delivered per this family's own store -- no duplicate send",
                origin=origin,
            )
        return RoutingDecision(
            family=fam, eligible=True, already_delivered=False, path=self.OFFICIAL_PATH,
            reason="eligible; not yet delivered; route via the one official Telegram path",
            origin=origin,
        )

    # -- observability -------------------------------------------------
    def delivery_stores(self) -> dict[str, str]:
        """The three separate, non-merged stores this router routes across."""
        return {
            "original": str(self.home / "dispatch_audit.db"),
            "experimental": str(self.home / "experimental" / "exp_alerts.db"),
            "intelligence_96f": str(self.home / "ingestion_ledger.db") + " :: intelligence_delivery",
        }
