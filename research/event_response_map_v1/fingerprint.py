"""EVENT_RESPONSE_MAP_V1 design-lock fingerprint: sha256 over the canonical SPEC json + every locked code/config file.
Phase D refuses to run unless the recomputed fingerprint equals the one in results/event_response_map_v1/design_lock.json."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCKED_FILES = (
    "research/common/research_stats.py",
    "research/common/locked_range_guard.py",
    "research/event_response_map_v1/spec.py",
    "research/event_response_map_v1/data.py",
    "research/event_response_map_v1/universe.py",
    "research/event_response_map_v1/events.py",
    "research/event_response_map_v1/metrics.py",
    "research/event_response_map_v1/phase_d.py",
    "research/event_response_map_v1/instrument_filter.py",
    "research/event_response_map_v1/identity.py",
    "research/event_response_map_v1/r3_metadata.py",
    "research/event_response_map_v1/fingerprint.py",
    "docs/research/preregistration/rs_sector_mapping_v1.json",
    "talonx_v2/cluster_engine.py",
    "talonx_v2/config.py",
    "talonx_v2/form4_source.py",
    "talonx_v2/calendar.py",
    "research/scripts/task107a_form4_build.py",
    "talonx_premarket/universe.py",
    "research/event_response_map_v1/universe_source.py",
)


def file_hashes(root: Path = ROOT) -> dict:
    # newline-normalized so a checkout with different line endings yields the same identity
    return {f: hashlib.sha256((root / f).read_bytes().replace(b"\r\n", b"\n")).hexdigest() for f in LOCKED_FILES}


def lf_sha256(path: Path) -> str:
    """sha256 of newline-normalized bytes (identical on every checkout regardless of core.autocrlf)."""
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def fingerprint(root: Path = ROOT) -> str:
    from research.event_response_map_v1.spec import SPEC
    doc = {"spec": SPEC, "files": file_hashes(root)}
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def verify(root: Path = ROOT) -> str:
    lock = json.loads((root / "results/event_response_map_v1/design_lock.json").read_text())
    fp = fingerprint(root)
    if fp != lock["fingerprint"]:
        raise RuntimeError(f"design-lock fingerprint mismatch: {fp} != {lock['fingerprint']}")
    return fp
