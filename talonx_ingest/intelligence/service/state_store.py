"""
talonx_ingest.intelligence.service.state_store
==============================================
``ProcessingStateStore`` — persistence for the per-event processing state
machine (``INTELLIGENCE_PROCESSING_STATE_SPEC.md``).

Additive tables in the SAME SQLite file the 96A ``EventStore`` uses:

* ``intel_event_processing`` — one row per ``event_id`` (PK). Overall
  ``stage`` plus per-downstream sub-state so one failure never hides where
  the pipeline stopped.
* ``intel_processing_log`` — append-only stage-transition log per event.

The store never touches ``text_events`` or any 96A/96C/96D/96E table; it
only records *where in processing* each already-stored event is.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from talonx_ingest.config import settings
from talonx_ingest.intelligence.service.state_machine import ProcessingStage

_SUBSTATE_PENDING = "PENDING"
_SUBSTATE_DONE = "DONE"
_SUBSTATE_NA = "NOT_APPLICABLE"
_SUBSTATE_FAILED = "FAILED"
_SUBSTATE_PARTIAL = "PARTIAL"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS intel_event_processing (
    event_id           TEXT PRIMARY KEY,
    symbol             TEXT NOT NULL DEFAULT '',
    event_type         TEXT NOT NULL DEFAULT '',
    form_type          TEXT NOT NULL DEFAULT '',
    accession          TEXT NOT NULL DEFAULT '',
    origin             TEXT NOT NULL DEFAULT 'poll',     -- poll | backfill | replay
    stage              TEXT NOT NULL,
    comparison_state   TEXT NOT NULL DEFAULT 'NOT_APPLICABLE',
    insider_state      TEXT NOT NULL DEFAULT 'NOT_APPLICABLE',
    significance_state TEXT NOT NULL DEFAULT 'PENDING',
    delivery_state     TEXT NOT NULL DEFAULT 'PENDING',
    attempts           INTEGER NOT NULL DEFAULT 0,
    last_error         TEXT,
    retry_after_utc    TEXT,
    discovered_at_utc  TEXT NOT NULL,
    updated_at_utc     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_intel_ep_stage ON intel_event_processing (stage);
CREATE INDEX IF NOT EXISTS idx_intel_ep_retry ON intel_event_processing (retry_after_utc);
CREATE INDEX IF NOT EXISTS idx_intel_ep_symbol ON intel_event_processing (symbol);

CREATE TABLE IF NOT EXISTS intel_processing_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id  TEXT NOT NULL,
    at_utc    TEXT NOT NULL,
    stage     TEXT NOT NULL,
    detail    TEXT
);
CREATE INDEX IF NOT EXISTS idx_intel_plog_event ON intel_processing_log (event_id);
"""

_SCHEMA_VERSION = 1


def _iso(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        d = v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc).isoformat()
    return str(v)


def _dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


@dataclass
class ProcessingRow:
    event_id: str
    symbol: str
    event_type: str
    form_type: str
    accession: str
    origin: str
    stage: ProcessingStage
    comparison_state: str
    insider_state: str
    significance_state: str
    delivery_state: str
    attempts: int
    last_error: str | None
    retry_after_utc: datetime | None
    discovered_at_utc: datetime | None
    updated_at_utc: datetime | None


