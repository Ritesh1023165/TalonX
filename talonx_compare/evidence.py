"""Task 83 §2 / Task 83-R1 §2+§6 -- the date-partitioned evidence store.

Layout (all under ``CompareConfig.evidence_root/<trading_date>/``):

    manifest.json          IMMUTABLE. Only stable identity/binding fields.
                           A second write with different content is refused
                           (conflict=True, naming the changed fields) and
                           the original is never overwritten.
    runtime_status.json    MUTABLE. Atomically rewritten every pass:
                           generated_at, collection stats, transport
                           health, PIV lifecycle status, source health.
    original_events.jsonl  append-only, deduplicated by _id
    piv_records.jsonl      append-only, deduplicated by _id
    comparison.json        aligned per (stage, symbol, event_identity) view
    divergences.json       classified divergences
    telegram.json          Original totals + PIV notification telemetry verdict
    diagnostics.json       malformed / duplicate / missing / stale / wrong-session
    file_hashes.json       sha256 of every required file present

Fail-closed: before modifying an existing archive the writer verifies its
prior integrity; on failure it stops writing and reports UNREADABLE /
DEGRADED rather than regenerating hashes over corruption. All mutable
writes are atomic (temp file + ``os.replace``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable

from .identity import ComparisonRecord

MANIFEST_NAME = "manifest.json"
RUNTIME_STATUS_NAME = "runtime_status.json"
FILE_HASHES_NAME = "file_hashes.json"

# The required archive file set (§6.1). ``file_hashes.json`` hashes every
# other entry; the manifest generator + manifest itself are excluded from
# the *committed* evidence manifest (§6.10), not from this runtime index.
REQUIRED_FILES = (
    MANIFEST_NAME, RUNTIME_STATUS_NAME,
    "original_events.jsonl", "piv_records.jsonl",
    "comparison.json", "divergences.json", "telegram.json", "diagnostics.json",
)
_JSONL_FILES = ("original_events.jsonl", "piv_records.jsonl")
_JSON_FILES = (MANIFEST_NAME, RUNTIME_STATUS_NAME, "comparison.json",
               "divergences.json", "telegram.json", "diagnostics.json")
# files that legitimately exist in the dir but are not part of REQUIRED_FILES
_ALLOWED_EXTRA = frozenset({FILE_HASHES_NAME})

TEST_FIXTURE_LABEL = "TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE"

# The immutable manifest whitelist (§2.2). Anything not here MUST live in
# runtime_status.json instead.
IMMUTABLE_MANIFEST_FIELDS = frozenset({
    "schema_version", "trading_date", "original", "piv", "collector",
    "operational_agreement_only", "not_alpha_evidence", "evidence_label",
})
IMMUTABLE_ORIGINAL_FIELDS = frozenset({
    "redis_url_scheme", "redis_db", "channels", "stage_modules", "execution_class",
})
IMMUTABLE_PIV_FIELDS = frozenset({
    "session_id", "trading_date_et", "runtime_sha", "config_hash", "feed_mode",
    "redis_url_scheme", "redis_db", "redis_namespace", "channels", "universe",
    "execution_mode", "strategy_approval_status", "real_capital_prohibited",
})


def _atomic_write(path: Path, text: str) -> None:
    """Temp file in the same dir + ``os.replace`` (atomic on Windows and
    POSIX). Newlines pinned to ``\\n`` so a committed blob matches the
    working tree byte-for-byte regardless of platform (§6.9)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, path)


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_normalized(path: Path) -> str:
    """Hash the file's git-normalized (LF) bytes so the value is stable
    across CRLF/LF checkouts."""
    return _sha256_bytes(path.read_bytes().replace(b"\r\n", b"\n"))


@dataclass
class ManifestResult:
    written: bool
    conflict: bool
    detail: str
    changed_fields: tuple[str, ...] = ()


