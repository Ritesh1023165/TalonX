"""Phase B: the vendored Task75B guard (byte-identical copy) refuses both reserved windows at both layers, and the
split-metadata query segments never touch them."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from research.raw_adjustment_audit import holdout_guard as H
from research.raw_adjustment_audit.split_events import SEGMENTS

VENDORED_SHA256 = "e332e7785dca41226032d457eeca3f1d48c82ba9785ee9c6f9da53d4492295e6"


def test_guard_is_byte_identical_to_task75b():
    p = Path(H.__file__)
    assert hashlib.sha256(p.read_bytes()).hexdigest() == VENDORED_SHA256


@pytest.mark.parametrize("layer", ["DOWNLOAD", "LOAD"])
@pytest.mark.parametrize("s,e", [("2024-06-01", "2024-06-01"), ("2024-09-02", "2024-09-10"),
                                 ("2024-10-21", "2024-10-21"), ("2024-12-01", "2025-01-10")])
def test_guard_refuses_both_reserved_windows(tmp_path, layer, s, e):
    g = H.HoldoutGuard("PREFLIGHT", tmp_path / "state.json")
    with pytest.raises(H.HoldoutViolation):
        g.check_range(s, e, layer=layer)


def test_split_query_segments_avoid_reserved_windows(tmp_path):
    g = H.HoldoutGuard("PREFLIGHT", tmp_path / "state.json")
    for s, e in SEGMENTS:
        g.check_range(s, e, layer="DOWNLOAD")
