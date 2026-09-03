"""
talonx_ingest.intelligence.significance.store
============================================
``SignificanceStore`` — persistence for ``InformationSignificance``.

Additive tables in the SAME SQLite file the Task 96A ``EventStore`` /
96C ``FilingComparisonStore`` / 96D ``InsiderStore`` use
(``settings.ledger.path``). ``CREATE TABLE IF NOT EXISTS`` only; no
existing table or row is touched.

Idempotency: the primary key is ``significance_id`` = ``SIG:{event_id}:{ruleset_version}``.
``upsert`` replaces that row (``INSERT OR REPLACE``), so a re-evaluation
with the same ruleset never duplicates. A ruleset-version bump produces a
different id, so an older score and the re-computed one coexist — history
is preserved, nothing is silently overwritten.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from talonx_ingest.config import settings
from talonx_ingest.intelligence.domain import SignificanceBand
from talonx_ingest.intelligence.significance.config import (
    RULESET_VERSION,
    SIGNIFICANCE_STORE_SCHEMA_VERSION,
)
from talonx_ingest.intelligence.significance.domain import (
    InformationSignificance,
    SignificanceComponent,
    SignificanceReason,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY, value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event_significance (
    significance_id      TEXT PRIMARY KEY,
    schema_version       TEXT NOT NULL,
    ruleset_version      TEXT NOT NULL,
    event_id             TEXT NOT NULL,
    symbol               TEXT NOT NULL,
    score                INTEGER NOT NULL,
    band                 TEXT NOT NULL,
    raw_score            INTEGER NOT NULL,
    substantive_points   INTEGER NOT NULL DEFAULT 0,
    substantive_families INTEGER NOT NULL DEFAULT 0,
    reasons_json         TEXT NOT NULL DEFAULT '[]',
    components_json      TEXT NOT NULL DEFAULT '[]',
    data_quality_flags   TEXT NOT NULL DEFAULT '[]',
    inputs_present       TEXT NOT NULL DEFAULT '[]',
    band_caps_applied    TEXT NOT NULL DEFAULT '[]',
    input_fingerprint    TEXT NOT NULL,
    evaluated_at_utc     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sig_event    ON event_significance (event_id);
CREATE INDEX IF NOT EXISTS idx_sig_symbol   ON event_significance (symbol);
CREATE INDEX IF NOT EXISTS idx_sig_band     ON event_significance (band);
CREATE INDEX IF NOT EXISTS idx_sig_score    ON event_significance (score);
CREATE INDEX IF NOT EXISTS idx_sig_ruleset  ON event_significance (ruleset_version);
CREATE INDEX IF NOT EXISTS idx_sig_sym_eval ON event_significance (symbol, evaluated_at_utc);
"""


