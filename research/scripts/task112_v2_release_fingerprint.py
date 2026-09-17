"""
task112_v2_release_fingerprint.py -- deterministic V2 release fingerprint (Phase 11)
================================================================================
A stable sha256 (first 16 hex) over the FROZEN V2 strategy definition:
its config values + the source of the modules that carry strategy
semantics (cluster detection, liquidity gate, config).  Operational /
plumbing modules (bus, run, service, store, dashboard_read, pipeline
orchestration) are NOT in the fingerprint -- they may be fixed for
safety/observability without invalidating the strategy.

  python research/scripts/task112_v2_release_fingerprint.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: modules whose bytes define the V2 STRATEGY (not its plumbing)
_STRATEGY_FILES = (
    ROOT / "talonx_v2" / "config.py",
    ROOT / "talonx_v2" / "cluster_engine.py",
    ROOT / "talonx_v2" / "liquidity.py",
    ROOT / "talonx_v2" / "quant_bridge.py",
    ROOT / "talonx_v2" / "brain_bridge.py",
)


def v2_release_fingerprint() -> dict:
    from talonx_v2.config import (
        V2_VERSION, V2_STATUS, V2_RESEARCH_SOURCE, V2Config,
    )

    c = V2Config()
    cfg = {
        "cluster_window_trading_days": c.cluster_window_trading_days,
        "min_distinct_owners": c.min_distinct_owners,
        "transaction_code": c.transaction_code,
        "direction": c.direction,
        "entry_offset_sessions": c.entry_offset_sessions,
        "hold_trading_days": c.hold_trading_days,
        "stop_loss_enabled": c.stop_loss_enabled,
        "max_concurrent_positions": c.max_concurrent_positions,
        "reentry_cooldown_trading_days": c.reentry_cooldown_trading_days,
        "liquidity_lookback_sessions": c.liquidity_lookback_sessions,
        "liquidity_min_median_dollar_volume": c.liquidity_min_median_dollar_volume,
        "liquidity_min_close": c.liquidity_min_close,
        "exit_fallforward_max_sessions": c.exit_fallforward_max_sessions,
        "max_entry_staleness_sessions": c.max_entry_staleness_sessions,
    }

    digest = hashlib.sha256()
    digest.update(json.dumps(cfg, sort_keys=True).encode())
    digest.update(V2_VERSION.encode())
    for p in _STRATEGY_FILES:
        try:
            # RI-1: LF-normalize before hashing -- the SAME fix Task 137
            # already applied to get_strategy_version() (V1's fingerprint)
            # for the identical defect: a working tree that materializes
            # these files with CRLF (Windows `core.autocrlf`) previously
            # produced a DIFFERENT fingerprint than the LF blobs actually
            # committed to git, so the same content could hash differently
            # depending purely on line-ending churn (confirmed directly
            # during RI-1 via a git stash/pop roundtrip, which alone
            # shifted this fingerprint with zero real content change). A
            # genuine content change is still fully detected; only the
            # line-ending REPRESENTATION stops being significant.
            digest.update(p.read_bytes().replace(b"\r\n", b"\n"))
        except OSError:
            digest.update(b"MISSING:" + str(p).encode())

    return {
        "strategy_version": V2_VERSION,
        "status": V2_STATUS,
        "research_source": V2_RESEARCH_SOURCE,
        "config": cfg,
        "strategy_files": [str(p.relative_to(ROOT)).replace("\\", "/") for p in _STRATEGY_FILES],
        "fingerprint": digest.hexdigest()[:16],
    }


if __name__ == "__main__":
    print(json.dumps(v2_release_fingerprint(), indent=2))
