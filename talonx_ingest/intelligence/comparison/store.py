"""
talonx_ingest.intelligence.comparison.store
===========================================
``FilingComparisonStore`` -- persistence for ``FilingComparison`` objects.

Additive tables in the SAME SQLite file the Task 96A ``EventStore`` uses
(``settings.ledger.path``). ``CREATE TABLE IF NOT EXISTS`` only; the
``text_events`` / ``ingested_*`` tables are never touched. Idempotent:
``upsert_comparison`` replaces the parent row and rebuilds child rows for
one ``comparison_id`` inside a single transaction, so a re-run of the same
filing pair never duplicates.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from talonx_ingest.config import settings
from talonx_ingest.intelligence.comparison.config import (
    COMPARISON_STORE_SCHEMA_VERSION,
    NEGATIVE_RISK_TERMS,
    POSITIVE_BUSINESS_TERMS,
    XBRL_FIELDS,
)
from talonx_ingest.intelligence.comparison.domain import (
    ComparisonMethod,
    FilingComparison,
    KeywordCategory,
    KeywordCategorySummary,
    KeywordChange,
    PassageChange,
    PassageChangeType,
    SectionChange,
    SectionStatus,
    SectionType,
    WholeDocumentChange,
    XbrlChange,
    XbrlPeriodComparison,
)
from talonx_ingest.intelligence.domain import EvidenceRecord, SourceType

# deterministic hydration order == engine emission order
_SECTION_RANK = {st.value: i for i, st in enumerate(SectionType)}
_PASSAGE_SECTION_RANK = {"risk_factors": 0, "mdna": 1, "liquidity": 2, "whole_document": 3}
_KEYWORD_TERM_RANK = {
    t: i for i, t in enumerate((*NEGATIVE_RISK_TERMS, *POSITIVE_BUSINESS_TERMS))
}
_KEYWORD_CAT_RANK = {KeywordCategory.NEGATIVE_RISK.value: 0, KeywordCategory.POSITIVE_BUSINESS.value: 1}
_XBRL_FIELD_RANK = {s["field"]: i for i, s in enumerate(XBRL_FIELDS)}
_XBRL_CMP_RANK = {XbrlPeriodComparison.YOY.value: 0, XbrlPeriodComparison.QOQ.value: 1}
_EVIDENCE_RANK = {
    "prior_comparable_match@v1": 0,
    "edgar_archive_fetch@v1:current": 1,
    "edgar_archive_fetch@v1:prior": 2,
    "filing_normalize@v1": 3,
    "section_extract@v1": 4,
    "difflib_opcodes@v1": 5,
    "frozen_lexicon_count@v1": 6,
    "xbrl_first_filed@v1": 7,
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS filing_comparisons (
    comparison_id            TEXT PRIMARY KEY,
    schema_version           TEXT NOT NULL,
    symbol                   TEXT NOT NULL,
    company_name             TEXT NOT NULL,
    current_event_id         TEXT NOT NULL,
    prior_event_id           TEXT,
    current_accession        TEXT NOT NULL,
    prior_accession          TEXT,
    form_type                TEXT NOT NULL,
    base_form                TEXT NOT NULL,
    comparison_method        TEXT NOT NULL,
    current_accepted_at_utc  TEXT,
    prior_accepted_at_utc    TEXT,
    current_report_period_end TEXT,
    prior_report_period_end  TEXT,
    current_document_hash    TEXT,
    prior_document_hash      TEXT,
    current_document_url     TEXT,
    prior_document_url       TEXT,
    has_prior                INTEGER NOT NULL,
    wd_prior_word_count      INTEGER,
    wd_current_word_count    INTEGER,
    wd_word_count_delta      INTEGER,
    wd_prior_char_count      INTEGER,
    wd_current_char_count    INTEGER,
    wd_char_count_delta      INTEGER,
    wd_quick_ratio           REAL,
    wd_diff_ratio            REAL,
    wd_added_word_count      INTEGER,
    wd_removed_word_count    INTEGER,
    wd_changed_fraction      REAL,
    wd_material_threshold    REAL,
    wd_exceeds_material      INTEGER,
    data_quality_flags       TEXT NOT NULL DEFAULT '[]',
    created_at_utc           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fc_symbol       ON filing_comparisons (symbol);
CREATE INDEX IF NOT EXISTS idx_fc_current_evt  ON filing_comparisons (current_event_id);
CREATE INDEX IF NOT EXISTS idx_fc_symbol_form  ON filing_comparisons (symbol, base_form);
CREATE INDEX IF NOT EXISTS idx_fc_accepted     ON filing_comparisons (current_accepted_at_utc);

CREATE TABLE IF NOT EXISTS filing_section_changes (
    comparison_id           TEXT NOT NULL,
    section_type            TEXT NOT NULL,
    status                  TEXT NOT NULL,
    prior_present           INTEGER NOT NULL,
    current_present         INTEGER NOT NULL,
    prior_char_count        INTEGER,
    current_char_count      INTEGER,
    char_count_delta        INTEGER,
    pct_char_delta          REAL,
    prior_word_count        INTEGER,
    current_word_count      INTEGER,
    word_count_delta        INTEGER,
    quick_ratio             REAL,
    diff_ratio              REAL,
    added_word_count        INTEGER,
    removed_word_count      INTEGER,
    prior_text_hash         TEXT,
    current_text_hash       TEXT,
    material_threshold      REAL,
    exceeds_material        INTEGER,
    header_matched_current  TEXT,
    header_matched_prior    TEXT,
    PRIMARY KEY (comparison_id, section_type)
);

CREATE TABLE IF NOT EXISTS filing_keyword_changes (
    comparison_id  TEXT NOT NULL,
    category       TEXT NOT NULL,
    term           TEXT NOT NULL,
    prior_count    INTEGER NOT NULL,
    current_count  INTEGER NOT NULL,
    delta          INTEGER NOT NULL,
    PRIMARY KEY (comparison_id, category, term)
);

CREATE TABLE IF NOT EXISTS filing_keyword_summaries (
    comparison_id    TEXT NOT NULL,
    category         TEXT NOT NULL,
    prior_total      INTEGER NOT NULL,
    current_total    INTEGER NOT NULL,
    total_delta      INTEGER NOT NULL,
    terms_increased  TEXT NOT NULL DEFAULT '[]',
    terms_decreased  TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (comparison_id, category)
);

CREATE TABLE IF NOT EXISTS filing_xbrl_changes (
    comparison_id           TEXT NOT NULL,
    field                   TEXT NOT NULL,
    comparison              TEXT NOT NULL,
    taxonomy                TEXT,
    concept                 TEXT,
    unit                    TEXT,
    prior_period_end        TEXT,
    current_period_end      TEXT,
    prior_value             REAL,
    current_value           REAL,
    absolute_delta          REAL,
    relative_delta          REAL,
    prior_filed_accession   TEXT,
    current_filed_accession TEXT,
    prior_filed_date        TEXT,
    current_filed_date      TEXT,
    status                  TEXT NOT NULL,
    quality_flags           TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (comparison_id, field, comparison)
);

CREATE TABLE IF NOT EXISTS filing_passage_changes (
    comparison_id       TEXT NOT NULL,
    change_type         TEXT NOT NULL,
    section             TEXT NOT NULL,
    idx                 INTEGER NOT NULL,
    word_count          INTEGER NOT NULL,
    char_count          INTEGER NOT NULL,
    text                TEXT NOT NULL,
    truncated           INTEGER NOT NULL DEFAULT 0,
    prior_word_offset   INTEGER,
    current_word_offset INTEGER,
    PRIMARY KEY (comparison_id, change_type, section, idx)
);

CREATE TABLE IF NOT EXISTS filing_comparison_evidence (
    comparison_id    TEXT NOT NULL,
    transform        TEXT NOT NULL,
    source_provider  TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    source_url       TEXT,
    exact_timestamp  TEXT,
    retrieved_at     TEXT NOT NULL,
    input_hash       TEXT,
    notes            TEXT,
    PRIMARY KEY (comparison_id, transform)
);
"""