def _iso(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        dt = v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    return str(v)


def _dt(raw) -> datetime | None:
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _reason_to_dict(r: SignificanceReason) -> dict:
    return {
        "code": r.code,
        "description": r.description,
        "points": r.points,
        "component": r.component,
        "evidence_ref": r.evidence_ref,
    }


def _component_to_dict(c: SignificanceComponent) -> dict:
    return {
        "code": c.code,
        "points": c.points,
        "raw_points": c.raw_points,
        "substantive": c.substantive,
        "detail": c.detail,
    }


class SignificanceStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else Path(settings.ledger.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.execute(
            "INSERT INTO schema_meta (key, value) VALUES "
            "('significance_store_schema_version', ?) ON CONFLICT(key) DO NOTHING",
            (str(SIGNIFICANCE_STORE_SCHEMA_VERSION),),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "SignificanceStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def schema_version(self) -> int:
        r = self._conn.execute(
            "SELECT value FROM schema_meta WHERE key='significance_store_schema_version'"
        ).fetchone()
        return int(r[0]) if r else 0

    # ------------------------------------------------------------------
    # writes
    # ------------------------------------------------------------------
    def upsert(self, sig: InformationSignificance) -> bool:
        """Insert or replace by ``significance_id``. Returns ``True`` on a
        fresh insert, ``False`` if it replaced an existing row."""
        existed = self.has(sig.significance_id)
        self._conn.execute(
            """
            INSERT OR REPLACE INTO event_significance (
                significance_id, schema_version, ruleset_version, event_id, symbol,
                score, band, raw_score, substantive_points, substantive_families,
                reasons_json, components_json, data_quality_flags, inputs_present,
                band_caps_applied, input_fingerprint, evaluated_at_utc
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                sig.significance_id,
                sig.schema_version,
                sig.ruleset_version,
                sig.event_id,
                sig.symbol.upper(),
                int(sig.score),
                sig.band.value,
                int(sig.raw_score),
                int(sig.substantive_points),
                int(sig.substantive_families),
                json.dumps([_reason_to_dict(r) for r in sig.reasons]),
                json.dumps([_component_to_dict(c) for c in sig.components]),
                json.dumps(list(sig.data_quality_flags)),
                json.dumps(list(sig.inputs_present)),
                json.dumps(list(sig.band_caps_applied)),
                sig.input_fingerprint,
                _iso(sig.evaluated_at_utc),
            ),
        )
        self._conn.commit()
        return not existed

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------
    def has(self, significance_id: str) -> bool:
        return (
            self._conn.execute(
                "SELECT 1 FROM event_significance WHERE significance_id = ?",
                (significance_id,),
            ).fetchone()
            is not None
        )

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM event_significance").fetchone()[0]

    def get(self, significance_id: str) -> InformationSignificance | None:
        r = self._conn.execute(
            "SELECT * FROM event_significance WHERE significance_id = ?", (significance_id,)
        ).fetchone()
        return self._hydrate(r) if r else None

    def get_for_event(
        self, event_id: str, *, ruleset_version: str = RULESET_VERSION
    ) -> InformationSignificance | None:
        r = self._conn.execute(
            "SELECT * FROM event_significance WHERE event_id = ? AND ruleset_version = ?",
            (event_id, ruleset_version),
        ).fetchone()
        return self._hydrate(r) if r else None

    def latest_for_event(self, event_id: str) -> InformationSignificance | None:
        r = self._conn.execute(
            "SELECT * FROM event_significance WHERE event_id = ? "
            "ORDER BY evaluated_at_utc DESC, significance_id DESC LIMIT 1",
            (event_id,),
        ).fetchone()
        return self._hydrate(r) if r else None

    def query(
        self,
        *,
        symbol: str | None = None,
        band: SignificanceBand | str | None = None,
        min_score: int | None = None,
        ruleset_version: str | None = RULESET_VERSION,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int | None = None,
    ) -> list[InformationSignificance]:
        where: list[str] = []
        params: list = []
        if symbol:
            where.append("symbol = ?")
            params.append(symbol.upper())
        if band is not None:
            where.append("band = ?")
            params.append(band.value if isinstance(band, SignificanceBand) else str(band))
        if min_score is not None:
            where.append("score >= ?")
            params.append(int(min_score))
        if ruleset_version is not None:
            where.append("ruleset_version = ?")
            params.append(ruleset_version)
        if since is not None:
            where.append("evaluated_at_utc >= ?")
            params.append(_iso(since))
        if until is not None:
            where.append("evaluated_at_utc <= ?")
            params.append(_iso(until))
        sql = "SELECT * FROM event_significance"
        if where:
            sql += " WHERE " + " AND ".join(where)
        # deterministic ordering: score desc, evaluated desc, id
        sql += " ORDER BY score DESC, evaluated_at_utc DESC, significance_id ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        return [self._hydrate(r) for r in self._conn.execute(sql, params).fetchall()]

    # ------------------------------------------------------------------
    # hydration
    # ------------------------------------------------------------------
    def _hydrate(self, r: sqlite3.Row) -> InformationSignificance:
        reasons = tuple(
            SignificanceReason(
                code=d["code"],
                description=d["description"],
                points=d["points"],
                component=d["component"],
                evidence_ref=d.get("evidence_ref"),
            )
            for d in json.loads(r["reasons_json"] or "[]")
        )
        components = tuple(
            SignificanceComponent(
                code=d["code"],
                points=d["points"],
                raw_points=d["raw_points"],
                substantive=d["substantive"],
                detail=d.get("detail", ""),
            )
            for d in json.loads(r["components_json"] or "[]")
        )
        return InformationSignificance(
            significance_id=r["significance_id"],
            schema_version=r["schema_version"],
            ruleset_version=r["ruleset_version"],
            event_id=r["event_id"],
            symbol=r["symbol"],
            score=r["score"],
            band=SignificanceBand(r["band"]),
            raw_score=r["raw_score"],
            reasons=reasons,
            components=components,
            substantive_points=r["substantive_points"],
            substantive_families=r["substantive_families"],
            data_quality_flags=tuple(json.loads(r["data_quality_flags"] or "[]")),
            inputs_present=tuple(json.loads(r["inputs_present"] or "[]")),
            band_caps_applied=tuple(json.loads(r["band_caps_applied"] or "[]")),
            input_fingerprint=r["input_fingerprint"],
            evaluated_at_utc=_dt(r["evaluated_at_utc"]),
        )
