"""Task 66B-PREP Part 7: read-only PIV-vs-normal-application evidence
comparator. Never changes runtime decisions -- pure reporting over
whatever evidence already exists on disk.

Explicitly NOT a claim of parity: PIV (talonx_piv) and the normal
application (run_talonx.py) are two different runtimes by design (see
talonx_ops/runtime_manifest.py and next_e2e_piv_handoff.md) -- PIV has no
Brain/Core/Dispatch participation at all, and until the normal application
has actually run once with this evidence layer active, there is nothing on
that side to compare against. This module's job is to report that honestly
(MISSING_EVENT / NOT_APPLICABLE_TO_PIV), never to fabricate or infer a
match that isn't backed by real evidence on both sides.

Stages mirror the pipeline the user's Task 66B-PREP prompt lists. PIV
(talonx_piv/events.py's EVENT_TYPES) only ever populates a subset of
these -- quant_signal, paper_decision, paper_execution, final_position_state --
since it drives QuantScanner directly and has no Brain/Core/Dispatch of its
own. Every other stage is reported NOT_APPLICABLE_TO_PIV on the PIV side,
not silently omitted.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

STAGES: tuple[str, ...] = (
    "market_event_seen",
    "quant_candidate",
    "quant_rejection",
    "quant_signal",
    "brain_received",
    "brain_report",
    "core_received",
    "core_result",
    "dispatch_received",
    "telegram_event",
    "paper_decision",
    "paper_execution",
    "final_position_state",
)

# Which stages PIV's own event stream (talonx_piv/events.py) can ever
# populate -- everything else is structurally out of PIV's scope, not a
# gap in this comparator or in PIV itself.
PIV_APPLICABLE_STAGES: frozenset[str] = frozenset({
    "quant_signal", "paper_decision", "paper_execution", "final_position_state",
})

MATCH = "MATCH"
DATA_DIFFERENCE = "DATA_DIFFERENCE"
PIV_GATING_DIFFERENCE = "PIV_GATING_DIFFERENCE"
DOWNSTREAM_PIPELINE_DIFFERENCE = "DOWNSTREAM_PIPELINE_DIFFERENCE"
EXECUTION_DIFFERENCE = "EXECUTION_DIFFERENCE"
MISSING_EVENT = "MISSING_EVENT"
NOT_APPLICABLE_TO_PIV = "NOT_APPLICABLE_TO_PIV"
UNEXPLAINED = "UNEXPLAINED"


@dataclass(frozen=True)
class ComparatorRow:
    symbol: str
    stage: str
    piv_evidence: dict[str, Any] | None
    full_app_evidence: dict[str, Any] | None
    classification: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_piv_evidence(piv_events_path: Path) -> dict[str, dict[str, Any]]:
    """{symbol: {stage: last-matching-event-dict}} built from a real
    piv_events.jsonl. Missing file / unparseable line is skipped, never
    fabricated -- an empty dict means "no PIV evidence available", reported
    as such downstream, not an error."""
    result: dict[str, dict[str, Any]] = {}
    if not piv_events_path.is_file():
        return result
    for line in piv_events_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        symbol = event.get("symbol")
        if not symbol:
            continue
        event_type = event.get("event")
        stage = None
        if event_type == "SIGNAL" and event.get("source") == "STRATEGY":
            stage = "quant_signal"
        elif event_type == "ORDER_INTENT":
            stage = "paper_decision"
        elif event_type in ("PAPER_ORDER_SUBMITTED", "FILLED"):
            stage = "paper_execution"
        elif event_type == "POSITION_OPENED":
            stage = "final_position_state"
        if stage is None:
            continue
        result.setdefault(symbol, {})[stage] = event
    return result


def load_full_app_evidence_for_date(date_str: str) -> dict[str, dict[str, Any]]:
    """{symbol: {stage: evidence-dict}} built from the normal application's
    own stores, reusing generate_eod_report.py's existing store-reading
    functions rather than re-querying SQLite by hand. Any store that can't
    be opened (not yet run, persistence disabled) is simply absent from the
    result -- never fabricated. Import is local/lazy so this module never
    requires the normal app's stores to exist just to be imported (e.g. by
    a test using only load_piv_evidence)."""
    result: dict[str, dict[str, Any]] = {}
    try:
        from talonx_core.config import CoreConfig
        from talonx_core.store import TickerStateStore
        from talonx_dispatch.config import DispatchConfig
        from talonx_dispatch.store import AuditStore
        from talonx_paper.config import PaperConfig
        from talonx_paper.store import PaperTradingStore
        from talonx_quant.config import QuantConfig
        from talonx_quant.store import QuantStateStore
        from talonx_watchlist.config import WatchlistConfig
        from talonx_watchlist.store import TickerWatchlistStore
        import generate_eod_report as eod
    except Exception:  # noqa: BLE001 -- comparator must never fail to import over this
        return result

    core_store = quant_store = brain_store = None
    try:
        core_store = TickerStateStore(CoreConfig().state_db_path)
    except Exception:  # noqa: BLE001
        pass
    try:
        quant_store = QuantStateStore(QuantConfig().db_path)
    except Exception:  # noqa: BLE001
        pass
    try:
        from talonx_brain.config import BrainConfig
        from talonx_brain.store import BrainStatsStore
        brain_store = BrainStatsStore(BrainConfig().db_path)
    except Exception:  # noqa: BLE001
        pass

    try:
        with AuditStore(DispatchConfig().audit_db_path) as audit_store, \
             PaperTradingStore(PaperConfig().db_path) as paper_store, \
             TickerWatchlistStore(WatchlistConfig().db_path) as watchlist_store:
            report = eod.build_report(
                date_str, audit_store, paper_store, watchlist_store,
                core_store=core_store, quant_store=quant_store, brain_store=brain_store,
            )
    except Exception:  # noqa: BLE001 -- no full-app data available for this date yet
        return result
    finally:
        for store in (core_store, quant_store, brain_store):
            if store is not None:
                try:
                    store.close()
                except Exception:  # noqa: BLE001
                    pass

    for section in report.ticker_sections:
        # build locally and only attach if genuinely non-empty -- every
        # watchlist ticker gets a TickerSection regardless of activity
        # (see build_report's all_symbols), so an unconditional setdefault
        # here would falsely report "full-app evidence" for a ticker that
        # simply exists in the watchlist with zero real pipeline activity.
        entry: dict[str, Any] = {}
        if section.quant_suppressed:
            entry["quant_rejection"] = {"reasons": section.quant_suppressed}
        if section.brain_categories:
            entry["brain_report"] = {"categories": section.brain_categories}
        if section.alert_counts:
            entry["core_result"] = {"alert_counts": section.alert_counts}
            entry["dispatch_received"] = {"alert_counts": section.alert_counts}
        if section.trades:
            entry["paper_execution"] = {"trades": section.trades}
        if entry:
            result[section.ticker] = entry
    return result


def compare(
    piv_evidence: dict[str, dict[str, Any]], full_app_evidence: dict[str, dict[str, Any]],
) -> list[ComparatorRow]:
    """Presence-based, honest reconciliation -- deliberately does NOT
    attempt deep semantic value-diffing across two structurally different
    event schemas with no calibration data (no full-app run has happened
    yet as of this task). DATA_DIFFERENCE/EXECUTION_DIFFERENCE are reserved
    for a future pass once real full-app evidence exists to compare
    specific fields (price, quantity, timestamp) against."""
    symbols = sorted(set(piv_evidence) | set(full_app_evidence))
    rows: list[ComparatorRow] = []
    for symbol in symbols:
        piv_stages = piv_evidence.get(symbol, {})
        app_stages = full_app_evidence.get(symbol, {})
        for stage in STAGES:
            piv_row = piv_stages.get(stage)
            app_row = app_stages.get(stage)
            if stage not in PIV_APPLICABLE_STAGES and piv_row is None:
                classification = NOT_APPLICABLE_TO_PIV
                detail = "This stage is structurally out of PIV's scope (no Brain/Core/Dispatch in PIV)."
            elif piv_row is not None and app_row is not None:
                classification = MATCH
                detail = "Evidence present on both sides for this symbol/stage."
            elif piv_row is not None and app_row is None:
                classification = MISSING_EVENT
                detail = "PIV has evidence; no corresponding full-app evidence found for this date."
            elif piv_row is None and app_row is not None:
                classification = MISSING_EVENT
                detail = "Full-app has evidence; no corresponding PIV evidence found."
            else:
                classification = MISSING_EVENT
                detail = "No evidence on either side."
            rows.append(ComparatorRow(symbol, stage, piv_row, app_row, classification, detail))
    return rows


def build_comparator_report(piv_events_path: Path, date_str: str) -> dict[str, Any]:
    piv_evidence = load_piv_evidence(piv_events_path)
    full_app_evidence = load_full_app_evidence_for_date(date_str)
    rows = compare(piv_evidence, full_app_evidence)
    from collections import Counter
    counts = Counter(r.classification for r in rows)
    return {
        "date": date_str,
        "piv_events_path": str(piv_events_path),
        "piv_symbols_with_evidence": sorted(piv_evidence),
        "full_app_symbols_with_evidence": sorted(full_app_evidence),
        "classification_counts": dict(counts),
        "rows": [r.to_dict() for r in rows],
    }
