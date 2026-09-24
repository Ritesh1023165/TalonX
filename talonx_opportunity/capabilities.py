"""
Provider capability per market phase (REQ S14-05). Never "SIP works everywhere".

Static capability = what the configured subscription is DEMONSTRATED to provide (2026-09-24 probes, recorded in
docs/research/evidence/SESSION04_MISSED_OPPORTUNITY_FORENSIC.md s5). Effective capability = static capability
downgraded by the latest live probe (DATA_INGESTION records a probe per phase; a failed probe makes that phase
UNAVAILABLE until the next successful probe). A phase that is not usable fails CLOSED for discovery only -- every
other phase / component keeps running.

OVERNIGHT: consolidated SIP has NO overnight bars. BOATS (Blue Ocean ATS) has overnight bars but is a SINGLE VENUE,
sparse (median 4 bars/night for Session-04 actionable movers) and not the SIP economic contract -> recorded as an
alternative, DISABLED, never mixed into SIP discovery.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace

from talonx_opportunity.phases import AFTER_HOURS, CLOSED, OVERNIGHT, PREMARKET, REGULAR

AVAILABLE = "AVAILABLE"
NOT_SUPPORTED = "NOT_SUPPORTED"
DISABLED = "DISABLED"
UNAVAILABLE = "UNAVAILABLE"          # supported in principle, but the latest live probe failed
NO_SESSION = "NO_SESSION"

RESEARCH_ONLY = "RESEARCH_ONLY_NO_EXECUTION"


@dataclass(frozen=True)
class PhaseCapability:
    phase: str
    provider: str
    feed: str
    realtime: bool
    delay_minutes: int | None
    adjustment: str | None
    consolidated: bool
    completeness: str            # COMPLETE | SPARSE_SINGLE_VENUE | NONE
    availability: str            # AVAILABLE | NOT_SUPPORTED | DISABLED | UNAVAILABLE | NO_SESSION
    execution: str               # what may act on it (research lane: never executes)
    evidence: str

    @property
    def usable_for_discovery(self) -> bool:
        return self.availability == AVAILABLE and self.consolidated and self.completeness == "COMPLETE"

    def as_dict(self) -> dict:
        return {**asdict(self), "usable_for_discovery": self.usable_for_discovery}


_SIP = dict(provider="alpaca", feed="sip", realtime=False, delay_minutes=15, adjustment="split", consolidated=True,
            completeness="COMPLETE", availability=AVAILABLE, execution=RESEARCH_ONLY)
_PROBE = "demonstrated 2026-09-24 (Session-04 forensic s5): SIP 1Min bars present, 15-min delay (403 if newer)"

STATIC_CAPABILITIES: dict[str, PhaseCapability] = {
    PREMARKET: PhaseCapability(PREMARKET, evidence=_PROBE, **_SIP),
    REGULAR: PhaseCapability(REGULAR, evidence=_PROBE, **_SIP),
    AFTER_HOURS: PhaseCapability(AFTER_HOURS, evidence=_PROBE, **_SIP),
    OVERNIGHT: PhaseCapability(OVERNIGHT, provider="alpaca", feed="sip", realtime=False, delay_minutes=None,
                               adjustment="split", consolidated=True, completeness="NONE",
                               availability=NOT_SUPPORTED, execution=RESEARCH_ONLY,
                               evidence="2026-09-24 probe: SIP returns NO bars 20:00-04:00 ET"),
    CLOSED: PhaseCapability(CLOSED, provider="none", feed="none", realtime=False, delay_minutes=None, adjustment=None,
                            consolidated=False, completeness="NONE", availability=NO_SESSION, execution="NONE",
                            evidence="no XNYS extended/regular/overnight session"),
}

# Observed alternative -- NEVER used for discovery (different economic contract).
OVERNIGHT_ALTERNATIVES: dict[str, PhaseCapability] = {
    "boats": PhaseCapability(OVERNIGHT, provider="alpaca", feed="boats", realtime=False, delay_minutes=15,
                             adjustment="split", consolidated=False, completeness="SPARSE_SINGLE_VENUE",
                             availability=DISABLED, execution="NONE",
                             evidence="2026-09-24 probe: bars exist (Blue Ocean ATS single venue, sparse); recent "
                                      "data 403; not the SIP contract -> disabled for discovery"),
}


def effective_capability(phase: str, probe: dict | None = None) -> PhaseCapability:
    """``probe``: the latest DATA_INGESTION probe row for the phase ({"ok": bool, "at_utc": ..., "detail": ...})."""
    cap = STATIC_CAPABILITIES.get(phase, STATIC_CAPABILITIES[CLOSED])
    if cap.availability == AVAILABLE and probe is not None and not probe.get("ok", False):
        return replace(cap, availability=UNAVAILABLE,
                       evidence=f"latest probe failed at {probe.get('at_utc')}: {probe.get('detail')}")
    return cap


def capability_table(probes: dict[str, dict] | None = None) -> list[dict]:
    probes = probes or {}
    rows = [effective_capability(p, probes.get(p)).as_dict() for p in (OVERNIGHT, PREMARKET, REGULAR, AFTER_HOURS)]
    rows += [{**c.as_dict(), "alternative": True} for c in OVERNIGHT_ALTERNATIVES.values()]
    return rows