@dataclass
class ArchiveIntegrity:
    state: str              # HEALTHY | DEGRADED | UNREADABLE | MISSING
    ok: bool
    problems: list[str] = field(default_factory=list)
    checked_files: list[str] = field(default_factory=list)
    session_scope_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state, "ok": self.ok,
            "problems": list(self.problems), "checked_files": list(self.checked_files),
            "session_scope_notes": list(self.session_scope_notes),
        }


def _diff_fields(old: Any, new: Any, prefix: str = "") -> list[str]:
    """Recursive field-level diff for the immutable-manifest conflict
    report (§2.6)."""
    out: list[str] = []
    if isinstance(old, dict) and isinstance(new, dict):
        for k in sorted(set(old) | set(new)):
            child = f"{prefix}.{k}" if prefix else k
            out += _diff_fields(old.get(k), new.get(k), child)
    elif old != new:
        out.append(f"{prefix or '<root>'}: {old!r} -> {new!r}")
    return out


class EvidenceWriter:
    def __init__(self, evidence_root: Path, trading_date: str) -> None:
        self.trading_date = trading_date
        self.dir = Path(evidence_root) / trading_date
        self.dir.mkdir(parents=True, exist_ok=True)

    # --- manifest (IMMUTABLE) --------------------------------------------

    @property
    def manifest_path(self) -> Path:
        return self.dir / MANIFEST_NAME

    def write_manifest(self, manifest: dict[str, Any]) -> ManifestResult:
        payload = dict(manifest)
        payload.setdefault("schema_version", "83r1")
        payload.setdefault("evidence_label", TEST_FIXTURE_LABEL)
        payload.setdefault("operational_agreement_only", True)
        stray = set(payload) - IMMUTABLE_MANIFEST_FIELDS
        if stray:
            # a programming error -- the caller tried to put a mutable field
            # in the immutable manifest.
            raise ValueError(f"immutable manifest may not contain mutable fields: {sorted(stray)}")
        normalised = _canonical_json(payload)
        if self.manifest_path.exists():
            existing_raw = self.manifest_path.read_text(encoding="utf-8")
            try:
                existing = json.loads(existing_raw)
            except json.JSONDecodeError:
                return ManifestResult(False, True, "existing manifest is unreadable -- refused to overwrite")
            if _canonical_json(existing) == normalised:
                return ManifestResult(False, False, "manifest already written (identical bindings)")
            changed = _diff_fields(existing, payload)
            return ManifestResult(
                False, True,
                "binding change vs the immutable manifest -- refused to overwrite: " + "; ".join(changed),
                tuple(changed),
            )
        _atomic_write(self.manifest_path, normalised)
        return ManifestResult(True, False, "immutable manifest written")

    def read_manifest(self) -> dict[str, Any] | None:
        if not self.manifest_path.exists():
            return None
        try:
            return json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    # --- runtime status (MUTABLE, atomic) ------------------------------

    def write_runtime_status(self, status: dict[str, Any]) -> None:
        payload = dict(status)
        payload.setdefault("generated_at", datetime.now(timezone.utc).isoformat())
        _atomic_write(self.dir / RUNTIME_STATUS_NAME, _canonical_json(payload))

    def read_runtime_status(self) -> dict[str, Any] | None:
        p = self.dir / RUNTIME_STATUS_NAME
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    # --- append-only, deduplicated record streams --------------------

    def _existing_ids(self, name: str) -> set[str]:
        path = self.dir / name
        if not path.exists():
            return set()
        ids: set[str] = set()
        for ln in path.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                ids.add(json.loads(ln).get("_id", ""))
            except json.JSONDecodeError:
                continue
        return ids

    def _append_records(self, name: str, records: Iterable[ComparisonRecord]) -> tuple[int, int]:
        path = self.dir / name
        seen = self._existing_ids(name)
        appended = duplicate = 0
        lines: list[str] = []
        for rec in records:
            d = rec.to_dict()
            if d["_id"] in seen:
                duplicate += 1
                continue
            seen.add(d["_id"])
            lines.append(json.dumps(d, sort_keys=True))
            appended += 1
        if lines:
            # append with a guaranteed trailing newline so the stream is
            # never left truncated mid-line.
            existing = path.read_text(encoding="utf-8") if path.exists() else ""
            if existing and not existing.endswith("\n"):
                existing += "\n"
            _atomic_write(path, existing + "\n".join(lines) + "\n")
        elif not path.exists():
            _atomic_write(path, "")
        return appended, duplicate

    def append_original_events(self, records: Iterable[ComparisonRecord]) -> tuple[int, int]:
        return self._append_records("original_events.jsonl", records)

    def append_piv_records(self, records: Iterable[ComparisonRecord]) -> tuple[int, int]:
        return self._append_records("piv_records.jsonl", records)

    def read_original_events(self) -> list[ComparisonRecord]:
        return self._read_records("original_events.jsonl")[0]

    def read_piv_records(self) -> list[ComparisonRecord]:
        return self._read_records("piv_records.jsonl")[0]

    def _read_records(self, name: str) -> tuple[list[ComparisonRecord], list[str]]:
        """Returns (records, malformed_line_descriptions). Malformed lines
        are NEVER silently dropped -- they are reported (§6.3)."""
        path = self.dir / name
        if not path.exists():
            return [], []
        out: list[ComparisonRecord] = []
        malformed: list[str] = []
        for i, ln in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(ComparisonRecord.from_dict(json.loads(ln)))
            except (json.JSONDecodeError, KeyError) as exc:
                malformed.append(f"{name}:{i}: {type(exc).__name__}: {exc}")
        return out, malformed

    def read_records_with_problems(self, name: str) -> tuple[list[ComparisonRecord], list[str]]:
        return self._read_records(name)

    # --- derived views (rewritten each pass; atomic) ----------------

    def write_comparison(self, payload: dict[str, Any]) -> None:
        _atomic_write(self.dir / "comparison.json", _canonical_json(payload))

    def write_divergences(self, rows: list[dict[str, Any]]) -> None:
        _atomic_write(self.dir / "divergences.json", _canonical_json({"divergences": rows}))

    def write_telegram(self, payload: dict[str, Any]) -> None:
        _atomic_write(self.dir / "telegram.json", _canonical_json(payload))

    def write_diagnostics(self, diagnostics: list[dict[str, Any]]) -> None:
        _atomic_write(self.dir / "diagnostics.json", _canonical_json({"diagnostics": diagnostics}))

    def read_diagnostics(self) -> list[dict[str, Any]]:
        path = self.dir / "diagnostics.json"
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text(encoding="utf-8")).get("diagnostics", [])
        except json.JSONDecodeError:
            return []

    # --- integrity (§6) --------------------------------------------

    def write_file_hashes(self) -> dict[str, str]:
        hashes: dict[str, str] = {}
        missing_required: list[str] = []
        for name in REQUIRED_FILES:
            p = self.dir / name
            if p.exists():
                hashes[name] = sha256_normalized(p)
            else:
                missing_required.append(name)
        _atomic_write(self.dir / FILE_HASHES_NAME, _canonical_json({
            "algorithm": "sha256-lf-normalized",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "required_files": list(REQUIRED_FILES),
            "missing_required": missing_required,
            "hashes": hashes,
        }))
        return hashes

    def verify_file_hashes(self) -> tuple[bool, list[str]]:
        integ = self.verify_archive()
        return integ.ok, integ.problems

    def verify_archive(self, *, expect_session_ids: set[str] | None = None) -> ArchiveIntegrity:
        """Full fail-closed integrity check (§6.2). Detects: required
        missing, unexpected files, malformed JSON/JSONL, missing/duplicate
        _id, hash mismatch, truncated append-only streams, wrong
        date/session, incomplete hash inventory."""
        d = self.dir
        problems: list[str] = []
        checked: list[str] = []
        session_scope_notes: list[str] = []

        if not d.exists():
            return ArchiveIntegrity("MISSING", False, ["archive directory does not exist"])

        # required present?
        present = {p.name for p in d.iterdir() if p.is_file()}
        for name in REQUIRED_FILES:
            if name not in present:
                problems.append(f"required file missing: {name}")
        # unexpected files
        for name in sorted(present - set(REQUIRED_FILES) - _ALLOWED_EXTRA):
            if name.endswith(".tmp"):
                problems.append(f"stray temp file left behind: {name}")
            else:
                problems.append(f"unexpected file in archive: {name}")

        # JSON files parse?
        for name in _JSON_FILES:
            p = d / name
            if not p.exists():
                continue
            checked.append(name)
            try:
                json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                problems.append(f"malformed JSON: {name}: {exc}")

        # JSONL streams
        for name in _JSONL_FILES:
            p = d / name
            if not p.exists():
                continue
            checked.append(name)
            raw = p.read_text(encoding="utf-8")
            if raw and not raw.endswith("\n"):
                problems.append(f"truncated append-only stream (no trailing newline): {name}")
            ids: list[str] = []
            for i, ln in enumerate(raw.splitlines(), 1):
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    row = json.loads(ln)
                except json.JSONDecodeError as exc:
                    problems.append(f"malformed JSONL record: {name}:{i}: {exc}")
                    continue
                _id = row.get("_id")
                if not _id:
                    problems.append(f"JSONL record missing _id: {name}:{i}")
                else:
                    ids.append(_id)
                td = row.get("trading_date")
                if td and td != self.trading_date:
                    problems.append(f"wrong-date record: {name}:{i}: trading_date={td} != {self.trading_date}")
                # NOTE: multiple same-DATE PIV sessions legitimately coexist
                # in one archive, separated by run_scope (§3.8). A changed
                # session id is surfaced as a manifest binding conflict, not
                # as record corruption. ``expect_session_ids`` therefore only
                # WARNS (never fails) about a PIV record whose scope is
                # neither the manifest session nor an "orig:" scope.
                if expect_session_ids is not None:
                    sc = row.get("run_scope")
                    if (row.get("pipeline") == "PIV" and sc and sc not in expect_session_ids
                            and not str(sc).startswith("orig:")):
                        session_scope_notes.append(
                            f"{name}:{i}: PIV run_scope {sc!r} not in manifest scope set "
                            f"(a same-day additional session -- separated by run_scope)")
            dupes = sorted({x for x in ids if ids.count(x) > 1})
            for x in dupes:
                problems.append(f"duplicate _id in {name}: {x}")

        # hash inventory
        hp = d / FILE_HASHES_NAME
        if not hp.exists():
            problems.append("file_hashes.json missing")
        else:
            checked.append(FILE_HASHES_NAME)
            try:
                inv = json.loads(hp.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                problems.append(f"file_hashes.json unreadable: {exc}")
                inv = {}
            stored = inv.get("hashes", {}) if isinstance(inv, dict) else {}
            for name in REQUIRED_FILES:
                p = d / name
                if p.exists() and name not in stored:
                    problems.append(f"incomplete hash inventory: {name} present but unhashed")
                if name in stored:
                    got = sha256_normalized(p) if p.exists() else None
                    if got is None:
                        problems.append(f"hash inventory lists {name} but the file is gone")
                    elif got != stored[name]:
                        problems.append(
                            f"hash mismatch: {name} (recorded {stored[name][:12]}, now {got[:12]})")

        state = "HEALTHY" if not problems else "DEGRADED"
        # a parse failure on a required JSON / any missing required file is
        # a harder UNREADABLE condition.
        if any(p.startswith(("malformed JSON:", "required file missing:", "archive directory"))
               for p in problems):
            state = "UNREADABLE"
        return ArchiveIntegrity(state, not problems, problems, checked, session_scope_notes)

    def verify_before_write(self, *, expect_session_ids: set[str] | None = None) -> ArchiveIntegrity:
        """Called by the collector before it modifies an EXISTING archive.
        If the archive already exists and is not HEALTHY the collector must
        abort the write phase (§6.4)."""
        if not (self.dir / MANIFEST_NAME).exists():
            return ArchiveIntegrity("HEALTHY", True, [], [])  # brand-new archive
        return self.verify_archive(expect_session_ids=expect_session_ids)
