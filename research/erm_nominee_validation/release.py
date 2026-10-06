"""ERM nominee -- narrowly scoped guard RELEASE for ONE hypothesis / window (built, INACTIVE).

There is no guard-disable option. A validation-window request is allowed only by a ReleasedGuard, which exists only
when `load_release` validates a COMPLETE release journal whose every hash still matches:

  ReleaseRequest = {hypothesis, window_id, config_hash, protocol_lock_sha256, implementation_sha256,
                    owner_decisions_sha256, go_record_sha256, download_date, scope}
    * hypothesis    == config.HYPOTHESIS (the only nominee)
    * config        == require_decided() passes and config_hash matches
    * protocol lock == sha256 of the LOCKED protocol record (PROTOCOL_LOCK); absent today -> refused
    * implementation== aggregate sha256 of research/erm_nominee_validation/**/*.py + frozen modules it imports
    * owner decisions / GO == sha256 of the committed decision record and a SEPARATE GO record naming this release
    * scope         == period.scope_envelopes(window, download_date) EXACTLY (wider, narrower, other category ->
                       refused)
  Transition (ReleaseStore, append-only, fsync'd journal):
      PREPARED -> ERM_AUDIT_WRITTEN -> TASK75_LEDGER_WRITTEN -> ACTIVE
    * ERM audit record      erm_guard_release_audit.json      (ERM-owned)
    * Task75 ledger         task75_reserve_consumption.json  (ERM-owned record that the Task75 reserved windows
                                                                inside the scope are consumed by THIS release; the
                                                                original Task75 study and its files are never
                                                                modified or released)
    * the journal must reach ACTIVE with all four states, one release id, both records consistent; an interrupted
      transition (any prefix) is INCOMPLETE and refuses every protected request. A store holding any journal refuses a
      second activation (no re-use, no overwrite).
The frozen EVENT_RESPONSE_MAP_V1 LockedRangeGuard and its guard_state.json are never written.

INACTIVE: production uses `production_guard`, which returns the always-refusing ValidationGuard unless the production
store PRODUCTION_STORE holds a valid ACTIVE journal. No code path creates that store: `activate` is a library function
with no CLI, and it is refused without a separate GO record (none exists). The protocol and implementation locks
(lock.py) are bound: a release whose implementation or config hash differs from them is refused.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from research.common.locked_range_guard import EVENT_RESPONSE_MAP_V1, HoldoutViolation, LockedRangeGuard
from research.erm_nominee_validation.acquisition.guards import AcquisitionRefused, norm
from research.erm_nominee_validation.acquisition.period import PERIODS, TASK75_RESERVED, scope_envelopes
from research.erm_nominee_validation.config import HYPOTHESIS, ValidationConfig
from research.erm_nominee_validation.guard import GuardReleaseNotAuthorised, ValidationGuard, check_authorisation_scope

HERE = Path(__file__).resolve().parents[2]
PROTOCOL_LOCK = Path("docs/research/preregistration/ERM_NOMINEE_PROTOCOL_LOCK.json")
IMPLEMENTATION_LOCK = Path("docs/research/preregistration/ERM_NOMINEE_IMPLEMENTATION_LOCK.json")
GO_RECORD = Path("docs/research/preregistration/ERM_NOMINEE_VALIDATION_GO_{window}.json")      # does not exist (no GO)
DECISIONS = Path("docs/research/preregistration/ERM_NOMINEE_OWNER_DECISIONS_{window}.json")
PRODUCTION_STORE = Path("results/erm_nominee_validation/guard_release")                       # never created here
STATES = ("PREPARED", "ERM_AUDIT_WRITTEN", "TASK75_LEDGER_WRITTEN", "ACTIVE")
FROZEN_IMPL = ("research/erm_nominee_audit/v2_rules.py", "research/event_response_map_v1/data.py",
               "research/event_response_map_v1/events.py", "research/event_response_map_v1/identity.py",
               "research/event_response_map_v1/universe.py", "research/event_response_map_v1/universe_source.py",
               "research/event_response_map_v1/r3_metadata.py", "research/event_response_map_v1/instrument_filter.py",
               "research/event_response_map_v1/metrics.py", "research/common/locked_range_guard.py",
               "research/common/research_stats.py")


class ReleaseInvalid(GuardReleaseNotAuthorised):
    pass


def sha_file(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def implementation_hash(root: Path = HERE) -> tuple[str, dict]:
    files = sorted((root / "research/erm_nominee_validation").rglob("*.py")) + [root / p for p in FROZEN_IMPL]
    per = {p.relative_to(root).as_posix(): sha_file(p) for p in files}
    agg = hashlib.sha256(json.dumps(per, sort_keys=True).encode()).hexdigest()
    return agg, per


@dataclass(frozen=True)
class ReleaseRequest:
    hypothesis: str
    window_id: str
    config_hash: str
    protocol_lock_sha256: str
    implementation_sha256: str
    owner_decisions_sha256: str
    go_record_sha256: str
    download_date: str
    scope: dict

    def canonical(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))

    @property
    def release_id(self) -> str:
        return hashlib.sha256(self.canonical().encode()).hexdigest()


def current_hashes(cfg: ValidationConfig, root: Path = HERE) -> dict:
    """Hashes of the artefacts a release must bind to, read NOW (records under `root`; the implementation hash is
    always computed from THIS code tree). A missing artefact -> None (refused)."""
    w = cfg.window_id
    get = lambda p: sha_file(root / p) if (root / p).exists() else None  # noqa: E731
    go = Path(str(GO_RECORD).format(window=w))
    return {"protocol_lock_sha256": get(PROTOCOL_LOCK), "implementation_sha256": implementation_hash()[0],
            "owner_decisions_sha256": get(Path(str(DECISIONS).format(window=w))), "go_record_sha256": get(go),
            "go_path": str(root / go), "root": str(root)}


def validate_request(r: ReleaseRequest, cfg: ValidationConfig, cur: dict) -> None:
    cfg.require_decided()                                            # every owner decision recorded, window consistent
    if r.hypothesis != HYPOTHESIS:
        raise ReleaseInvalid(f"release is for hypothesis {r.hypothesis!r}, only {HYPOTHESIS!r} may be released")
    if r.window_id != cfg.window_id or r.window_id not in ("A", "B"):
        raise ReleaseInvalid(f"release window {r.window_id!r} != configured {cfg.window_id!r}")
    if r.config_hash != cfg.config_hash():
        raise ReleaseInvalid("config hash changed since the release was prepared")
    for k in ("protocol_lock_sha256", "implementation_sha256", "owner_decisions_sha256", "go_record_sha256"):
        if not cur.get(k):
            raise ReleaseInvalid(f"{k}: required artefact does not exist (no locked protocol / decision / GO)")
        if getattr(r, k) != cur[k]:
            raise ReleaseInvalid(f"{k} mismatch: release {getattr(r, k)[:12]} != current {cur[k][:12]}")
    exp = scope_envelopes(PERIODS[r.window_id], date.fromisoformat(r.download_date))
    if set(r.scope) - set(exp):
        raise ReleaseInvalid(f"scope names other input categories: {sorted(set(r.scope) - set(exp))}")
    if set(exp) - set(r.scope):
        raise ReleaseInvalid(f"incomplete scope: missing {sorted(set(exp) - set(r.scope))}")
    for k, v in exp.items():
        if r.scope[k] != v:
            wider = any(norm(a, b)[0] < norm(x, y)[0] or norm(a, b)[1] > norm(x, y)[1]
                        for a, b in r.scope[k] for x, y in v)
            raise ReleaseInvalid(f"scope for {k} {'WIDER than' if wider else 'differs from'} the window: "
                                 f"{r.scope[k]} != {v}")
    root = Path(cur.get("root") or HERE)                            # the GO binds the LOCKED protocol / implementation
    il, pl = root / IMPLEMENTATION_LOCK, root / PROTOCOL_LOCK
    if not il.exists():
        raise ReleaseInvalid("no implementation lock record")
    if json.loads(il.read_text(encoding="utf-8")).get("implementation_sha256") != r.implementation_sha256:
        raise ReleaseInvalid("implementation hash differs from the implementation lock")
    if json.loads(pl.read_text(encoding="utf-8")).get("config_hash") != r.config_hash:
        raise ReleaseInvalid("config hash differs from the protocol lock")
    go = json.loads(Path(cur["go_path"]).read_text())             # the GO is a SEPARATE record naming this scope
    if not (go.get("owner_go") is True and go.get("hypothesis") == r.hypothesis and go.get("window_id") == r.window_id
            and go.get("config_hash") == r.config_hash and go.get("protocol_lock_sha256") == r.protocol_lock_sha256
            and go.get("implementation_sha256") == r.implementation_sha256 and go.get("scope") == r.scope):
        raise ReleaseInvalid("GO record does not name exactly this hypothesis / window / hashes / scope")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_once(p: Path, text: str) -> None:
    if p.exists():
        raise ReleaseInvalid(f"{p.name} already exists: release records are never overwritten")
    with open(p, "x", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())


class ReleaseStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.journal = self.root / "release_journal.jsonl"
        self.erm_audit = self.root / "erm_guard_release_audit.json"
        self.task75 = self.root / "task75_reserve_consumption.json"

    def entries(self) -> list:
        if not self.journal.exists():
            return []
        return [json.loads(x) for x in self.journal.read_text(encoding="utf-8").splitlines() if x.strip()]

    def append(self, state: str, release_id: str, **kw) -> None:
        with open(self.journal, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps({"state": state, "release_id": release_id, "utc": _now(), **kw}, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())


def task75_overlap(scope: dict) -> list:
    out = []
    for a, b in TASK75_RESERVED:
        cats = sorted(k for k, v in scope.items() for x, y in v if norm(x, y)[0] <= b and a <= norm(x, y)[1])
        if cats:
            out.append({"reserved_window": [a.isoformat(), b.isoformat()], "categories": cats})
    return out


def activate(store: ReleaseStore, r: ReleaseRequest, cfg: ValidationConfig, cur: dict, *, _crash_after=None):
    """The ONLY transition. Library function, no CLI. `_crash_after` (tests) simulates an interruption."""
    validate_request(r, cfg, cur)
    store.root.mkdir(parents=True, exist_ok=True)
    if store.entries():
        raise ReleaseInvalid("release store already holds a journal: no second activation")
    rid = r.release_id
    store.append("PREPARED", rid, request=json.loads(r.canonical()))
    if _crash_after == "PREPARED":
        raise RuntimeError("simulated interruption after PREPARED")
    _write_once(store.erm_audit, json.dumps({"program": "EVENT_RESPONSE_MAP_V1", "release_id": rid,
                                             "request": json.loads(r.canonical()), "utc": _now(),
                                             "note": "scoped release of ONE hypothesis / window; frozen guard state "
                                                     "untouched"}, indent=1, sort_keys=True))
    store.append("ERM_AUDIT_WRITTEN", rid, sha256=sha_file(store.erm_audit))
    if _crash_after == "ERM_AUDIT_WRITTEN":
        raise RuntimeError("simulated interruption after ERM_AUDIT_WRITTEN")
    _write_once(store.task75, json.dumps({"ledger": "TASK75_RESERVE_CONSUMPTION (ERM-owned)", "release_id": rid,
                                          "consumed": task75_overlap(r.scope), "hypothesis": r.hypothesis,
                                          "window_id": r.window_id, "utc": _now(),
                                          "note": "the original Task75 study is not modified or released"},
                                         indent=1, sort_keys=True))
    store.append("TASK75_LEDGER_WRITTEN", rid, sha256=sha_file(store.task75))
    if _crash_after == "TASK75_LEDGER_WRITTEN":
        raise RuntimeError("simulated interruption after TASK75_LEDGER_WRITTEN")
    store.append("ACTIVE", rid)
    return load_release(store, cfg, cur)


def load_release(store: ReleaseStore, cfg: ValidationConfig, cur: dict) -> "ReleasedGuard":
    e = store.entries()
    if [x["state"] for x in e] != list(STATES):
        raise ReleaseInvalid(f"release transition incomplete or malformed: {[x['state'] for x in e]}")
    rid = {x["release_id"] for x in e}
    if len(rid) != 1:
        raise ReleaseInvalid("journal mixes release ids")
    rid = rid.pop()
    r = ReleaseRequest(**e[0]["request"])
    if r.release_id != rid:
        raise ReleaseInvalid("journal request does not hash to its release id")
    for f, st in ((store.erm_audit, "ERM_AUDIT_WRITTEN"), (store.task75, "TASK75_LEDGER_WRITTEN")):
        if not f.exists() or sha_file(f) != next(x for x in e if x["state"] == st)["sha256"]:
            raise ReleaseInvalid(f"{f.name} missing or changed since the transition")
        if json.loads(f.read_text())["release_id"] != rid:
            raise ReleaseInvalid(f"{f.name} names another release")
    if json.loads(store.task75.read_text())["consumed"] != task75_overlap(r.scope):
        raise ReleaseInvalid("Task75 ledger inconsistent with the released scope")
    validate_request(r, cfg, cur)                                    # every hash re-checked at load time
    return ReleasedGuard(cfg, r)


class ScopedFrameGuard:
    """LOAD-layer guard for a released window: a frame is accepted only if every row lies inside the released bar
    envelope; anything else goes to the frozen guard (which refuses 2024+)."""

    def __init__(self, envelope: list, frozen: LockedRangeGuard):
        self.env, self.frozen = [norm(a, b) for a, b in envelope], frozen

    def check_range(self, start, end, *, layer: str) -> None:
        a, b = norm(start, end)
        if not any(x <= a and b <= y for x, y in self.env):
            self.frozen.check_range(a, b, layer=layer)

    def check_frame(self, df, *, layer: str = "LOAD", ts_col: str = "timestamp") -> None:
        if df is None or len(df) == 0:
            return
        import pandas as pd
        t = pd.to_datetime(df[ts_col], utc=True).dt.date
        self.check_range(t.min(), t.max(), layer=layer)

    def record(self, event: dict) -> None:               # never writes the frozen guard state
        pass


class ReleasedGuard:
    def __init__(self, cfg: ValidationConfig, r: ReleaseRequest):
        self.config, self.release = cfg, r
        self.frozen = LockedRangeGuard(EVENT_RESPONSE_MAP_V1)

    def check_acquisition(self, start, end, category: str) -> None:
        a, b = norm(start, end)
        for x, y in self.release.scope.get(category, []):
            x, y = norm(x, y)
            if x <= a and b <= y:
                return
        try:
            self.frozen.check_range(a, b, layer="DOWNLOAD")
        except HoldoutViolation as e:
            raise AcquisitionRefused(f"outside the released scope ({category} {a}..{b}): {e}") from None
        if category not in self.release.scope:
            raise AcquisitionRefused(f"category {category!r} not in the released scope")

    def check_load(self, df, what: str, ts_col: str = "timestamp") -> None:
        self.frame_guard().check_frame(df, layer="LOAD", ts_col=ts_col)

    def frame_guard(self):
        return ScopedFrameGuard(self.release.scope["bars"], self.frozen)

    def authorise(self, auth) -> None:
        check_authorisation_scope(auth, self.config)
        if auth.get("release_id") != self.release.release_id:
            raise ReleaseInvalid("authorisation names another release")

    def release_authorised(self) -> bool:
        return True


def production_guard(cfg: ValidationConfig, root: Path = HERE):
    """Production wiring. No production release store exists -> the always-refusing ValidationGuard."""
    store = ReleaseStore(root / PRODUCTION_STORE)
    if not store.journal.exists():
        return ValidationGuard(cfg, root)
    return load_release(store, cfg, current_hashes(cfg, root))