class ProcessingStateStore:
    # sub-state vocabulary re-exported for callers
    PENDING = _SUBSTATE_PENDING
    DONE = _SUBSTATE_DONE
    NOT_APPLICABLE = _SUBSTATE_NA
    FAILED = _SUBSTATE_FAILED
    PARTIAL = _SUBSTATE_PARTIAL

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else Path(settings.ledger.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.execute(
            "INSERT INTO schema_meta (key, value) VALUES "
            "('intel_event_processing_schema_version', ?) ON CONFLICT(key) DO NOTHING",
            (str(_SCHEMA_VERSION),),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "ProcessingStateStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------
    def get(self, event_id: str) -> ProcessingRow | None:
        r = self._conn.execute(
            "SELECT * FROM intel_event_processing WHERE event_id = ?", (event_id,)
        ).fetchone()
        return self._row(r) if r else None

    def log(self, event_id: str, stage: ProcessingStage | str, detail: str | None = None) -> None:
        self._conn.execute(
            "INSERT INTO intel_processing_log (event_id, at_utc, stage, detail) VALUES (?,?,?,?)",
            (
                event_id,
                _iso(datetime.now(timezone.utc)),
                stage.value if isinstance(stage, ProcessingStage) else str(stage),
                detail,
            ),
        )
        self._conn.commit()

    def logs(self, event_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT at_utc, stage, detail FROM intel_processing_log "
            "WHERE event_id = ? ORDER BY id",
            (event_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    def ensure(
        self,
        event_id: str,
        *,
        symbol: str = "",
        event_type: str = "",
        form_type: str = "",
        accession: str = "",
        origin: str = "poll",
        stage: ProcessingStage = ProcessingStage.DISCOVERED,
        comparison_state: str = _SUBSTATE_NA,
        insider_state: str = _SUBSTATE_NA,
    ) -> ProcessingRow:
        existing = self.get(event_id)
        if existing is not None:
            return existing
        now = _iso(datetime.now(timezone.utc))
        self._conn.execute(
            """
            INSERT INTO intel_event_processing
                (event_id, symbol, event_type, form_type, accession, origin, stage,
                 comparison_state, insider_state, significance_state, delivery_state,
                 discovered_at_utc, updated_at_utc)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(event_id) DO NOTHING
            """,
            (
                event_id, symbol.upper(), event_type, form_type, accession, origin,
                stage.value, comparison_state, insider_state,
                _SUBSTATE_PENDING, _SUBSTATE_PENDING, now, now,
            ),
        )
        self._conn.commit()
        self.log(event_id, stage, f"discovered origin={origin}")
        return self.get(event_id)  # type: ignore[return-value]

    def set_stage(
        self, event_id: str, stage: ProcessingStage, *, detail: str | None = None
    ) -> None:
        self._conn.execute(
            "UPDATE intel_event_processing SET stage=?, updated_at_utc=? WHERE event_id=?",
            (stage.value, _iso(datetime.now(timezone.utc)), event_id),
        )
        self._conn.commit()
        self.log(event_id, stage, detail)

    def set_substate(
        self,
        event_id: str,
        *,
        comparison_state: str | None = None,
        insider_state: str | None = None,
        significance_state: str | None = None,
        delivery_state: str | None = None,
        detail: str | None = None,
    ) -> None:
        sets, params = [], []
        for col, val in (
            ("comparison_state", comparison_state),
            ("insider_state", insider_state),
            ("significance_state", significance_state),
            ("delivery_state", delivery_state),
        ):
            if val is not None:
                sets.append(f"{col}=?")
                params.append(val)
        if not sets:
            return
        sets.append("updated_at_utc=?")
        params.append(_iso(datetime.now(timezone.utc)))
        params.append(event_id)
        self._conn.execute(
            f"UPDATE intel_event_processing SET {', '.join(sets)} WHERE event_id=?", params
        )
        self._conn.commit()
        if detail:
            self.log(event_id, "SUBSTATE", detail)

    def record_error(
        self,
        event_id: str,
        *,
        error: str,
        retryable: bool,
        retry_after_utc: datetime | None = None,
    ) -> None:
        stage = (
            ProcessingStage.FAILED_RETRYABLE if retryable else ProcessingStage.FAILED_TERMINAL
        )
        self._conn.execute(
            """
            UPDATE intel_event_processing
               SET stage=?, attempts=attempts+1, last_error=?, retry_after_utc=?, updated_at_utc=?
             WHERE event_id=?
            """,
            (
                stage.value, error[:500], _iso(retry_after_utc),
                _iso(datetime.now(timezone.utc)), event_id,
            ),
        )
        self._conn.commit()
        self.log(event_id, stage, error[:200])

    def clear_retry(self, event_id: str) -> None:
        self._conn.execute(
            "UPDATE intel_event_processing SET retry_after_utc=NULL, updated_at_utc=? WHERE event_id=?",
            (_iso(datetime.now(timezone.utc)), event_id),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    def open_rows(self, *, limit: int | None = None) -> list[ProcessingRow]:
        from talonx_ingest.intelligence.service.state_machine import OPEN_STAGES

        placeholders = ",".join("?" for _ in OPEN_STAGES)
        sql = (
            f"SELECT * FROM intel_event_processing WHERE stage IN ({placeholders}) "
            "ORDER BY discovered_at_utc"
        )
        params: list = [s.value for s in OPEN_STAGES]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row(r) for r in rows]

    def due_for_retry(self, *, now: datetime | None = None, limit: int | None = None) -> list[ProcessingRow]:
        now = now or datetime.now(timezone.utc)
        rows = self._conn.execute(
            """
            SELECT * FROM intel_event_processing
             WHERE stage IN ('FAILED_RETRYABLE','PARTIAL','ENRICHMENT_PENDING')
               AND (retry_after_utc IS NULL OR retry_after_utc <= ?)
             ORDER BY updated_at_utc
             LIMIT ?
            """,
            (_iso(now), int(limit) if limit is not None else -1),
        ).fetchall()
        return [self._row(r) for r in rows]

    def counts_by_stage(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT stage, COUNT(*) c FROM intel_event_processing GROUP BY stage"
        ).fetchall()
        return {r["stage"]: r["c"] for r in rows}

    def counts_by_substate(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for col in ("comparison_state", "insider_state", "significance_state", "delivery_state"):
            rows = self._conn.execute(
                f"SELECT {col} s, COUNT(*) c FROM intel_event_processing GROUP BY {col}"
            ).fetchall()
            out[col] = {r["s"]: r["c"] for r in rows}
        return out

    def total(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM intel_event_processing").fetchone()[0]

    # ------------------------------------------------------------------
    @staticmethod
    def _row(r: sqlite3.Row) -> ProcessingRow:
        return ProcessingRow(
            event_id=r["event_id"],
            symbol=r["symbol"],
            event_type=r["event_type"],
            form_type=r["form_type"],
            accession=r["accession"],
            origin=r["origin"],
            stage=ProcessingStage(r["stage"]),
            comparison_state=r["comparison_state"],
            insider_state=r["insider_state"],
            significance_state=r["significance_state"],
            delivery_state=r["delivery_state"],
            attempts=r["attempts"],
            last_error=r["last_error"],
            retry_after_utc=_dt(r["retry_after_utc"]),
            discovered_at_utc=_dt(r["discovered_at_utc"]),
            updated_at_utc=_dt(r["updated_at_utc"]),
        )
