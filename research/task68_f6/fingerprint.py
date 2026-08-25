"""
research/task68_f6/fingerprint.py
------------------------------------
Computes F6_FADE_V1's strategy fingerprint: a sha256 over a canonical
JSON serialization of every economically meaningful field in
results/task68_f6_freeze/f6_fade_v1_spec.json. Excludes pure provenance/
prose fields (timestamps, rationale text, source-commit pointers) that
carry no behavioral meaning -- changing THOSE should not flip the
fingerprint, but changing anything that actually affects what trades get
generated (threshold, direction rule, timing, exit, costs, sizing,
universe, ...) must.

Deterministic: same spec content -> same fingerprint, on any machine, any
run order (sorted keys, fixed separators).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

SPEC_PATH = Path(__file__).resolve().parents[2] / "results" / "task68_f6_freeze" / "f6_fade_v1_spec.json"

# Fields intentionally EXCLUDED from the fingerprint: provenance/prose
# metadata that documents WHY a value was chosen or WHEN the spec was
# written, not a behavioral semantic itself. Every other top-level key in
# the spec is included.
_EXCLUDED_FIELDS = frozenset({
    "spec_created_at",
    "source_task67b_sha",
    "development_dataset_identity_or_hash",
    "selection_rationale",
    "holding_period_rationale",
    "cost_rationale",
})


def load_spec(spec_path: Path = SPEC_PATH) -> dict:
    with open(spec_path, encoding="utf-8") as f:
        return json.load(f)


def economically_meaningful_subset(spec: dict) -> dict:
    return {k: v for k, v in spec.items() if k not in _EXCLUDED_FIELDS}


def compute_fingerprint(spec: dict | None = None) -> str:
    if spec is None:
        spec = load_spec()
    subset = economically_meaningful_subset(spec)
    canonical = json.dumps(subset, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def main() -> None:
    spec = load_spec()
    fp = compute_fingerprint(spec)
    out = {
        "strategy_id": spec["strategy_id"],
        "strategy_version": spec["strategy_version"],
        "fingerprint_method": "sha256 over canonical (sorted-key, compact-separator) JSON of every f6_fade_v1_spec.json top-level field EXCEPT the provenance/prose fields listed in fingerprint.py's _EXCLUDED_FIELDS.",
        "excluded_fields": sorted(_EXCLUDED_FIELDS),
        "fingerprint": fp,
        "spec_path": str(SPEC_PATH),
    }
    out_path = SPEC_PATH.parent / "f6_fade_v1_fingerprint.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"[fingerprint] {fp}")
    print(f"[fingerprint] wrote {out_path}")


if __name__ == "__main__":
    main()
