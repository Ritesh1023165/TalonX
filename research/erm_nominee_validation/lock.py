"""ERM nominee -- protocol and implementation LOCK records: build and verify (no GO, no release, no data).

  python -m research.erm_nominee_validation.lock verify            exit 0 only if every check passes
  python -m research.erm_nominee_validation.lock write --commit SHA    (re)build the two lock records (owner-authorised)

Authoritative byte representation: the committed git blob bytes, checked out VERBATIM. Every locked path is covered by
a .gitattributes rule that disables end-of-line conversion (`-text`) or pins LF (`text eol=lf`), so a fresh checkout on
any platform reproduces the committed bytes and therefore the recorded sha256. Files written for this lock are LF.

Digest rules (no circular definitions):
  * implementation_sha256 = sha256(json.dumps({path: sha256(file bytes)}, sort_keys=True)) over
    research/erm_nominee_validation/**/*.py plus the frozen modules in release.FROZEN_IMPL (release.implementation_hash).
    It EXCLUDES every document, test and lock record (including both lock records).
  * The protocol lock records the sha256 of: the final protocol, the owner decision record (md) and decision fields
    (json), the authoritative V2.1 rule sources, and the config hash computed from the decision fields. It does NOT
    hash itself or the implementation lock.
  * The implementation lock records implementation_sha256 + every per-file sha256 + the commit it was built from. It
    does NOT hash itself or the protocol lock.
  * A later GO / release binds sha256(ERM_NOMINEE_PROTOCOL_LOCK.json) and implementation_sha256; release.py refuses a
    request whose implementation hash differs from the implementation lock or whose config hash differs from the
    protocol lock.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
PRE = "docs/research/preregistration/"
PROTOCOL = PRE + "ERM_NOMINEE_PROTOCOL_FINAL.md"
DECISION_MD = PRE + "ERM_NOMINEE_OWNER_DECISION_RECORD_B.md"
DECISION_JSON = PRE + "ERM_NOMINEE_OWNER_DECISIONS_B.json"
PROTOCOL_LOCK = PRE + "ERM_NOMINEE_PROTOCOL_LOCK.json"
IMPLEMENTATION_LOCK = PRE + "ERM_NOMINEE_IMPLEMENTATION_LOCK.json"
RULE_SOURCES = (PRE + "ERM_NOMINEE_CORRECTION_SPEC_V2_1.md", PRE + "ERM_NOMINEE_CORRECTION_V2_1_FREEZE.json",
                "research/erm_nominee_audit/v2_rules.py")
SUPERSEDED_DRAFTS = (PRE + "ERM_NOMINEE_PREREG_DRAFT_r9.md", PRE + "ERM_NOMINEE_PREREG_DRAFT_r10.md")
WINDOW = "B"
R_SENTINEL = date(2000, 1, 3)       # placeholder reference date used only to render the symbolic scope template


def sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def config(root: Path):
    from research.erm_nominee_validation.config import OwnerDecisions, ValidationConfig
    dec = OwnerDecisions(**json.loads((root / DECISION_JSON).read_text(encoding="utf-8")))
    return ValidationConfig(WINDOW, dec)


def scope_template() -> dict:
    """release.scope_envelopes for window B with the reference date left SYMBOLIC ("R", "R+1"). The execution-time R is
    instantiated in the release request (download_date) and bound by the GO before any acquisition."""
    from datetime import timedelta
    from research.erm_nominee_validation.acquisition.period import PERIODS, RETRIEVAL_WINDOW_DAYS, scope_envelopes
    env = scope_envelopes(PERIODS[WINDOW], R_SENTINEL)
    r, r1 = R_SENTINEL.isoformat(), (R_SENTINEL + timedelta(days=RETRIEVAL_WINDOW_DAYS)).isoformat()
    sub = {r: "R", r1: f"R+{RETRIEVAL_WINDOW_DAYS}"}
    return {k: [[sub.get(a, a), sub.get(b, b)] for a, b in v] for k, v in env.items()}


def build_protocol_lock(root: Path = HERE) -> dict:
    cfg = config(root)
    cfg.require_decided()
    return {"lock": "ERM_NOMINEE_PROTOCOL_LOCK", "hypothesis": cfg.canonical()["hypothesis"], "window_id": WINDOW,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "protocol": {"path": PROTOCOL, "sha256": sha(root / PROTOCOL)},
            "decision_record": {"md": {"path": DECISION_MD, "sha256": sha(root / DECISION_MD)},
                                "json": {"path": DECISION_JSON, "sha256": sha(root / DECISION_JSON)}},
            "authoritative_rules": {p: sha(root / p) for p in RULE_SOURCES},
            "superseded_drafts_preserved": {p: sha(root / p) for p in SUPERSEDED_DRAFTS},
            "config": cfg.canonical(), "config_hash": cfg.config_hash(),
            "scope_template": scope_template(),
            "byte_representation": "committed git blob bytes, checked out verbatim (.gitattributes -text / eol=lf)",
            "digest_rules": "see research/erm_nominee_validation/lock.py docstring; this record is not part of any "
                            "digest it contains",
            "not_a_go": True, "release_active": False}


def build_implementation_lock(root: Path = HERE, commit: str = "") -> dict:
    from research.erm_nominee_validation.release import implementation_hash
    agg, per = implementation_hash(root)
    return {"lock": "ERM_NOMINEE_IMPLEMENTATION_LOCK", "window_id": WINDOW, "commit": commit,
            "created_utc": datetime.now(timezone.utc).isoformat(), "implementation_sha256": agg, "files_sha256": per,
            "digest_rules": "implementation_sha256 = sha256(json.dumps(files_sha256, sort_keys=True)); excludes "
                            "documents, tests and both lock records",
            "not_a_go": True}


def verify(root: Path = HERE) -> list[str]:
    """Recompute everything from the bytes on disk. [] = pass."""
    from research.erm_nominee_validation.release import implementation_hash
    probs = []
    for p in (PROTOCOL_LOCK, IMPLEMENTATION_LOCK):
        if not (root / p).exists():
            return [f"missing {p}"]
    pl = json.loads((root / PROTOCOL_LOCK).read_text(encoding="utf-8"))
    il = json.loads((root / IMPLEMENTATION_LOCK).read_text(encoding="utf-8"))
    checks = [(pl["protocol"]["path"], pl["protocol"]["sha256"]),
              (pl["decision_record"]["md"]["path"], pl["decision_record"]["md"]["sha256"]),
              (pl["decision_record"]["json"]["path"], pl["decision_record"]["json"]["sha256"])]
    checks += list(pl["authoritative_rules"].items()) + list(pl["superseded_drafts_preserved"].items())
    for path, want in checks:
        got = sha(root / path) if (root / path).exists() else None
        if got != want:
            probs.append(f"{path}: sha256 {got} != locked {want}")
    try:
        cfg = config(root)
        if cfg.config_hash() != pl["config_hash"] or cfg.canonical() != pl["config"]:
            probs.append(f"config hash {cfg.config_hash()} != locked {pl['config_hash']}")
        cfg.require_decided()
    except Exception as e:  # noqa: BLE001
        probs.append(f"decision fields invalid: {type(e).__name__}: {e}")
    if scope_template() != pl["scope_template"]:
        probs.append("scope template recomputed from code differs from the locked template")
    agg, per = implementation_hash(root)
    if agg != il["implementation_sha256"]:
        diff = sorted(k for k in set(per) | set(il["files_sha256"]) if per.get(k) != il["files_sha256"].get(k))
        probs.append(f"implementation_sha256 {agg} != locked {il['implementation_sha256']} (files: {diff[:5]})")
    if pl.get("not_a_go") is not True or il.get("not_a_go") is not True:
        probs.append("a lock record claims to be a GO")
    return probs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=("verify", "write"))
    ap.add_argument("--commit", default="")
    ap.add_argument("--root", default=str(HERE))
    a = ap.parse_args(argv)
    root = Path(a.root)
    if a.action == "write":
        for p, doc in ((PROTOCOL_LOCK, build_protocol_lock(root)), (IMPLEMENTATION_LOCK, build_implementation_lock(root, a.commit))):
            (root / p).write_bytes((json.dumps(doc, indent=1, sort_keys=True) + "\n").encode("utf-8"))
    probs = verify(root)
    out = {"lock_verify": "PASS" if not probs else "FAIL", "problems": probs,
           "protocol_lock_sha256": sha(root / PROTOCOL_LOCK) if (root / PROTOCOL_LOCK).exists() else None}
    if (root / IMPLEMENTATION_LOCK).exists():
        out["implementation_sha256"] = json.loads((root / IMPLEMENTATION_LOCK).read_text())["implementation_sha256"]
    print(json.dumps(out, indent=1))
    return 0 if not probs else 1


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    sys.exit(main())