def _iso(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        dt = v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def _dt(raw) -> datetime | None:
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _d(raw) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _b(v) -> int | None:
    return None if v is None else (1 if v else 0)


class FilingComparisonStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else Path(settings.ledger.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.execute(
            "INSERT INTO schema_meta (key, value) VALUES "
            "('comparison_store_schema_version', ?) ON CONFLICT(key) DO NOTHING",
            (str(COMPARISON_STORE_SCHEMA_VERSION),),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "FilingComparisonStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def schema_version(self) -> int:
        r = self._conn.execute(
            "SELECT value FROM schema_meta WHERE key='comparison_store_schema_version'"
        ).fetchone()
        return int(r[0]) if r else 0

    # ------------------------------------------------------------------
    # writes
    # ------------------------------------------------------------------
    def upsert_comparison(self, fc: FilingComparison) -> bool:
        existed = self.has_comparison(fc.comparison_id)
        w = fc.whole_document_change
        cur = self._conn
        with cur:  # single transaction
            cur.execute(
                """
                INSERT OR REPLACE INTO filing_comparisons (
                    comparison_id, schema_version, symbol, company_name,
                    current_event_id, prior_event_id, current_accession, prior_accession,
                    form_type, base_form, comparison_method,
                    current_accepted_at_utc, prior_accepted_at_utc,
                    current_report_period_end, prior_report_period_end,
                    current_document_hash, prior_document_hash,
                    current_document_url, prior_document_url, has_prior,
                    wd_prior_word_count, wd_current_word_count, wd_word_count_delta,
                    wd_prior_char_count, wd_current_char_count, wd_char_count_delta,
                    wd_quick_ratio, wd_diff_ratio, wd_added_word_count, wd_removed_word_count,
                    wd_changed_fraction, wd_material_threshold, wd_exceeds_material,
                    data_quality_flags, created_at_utc
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    fc.comparison_id, fc.schema_version, fc.symbol, fc.company_name,
                    fc.current_event_id, fc.prior_event_id, fc.current_accession, fc.prior_accession,
                    fc.form_type, fc.base_form, fc.comparison_method.value,
                    _iso(fc.current_accepted_at_utc), _iso(fc.prior_accepted_at_utc),
                    _iso(fc.current_report_period_end), _iso(fc.prior_report_period_end),
                    fc.current_document_hash, fc.prior_document_hash,
                    fc.current_document_url, fc.prior_document_url,
                    1 if fc.prior_accession else 0,
                    getattr(w, "prior_word_count", None), getattr(w, "current_word_count", None),
                    getattr(w, "word_count_delta", None), getattr(w, "prior_char_count", None),
                    getattr(w, "current_char_count", None), getattr(w, "char_count_delta", None),
                    getattr(w, "quick_ratio", None), getattr(w, "diff_ratio", None),
                    getattr(w, "added_word_count", None), getattr(w, "removed_word_count", None),
                    getattr(w, "changed_fraction", None), getattr(w, "material_threshold", None),
                    _b(getattr(w, "exceeds_material_threshold", None)),
                    json.dumps(list(fc.data_quality_flags)), _iso(fc.created_at_utc),
                ),
            )
            for tbl in (
                "filing_section_changes", "filing_keyword_changes", "filing_keyword_summaries",
                "filing_xbrl_changes", "filing_passage_changes", "filing_comparison_evidence",
            ):
                cur.execute(f"DELETE FROM {tbl} WHERE comparison_id = ?", (fc.comparison_id,))

            cur.executemany(
                """
                INSERT INTO filing_section_changes (
                    comparison_id, section_type, status, prior_present, current_present,
                    prior_char_count, current_char_count, char_count_delta, pct_char_delta,
                    prior_word_count, current_word_count, word_count_delta,
                    quick_ratio, diff_ratio, added_word_count, removed_word_count,
                    prior_text_hash, current_text_hash, material_threshold, exceeds_material,
                    header_matched_current, header_matched_prior
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                [
                    (
                        fc.comparison_id, s.section_type.value, s.status.value,
                        _b(s.prior_present), _b(s.current_present),
                        s.prior_char_count, s.current_char_count, s.char_count_delta, s.pct_char_delta,
                        s.prior_word_count, s.current_word_count, s.word_count_delta,
                        s.quick_ratio, s.diff_ratio, s.added_word_count, s.removed_word_count,
                        s.prior_text_hash, s.current_text_hash, s.material_threshold,
                        _b(s.exceeds_material_threshold),
                        s.header_matched_current, s.header_matched_prior,
                    )
                    for s in fc.section_changes
                ],
            )
            cur.executemany(
                "INSERT INTO filing_keyword_changes (comparison_id, category, term, "
                "prior_count, current_count, delta) VALUES (?,?,?,?,?,?)",
                [
                    (fc.comparison_id, k.category.value, k.term, k.prior_count, k.current_count, k.delta)
                    for k in fc.keyword_changes
                ],
            )
            cur.executemany(
                "INSERT INTO filing_keyword_summaries (comparison_id, category, prior_total, "
                "current_total, total_delta, terms_increased, terms_decreased) VALUES (?,?,?,?,?,?,?)",
                [
                    (
                        fc.comparison_id, s.category.value, s.prior_total, s.current_total,
                        s.total_delta, json.dumps(list(s.terms_increased)),
                        json.dumps(list(s.terms_decreased)),
                    )
                    for s in fc.keyword_category_summaries
                ],
            )
            cur.executemany(
                """
                INSERT INTO filing_xbrl_changes (
                    comparison_id, field, comparison, taxonomy, concept, unit,
                    prior_period_end, current_period_end, prior_value, current_value,
                    absolute_delta, relative_delta, prior_filed_accession, current_filed_accession,
                    prior_filed_date, current_filed_date, status, quality_flags
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                [
                    (
                        fc.comparison_id, x.field, x.comparison.value, x.taxonomy, x.concept, x.unit,
                        _iso(x.prior_period_end), _iso(x.current_period_end),
                        x.prior_value, x.current_value, x.absolute_delta, x.relative_delta,
                        x.prior_filed_accession, x.current_filed_accession,
                        _iso(x.prior_filed_date), _iso(x.current_filed_date),
                        x.status, json.dumps(list(x.quality_flags)),
                    )
                    for x in fc.xbrl_changes
                ],
            )
            passages = [(p, PassageChangeType.NEW_IN_CURRENT) for p in fc.new_passages] + [
                (p, PassageChangeType.REMOVED_SINCE_PRIOR) for p in fc.removed_passages
            ]
            cur.executemany(
                """
                INSERT INTO filing_passage_changes (
                    comparison_id, change_type, section, idx, word_count, char_count,
                    text, truncated, prior_word_offset, current_word_offset
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                [
                    (
                        fc.comparison_id, p.change_type.value, p.section, p.index,
                        p.word_count, p.char_count, p.text, _b(p.truncated),
                        p.prior_word_offset, p.current_word_offset,
                    )
                    for p, _ in passages
                ],
            )
            cur.executemany(
                """
                INSERT INTO filing_comparison_evidence (
                    comparison_id, transform, source_provider, source_record_id, source_url,
                    exact_timestamp, retrieved_at, input_hash, notes
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                [
                    (
                        fc.comparison_id, e.transform, e.source_provider.value, e.source_record_id,
                        e.source_url, _iso(e.exact_timestamp), _iso(e.retrieved_at),
                        e.input_hash, e.notes,
                    )
                    for e in fc.evidence
                ],
            )
        return not existed

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------
    def has_comparison(self, comparison_id: str) -> bool:
        return (
            self._conn.execute(
                "SELECT 1 FROM filing_comparisons WHERE comparison_id = ?", (comparison_id,)
            ).fetchone()
            is not None
        )

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM filing_comparisons").fetchone()[0]

    def get_comparison(self, comparison_id: str) -> FilingComparison | None:
        row = self._conn.execute(
            "SELECT * FROM filing_comparisons WHERE comparison_id = ?", (comparison_id,)
        ).fetchone()
        return self._hydrate(row) if row else None

    def get_comparison_for_current_event(self, current_event_id: str) -> FilingComparison | None:
        row = self._conn.execute(
            "SELECT * FROM filing_comparisons WHERE current_event_id = ? "
            "ORDER BY created_at_utc DESC LIMIT 1",
            (current_event_id,),
        ).fetchone()
        return self._hydrate(row) if row else None

    def latest_for_symbol(
        self, symbol: str, *, base_form: str | None = None
    ) -> FilingComparison | None:
        sql = "SELECT * FROM filing_comparisons WHERE symbol = ?"
        params: list = [symbol.upper()]
        if base_form:
            sql += " AND base_form = ?"
            params.append(base_form)
        sql += " ORDER BY current_accepted_at_utc DESC, created_at_utc DESC LIMIT 1"
        row = self._conn.execute(sql, params).fetchone()
        return self._hydrate(row) if row else None

    def query_comparisons(
        self,
        *,
        symbol: str | None = None,
        base_form: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int | None = None,
        newest_first: bool = True,
    ) -> list[FilingComparison]:
        where: list[str] = []
        params: list = []
        if symbol:
            where.append("symbol = ?")
            params.append(symbol.upper())
        if base_form:
            where.append("base_form = ?")
            params.append(base_form)
        if since is not None:
            where.append("current_accepted_at_utc >= ?")
            params.append(_iso(since))
        if until is not None:
            where.append("current_accepted_at_utc <= ?")
            params.append(_iso(until))
        sql = "SELECT * FROM filing_comparisons"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY current_accepted_at_utc " + ("DESC" if newest_first else "ASC")
        sql += ", comparison_id " + ("DESC" if newest_first else "ASC")
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        return [self._hydrate(r) for r in self._conn.execute(sql, params).fetchall()]

    def get_section_changes(self, comparison_id: str) -> list[SectionChange]:
        return self._section_changes(comparison_id)

    def get_xbrl_changes(self, comparison_id: str) -> list[XbrlChange]:
        return self._xbrl_changes(comparison_id)

    def get_passages(
        self, comparison_id: str, *, change_type: PassageChangeType | None = None
    ) -> list[PassageChange]:
        new, removed = self._passages(comparison_id)
        if change_type is PassageChangeType.NEW_IN_CURRENT:
            return list(new)
        if change_type is PassageChangeType.REMOVED_SINCE_PRIOR:
            return list(removed)
        return list(new) + list(removed)

    def get_evidence(self, comparison_id: str) -> list[EvidenceRecord]:
        return self._evidence(comparison_id)

    # ------------------------------------------------------------------
    # hydration helpers
    # ------------------------------------------------------------------
    _SECTION_ORDER = {st.value: i for i, st in enumerate(SectionType)}

    def _section_changes(self, cid: str) -> list[SectionChange]:
        rows = self._conn.execute(
            "SELECT * FROM filing_section_changes WHERE comparison_id = ?", (cid,)
        ).fetchall()
        rows = sorted(rows, key=lambda r: self._SECTION_ORDER.get(r["section_type"], 99))
        out = []
        for r in rows:
            out.append(
                SectionChange(
                    section_type=SectionType(r["section_type"]),
                    status=SectionStatus(r["status"]),
                    prior_present=bool(r["prior_present"]),
                    current_present=bool(r["current_present"]),
                    prior_char_count=r["prior_char_count"],
                    current_char_count=r["current_char_count"],
                    char_count_delta=r["char_count_delta"],
                    pct_char_delta=r["pct_char_delta"],
                    prior_word_count=r["prior_word_count"],
                    current_word_count=r["current_word_count"],
                    word_count_delta=r["word_count_delta"],
                    quick_ratio=r["quick_ratio"],
                    diff_ratio=r["diff_ratio"],
                    added_word_count=r["added_word_count"],
                    removed_word_count=r["removed_word_count"],
                    prior_text_hash=r["prior_text_hash"],
                    current_text_hash=r["current_text_hash"],
                    material_threshold=r["material_threshold"],
                    exceeds_material_threshold=(
                        None if r["exceeds_material"] is None else bool(r["exceeds_material"])
                    ),
                    header_matched_current=r["header_matched_current"],
                    header_matched_prior=r["header_matched_prior"],
                )
            )
        return out

    def _keyword_changes(self, cid: str) -> list[KeywordChange]:
        rows = self._conn.execute(
            "SELECT * FROM filing_keyword_changes WHERE comparison_id = ?", (cid,)
        ).fetchall()
        rows = sorted(
            rows,
            key=lambda r: (
                _KEYWORD_CAT_RANK.get(r["category"], 9),
                _KEYWORD_TERM_RANK.get(r["term"], 99),
            ),
        )
        return [
            KeywordChange(
                category=KeywordCategory(r["category"]),
                term=r["term"],
                prior_count=r["prior_count"],
                current_count=r["current_count"],
                delta=r["delta"],
            )
            for r in rows
        ]

    def _keyword_summaries(self, cid: str) -> list[KeywordCategorySummary]:
        rows = self._conn.execute(
            "SELECT * FROM filing_keyword_summaries WHERE comparison_id = ? ORDER BY category",
            (cid,),
        ).fetchall()
        return [
            KeywordCategorySummary(
                category=KeywordCategory(r["category"]),
                prior_total=r["prior_total"],
                current_total=r["current_total"],
                total_delta=r["total_delta"],
                terms_increased=tuple(json.loads(r["terms_increased"] or "[]")),
                terms_decreased=tuple(json.loads(r["terms_decreased"] or "[]")),
            )
            for r in rows
        ]

    def _xbrl_changes(self, cid: str) -> list[XbrlChange]:
        rows = self._conn.execute(
            "SELECT * FROM filing_xbrl_changes WHERE comparison_id = ?", (cid,)
        ).fetchall()
        rows = sorted(
            rows,
            key=lambda r: (
                _XBRL_FIELD_RANK.get(r["field"], 99),
                _XBRL_CMP_RANK.get(r["comparison"], 9),
            ),
        )
        return [
            XbrlChange(
                field=r["field"],
                taxonomy=r["taxonomy"],
                concept=r["concept"],
                unit=r["unit"],
                comparison=XbrlPeriodComparison(r["comparison"]),
                prior_period_end=_d(r["prior_period_end"]),
                current_period_end=_d(r["current_period_end"]),
                prior_value=r["prior_value"],
                current_value=r["current_value"],
                absolute_delta=r["absolute_delta"],
                relative_delta=r["relative_delta"],
                prior_filed_accession=r["prior_filed_accession"],
                current_filed_accession=r["current_filed_accession"],
                prior_filed_date=_d(r["prior_filed_date"]),
                current_filed_date=_d(r["current_filed_date"]),
                status=r["status"],
                quality_flags=tuple(json.loads(r["quality_flags"] or "[]")),
            )
            for r in rows
        ]

    def _passages(self, cid: str) -> tuple[list[PassageChange], list[PassageChange]]:
        rows = self._conn.execute(
            "SELECT * FROM filing_passage_changes WHERE comparison_id = ?", (cid,)
        ).fetchall()
        rows = sorted(
            rows,
            key=lambda r: (
                _PASSAGE_SECTION_RANK.get(r["section"], 9),
                r["idx"],
            ),
        )
        new: list[PassageChange] = []
        removed: list[PassageChange] = []
        for r in rows:
            p = PassageChange(
                change_type=PassageChangeType(r["change_type"]),
                section=r["section"],
                index=r["idx"],
                word_count=r["word_count"],
                char_count=r["char_count"],
                text=r["text"],
                truncated=bool(r["truncated"]),
                prior_word_offset=r["prior_word_offset"],
                current_word_offset=r["current_word_offset"],
            )
            (new if p.change_type is PassageChangeType.NEW_IN_CURRENT else removed).append(p)
        return new, removed

    def _evidence(self, cid: str) -> list[EvidenceRecord]:
        rows = self._conn.execute(
            "SELECT * FROM filing_comparison_evidence WHERE comparison_id = ?", (cid,)
        ).fetchall()
        rows = sorted(
            rows, key=lambda r: (_EVIDENCE_RANK.get(r["transform"], 99), r["transform"])
        )
        return [
            EvidenceRecord(
                source_provider=SourceType(r["source_provider"]),
                source_record_id=r["source_record_id"],
                source_url=r["source_url"],
                exact_timestamp=_dt(r["exact_timestamp"]),
                retrieved_at=_dt(r["retrieved_at"]),
                transform=r["transform"],
                input_hash=r["input_hash"],
                notes=r["notes"],
            )
            for r in rows
        ]

    def _hydrate(self, row: sqlite3.Row) -> FilingComparison:
        cid = row["comparison_id"]
        w = None
        if row["has_prior"] and row["wd_diff_ratio"] is not None:
            w = WholeDocumentChange(
                method=ComparisonMethod.SEQUENCEMATCHER_QUICKRATIO_WORDLIST_V1,
                prior_word_count=row["wd_prior_word_count"],
                current_word_count=row["wd_current_word_count"],
                word_count_delta=row["wd_word_count_delta"],
                prior_char_count=row["wd_prior_char_count"],
                current_char_count=row["wd_current_char_count"],
                char_count_delta=row["wd_char_count_delta"],
                quick_ratio=row["wd_quick_ratio"],
                diff_ratio=row["wd_diff_ratio"],
                added_word_count=row["wd_added_word_count"],
                removed_word_count=row["wd_removed_word_count"],
                changed_fraction=row["wd_changed_fraction"],
                material_threshold=row["wd_material_threshold"],
                exceeds_material_threshold=bool(row["wd_exceeds_material"]),
            )
        new, removed = self._passages(cid)
        try:
            flags = tuple(json.loads(row["data_quality_flags"] or "[]"))
        except (ValueError, TypeError):
            flags = ()
        return FilingComparison(
            comparison_id=cid,
            schema_version=row["schema_version"],
            symbol=row["symbol"],
            company_name=row["company_name"],
            current_event_id=row["current_event_id"],
            prior_event_id=row["prior_event_id"],
            current_accession=row["current_accession"],
            prior_accession=row["prior_accession"],
            form_type=row["form_type"],
            base_form=row["base_form"],
            current_accepted_at_utc=_dt(row["current_accepted_at_utc"]),
            prior_accepted_at_utc=_dt(row["prior_accepted_at_utc"]),
            current_report_period_end=_d(row["current_report_period_end"]),
            prior_report_period_end=_d(row["prior_report_period_end"]),
            comparison_method=ComparisonMethod(row["comparison_method"]),
            current_document_hash=row["current_document_hash"],
            prior_document_hash=row["prior_document_hash"],
            current_document_url=row["current_document_url"],
            prior_document_url=row["prior_document_url"],
            whole_document_change=w,
            section_changes=tuple(self._section_changes(cid)),
            keyword_changes=tuple(self._keyword_changes(cid)),
            keyword_category_summaries=tuple(self._keyword_summaries(cid)),
            xbrl_changes=tuple(self._xbrl_changes(cid)),
            new_passages=tuple(new),
            removed_passages=tuple(removed),
            data_quality_flags=flags,
            evidence=tuple(self._evidence(cid)),
            created_at_utc=_dt(row["created_at_utc"]),
        )
