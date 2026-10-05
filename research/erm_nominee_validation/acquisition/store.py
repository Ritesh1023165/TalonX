"""Acquisition archive store: append-only request ledger + write-once bytes (resumable, never silently replaced).

ledger.jsonl: one record per ATTEMPT {request_key, category, provider, url, params (no secrets), content_from,
content_to, retrieved_utc, state, http_status, attempts, path, sha256, bytes, detail}. Resume: a request whose latest
record is RETRIEVED_USABLE or RETRIEVED_LEGITIMATELY_ABSENT is NOT re-requested; failed requests are retried and the
new attempt is appended (old records kept). Bytes are written once: if a path already holds DIFFERENT bytes (e.g. a
provider revision on a later run) the new bytes go to '<path>.rev-<sha8>' and both are recorded -- nothing is
overwritten. The store never writes outside its own root (it is never the frozen development archive).
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from research.erm_nominee_validation.acquisition import states as S


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ArchiveStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "acquisition").mkdir(exist_ok=True)
        self.ledger_path = self.root / "acquisition" / "ledger.jsonl"
        self._latest: dict = {}
        if self.ledger_path.exists():
            for line in self.ledger_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    r = json.loads(line)
                    self._latest[r["request_key"]] = r

    def latest(self, key: str) -> dict | None:
        return self._latest.get(key)

    def done(self, key: str) -> bool:
        r = self._latest.get(key)
        return bool(r) and r["state"] in S.OK_STATES

    def _append(self, rec: dict) -> dict:
        with open(self.ledger_path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        self._latest[rec["request_key"]] = rec
        return rec

    def record(self, request, category: str, scope: tuple, state: str, *, http_status=None, attempts=None,
               body: bytes | None = None, rel_path: str | None = None, gz: bool = True, detail: str = "") -> dict:
        path, digest, size = None, None, None
        if body is not None and rel_path is not None:
            if gz and not rel_path.endswith(".gz"):
                rel_path += ".gz"
            digest = hashlib.sha256(body).hexdigest()
            data = gzip.compress(body, mtime=0) if gz else body
            p = self.root / rel_path
            p.parent.mkdir(parents=True, exist_ok=True)
            if p.exists():
                prev = gzip.decompress(p.read_bytes()) if gz else p.read_bytes()
                if hashlib.sha256(prev).hexdigest() != digest:               # never overwrite: keep both
                    p = p.with_name(p.name + f".rev-{digest[:8]}")
                    detail = (detail + "; " if detail else "") + "REVISION_PRESERVED_ALONGSIDE_EARLIER_BYTES"
                    p.write_bytes(data)
            else:
                tmp = p.with_name(p.name + ".tmp")
                tmp.write_bytes(data)
                os.replace(tmp, p)
            path, size = p.relative_to(self.root).as_posix(), len(body)
        return self._append({"request_key": request.key, "category": category, "provider": request.provider,
                             "url": request.url, "params": list(request.params),
                             "content_from": str(scope[0]) if scope[0] else None,
                             "content_to": str(scope[1]) if scope[1] else None,
                             "retrieved_utc": now(), "state": state, "http_status": http_status,
                             "attempts": attempts, "path": path, "sha256": digest, "bytes": size, "detail": detail})

    def read(self, key: str) -> bytes | None:
        r = self._latest.get(key)
        if not r or not r.get("path"):
            return None
        data = (self.root / r["path"]).read_bytes()
        return gzip.decompress(data) if r["path"].endswith(".gz") else data

    def event(self, ev: dict) -> None:
        """Non-request audit events (pass starts / completions / guard notices)."""
        with open(self.root / "acquisition" / "events.jsonl", "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps({"utc": now(), **ev}, sort_keys=True, default=str) + "\n")

    def index(self, category: str) -> list:
        """Latest record of every request in `category` (state, path, sha256): the per-category evidence index."""
        return sorted(({k: r[k] for k in ("request_key", "state", "path", "sha256", "http_status", "detail")}
                       for r in self._latest.values() if r["category"] == category), key=lambda x: x["request_key"])

    def summary(self) -> dict:
        by: dict = {}
        for r in self._latest.values():
            by.setdefault(r["category"], {}).setdefault(r["state"], 0)
            by[r["category"]][r["state"]] += 1
        return by
