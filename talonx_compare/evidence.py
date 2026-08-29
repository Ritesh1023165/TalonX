"""Task 83 §2 -- the date-partitioned evidence store.

Layout (all under ``CompareConfig.evidence_root``):

    <trading_date>/
        manifest.json                 immutable; second write with different
                                      content is refused and diagnosed
        original_events.jsonl         append-only, deduplicated by _id
        piv_records.jsonl             append-only, deduplicated by _id
        comparison.json               per (stage, symbol) aligned view
        divergences.json              classified divergences
        telegram.json                 Original totals + PIV zero-attempt assertion
        diagnostics.json              malformed/duplicate/missing/stale/wrong-session
        file_hashes.json              sha256 of every other file in the dir

Every writer is idempotent: re-running the collector over the same inputs
re-derives the same files without duplicating a single record.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from .identity import ComparisonRecord

MANIFEST_NAME = "manifest.json"
_HASHABLE = (
    "manifest.json", "original_events.jsonl", "piv_records.jsonl",
    "comparison.json", "divergences.json", "telegram.json", "diagnostics.json",
)

TEST_FIXTURE_LABEL = "TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _read_jsonl_ids(path: Path) -> set[str]:
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


@dataclass
class ManifestResult:
    written: bool
    conflict: bool
    detail: str


class EvidenceWriter:
    def __init__(self, evidence_root: Path, trading_date: str) -> None:
        self.trading_date = trading_date
        self.dir = Path(evidence_root) / trading_date
        self.dir.mkdir(parents=True, exist_ok=True)

    # --- manifest (immutable) ------------------------------------------------

    @property
    def manifest_path(self) -> Path:
        return self.dir / MANIFEST_NAME

    def write_manifest(self, manifest: dict[str, Any]) -> ManifestResult:
        """Write once. A later call with byte-identical normalised content
        is a no-op success; a later call with *different* content is
        refused and returns conflict=True (the caller records a
        MANIFEST_CONFLICT diagnostic -- this is the day-level
        wrong-session guard)."""
        payload = dict(manifest)
        payload.setdefault("evidence_label", TEST_FIXTURE_LABEL)
        payload.setdefault("operational_agreement_only", True)
        normalised = json.dumps(payload, sort_keys=True, indent=2)
        if self.manifest_path.exists():
            existing = self.manifest_path.read_text(encoding="utf-8")
            try:
                existing_norm = json.dumps(json.loads(existing), sort_keys=True, indent=2)
            except json.JSONDecodeError:
                existing_norm = existing
            if existing_norm == normalised:
                return ManifestResult(False, False, "manifest already written (identical)")
            return ManifestResult(
                False, True,
                "manifest already exists with different content -- refused to overwrite",
            )
        self.manifest_path.write_text(normalised, encoding="utf-8")
        return ManifestResult(True, False, "manifest written")

    def read_manifest(self) -> dict[str, Any] | None:
        if not self.manifest_path.exists():
            return None
        try:
            return json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    # --- append-only, deduplicated record streams --------------------------

    def _append_records(self, name: str, records: Iterable[ComparisonRecord]) -> tuple[int, int]:
        path = self.dir / name
        seen = _read_jsonl_ids(path)
        appended = duplicate = 0
        with path.open("a", encoding="utf-8") as fh:
            for rec in records:
                d = rec.to_dict()
                if d["_id"] in seen:
                    duplicate += 1
                    continue
                seen.add(d["_id"])
                fh.write(json.dumps(d, sort_keys=True) + "\n")
                appended += 1
        return appended, duplicate

    def append_original_events(self, records: Iterable[ComparisonRecord]) -> tuple[int, int]:
        return self._append_records("original_events.jsonl", records)

    def append_piv_records(self, records: Iterable[ComparisonRecord]) -> tuple[int, int]:
        return self._append_records("piv_records.jsonl", records)

    def read_original_events(self) -> list[ComparisonRecord]:
        return self._read_records("original_events.jsonl")

    def read_piv_records(self) -> list[ComparisonRecord]:
        return self._read_records("piv_records.jsonl")

    def _read_records(self, name: str) -> list[ComparisonRecord]:
        path = self.dir / name
        if not path.exists():
            return []
        out: list[ComparisonRecord] = []
        for ln in path.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(ComparisonRecord.from_dict(json.loads(ln)))
            except (json.JSONDecodeError, KeyError):
                continue
        return out

    # --- derived views (rewritten each pass; pure functions of the streams) -

    def write_comparison(self, payload: dict[str, Any]) -> None:
        (self.dir / "comparison.json").write_text(
            json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")

    def write_divergences(self, rows: list[dict[str, Any]]) -> None:
        (self.dir / "divergences.json").write_text(
            json.dumps({"divergences": rows}, sort_keys=True, indent=2), encoding="utf-8")

    def write_telegram(self, payload: dict[str, Any]) -> None:
        (self.dir / "telegram.json").write_text(
            json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")

    def write_diagnostics(self, diagnostics: list[dict[str, Any]]) -> None:
        (self.dir / "diagnostics.json").write_text(
            json.dumps({"diagnostics": diagnostics}, sort_keys=True, indent=2), encoding="utf-8")

    def read_diagnostics(self) -> list[dict[str, Any]]:
        path = self.dir / "diagnostics.json"
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text(encoding="utf-8")).get("diagnostics", [])
        except json.JSONDecodeError:
            return []

    # --- integrity ---------------------------------------------------------

    def write_file_hashes(self) -> dict[str, str]:
        hashes: dict[str, str] = {}
        for name in _HASHABLE:
            p = self.dir / name
            if p.exists():
                hashes[name] = _sha256_file(p)
        (self.dir / "file_hashes.json").write_text(
            json.dumps({
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "algorithm": "sha256",
                "hashes": hashes,
            }, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        return hashes

    def verify_file_hashes(self) -> tuple[bool, list[str]]:
        """Re-hash every file and compare to the stored file_hashes.json.
        Returns (ok, problems)."""
        path = self.dir / "file_hashes.json"
        if not path.exists():
            return False, ["file_hashes.json missing"]
        try:
            stored = json.loads(path.read_text(encoding="utf-8")).get("hashes", {})
        except json.JSONDecodeError as exc:
            return False, [f"file_hashes.json unreadable: {exc}"]
        problems: list[str] = []
        for name, want in stored.items():
            p = self.dir / name
            if not p.exists():
                problems.append(f"{name}: recorded but now missing")
                continue
            got = _sha256_file(p)
            if got != want:
                problems.append(f"{name}: hash mismatch (recorded {want[:12]}, now {got[:12]})")
        return (not problems), problems
