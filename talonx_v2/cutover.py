"""
talonx_v2.cutover -- material-version/campaign cutover PENDING-intent
classification (RI-1, RI1-D/E).
======================================================================
Implements the agreed cutover rules (`docs/product/DECISION_LOG.md`
Session 13, "Agreed material-version cutover rules"; restated verbatim
in Task RI-1's own spec):

  1. A material version change moves to a NEW campaign with explicitly
     approved capital (operator action, outside this module -- a new
     campaign is just a `V2Store` opened with a new `campaign_id`/
     `db_path`; see `talonx_v2.store.V2Store`).
  2. The OLD campaign manages existing obligations only -- this module
     never creates admissions, only classifies/resolves what already
     exists.
  3. FUTURE genuinely unfilled intents are cancelled atomically at the
     cutover moment.
  4. TIMELY ADMITTED intents still within their Package-3 recovery
     window remain governed by the OLD campaign/version -- untouched
     here; they resolve through the OLD campaign's own continuing
     service tick (fill / expiry) exactly as they would have without
     any cutover.
  5. Existing positions retain their original rules (this module never
     touches `positions` -- only `pending_entry_intents`).
  6. No historical accounting error is erased -- this module never
     mutates `portfolio`/`campaign`/`trades`/`positions`.

Classification (per PENDING intent, `target_entry_session` = the
episode's own eligible entry session):

  target_entry_session >  as_of_session         -> CANCELLED_CUTOVER
      (genuinely future: the market hasn't even reached this session's
      open yet -- no fill attempt has ever been made or could have
      been).
  target_entry_session <= as_of_session AND
      recovery deadline NOT yet passed            -> RETAINED (no-op;
      remains PENDING, governed by the OLD campaign until fill/expiry
      under its own already-existing lifecycle rules).
  target_entry_session <= as_of_session AND
      recovery deadline HAS passed                -> EXPIRED_RECOVERY_
      DEADLINE (mirrors exactly what the old campaign's own service
      tick would have done on its next run -- not a cutover-specific
      invention, just applied here instead of waiting for a tick that
      may never come if the old campaign's service is being wound
      down).

Any intent NOT in status='PENDING' (already FILLED / EXPIRED_STALE /
EXPIRED_RECOVERY_DEADLINE / SUPERSEDED / CANCELLED_CUTOVER / etc.) is
left completely untouched -- cutover never revives or reinterprets an
already-terminal intent.

IDEMPOTENT: relies on ``V2Store.mark_entry_intent``'s own
``WHERE status='PENDING'`` guard -- a second invocation finds nothing
left to transition (every previously-PENDING row is already terminal),
so it is a safe no-op for row-level state. A fresh audit row is still
appended to ``campaign_cutover_log`` on every call (see
``V2Store.record_cutover``), so repeated/duplicate invocations remain
individually visible for audit even though they change nothing further.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from talonx_v2.calendar import recovery_deadline_passed


@dataclass
class CutoverResult:
    cutover_id: str
    as_of_session: date
    cancelled: list[str] = field(default_factory=list)   # intent_ids
    retained: list[str] = field(default_factory=list)    # intent_ids
    expired: list[str] = field(default_factory=list)      # intent_ids

    @property
    def cancelled_count(self) -> int:
        return len(self.cancelled)

    @property
    def retained_count(self) -> int:
        return len(self.retained)

    @property
    def expired_count(self) -> int:
        return len(self.expired)


def classify_and_cancel_pending_at_cutover(
    store, *, as_of_session: date, max_entry_staleness_sessions: int,
    cutover_id: str, live: bool = False,
) -> CutoverResult:
    """Classify every currently-PENDING intent in ``store`` (the OLD
    campaign's store) and transition the genuinely-future ones to
    CANCELLED_CUTOVER / the already-recovery-expired ones to
    EXPIRED_RECOVERY_DEADLINE, leaving timely-in-recovery ones alone.

    ``max_entry_staleness_sessions`` is the OLD campaign's own
    ``V2Config.max_entry_staleness_sessions`` -- the SAME parameter its
    own service tick already uses for this exact calculation (reused,
    not reinvented, via ``calendar.recovery_deadline_passed``).

    Pure classification + store writes -- no service/tick loop, no
    process spawned, no Telegram, no broker. Safe to call against a
    stopped OR still-running old-campaign store (a concurrently running
    service only ever transitions a PENDING row forward under its own
    lifecycle rules -- both this function and the service use the same
    ``mark_entry_intent`` idempotent guard, so a race is never worse
    than "whichever committed first wins," never a double-transition).
    """
    result = CutoverResult(cutover_id=cutover_id, as_of_session=as_of_session)
    for intent in store.pending_entry_intents():
        target_entry_session = date.fromisoformat(intent["target_entry_session"])
        if target_entry_session > as_of_session:
            store.mark_entry_intent(
                intent["intent_id"], "CANCELLED_CUTOVER",
                detail=f"cutover {cutover_id}: target_entry_session "
                       f"{target_entry_session.isoformat()} is still in the future as of "
                       f"{as_of_session.isoformat()} -- genuinely unfilled, cancelled atomically")
            result.cancelled.append(intent["intent_id"])
            continue
        if recovery_deadline_passed(
            target_entry_session, max_entry_staleness_sessions=max_entry_staleness_sessions,
            ripe_through=as_of_session, live=live,
        ):
            store.mark_entry_intent(
                intent["intent_id"], "EXPIRED_RECOVERY_DEADLINE",
                detail=f"cutover {cutover_id}: recovery window already closed as of "
                       f"{as_of_session.isoformat()} -- terminal, no new exposure")
            result.expired.append(intent["intent_id"])
            continue
        # timely admitted, still within its Package-3 recovery window --
        # untouched, remains governed by the OLD campaign/version.
        result.retained.append(intent["intent_id"])

    store.record_cutover(
        cutover_id=cutover_id, as_of_session=as_of_session,
        cancelled_count=result.cancelled_count, retained_count=result.retained_count,
        expired_count=result.expired_count,
        detail={"cancelled": result.cancelled, "retained": result.retained, "expired": result.expired},
    )
    return result
