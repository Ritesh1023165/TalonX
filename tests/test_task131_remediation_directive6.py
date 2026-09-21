"""
Task 131 Remediation Directive 6 -- the TALONX_V2_DURABLE_STORE_ENABLED
feature flag (default False, gating the Task 131 durable-lifecycle
admission-policy changes) and the static, versioned CIK_MANIFEST_V1 for
the broad-discovery population. Also confirms every discovery/dispatch
toggle defaults OFF.
"""
from __future__ import annotations

import json
from datetime import date

from talonx_ingest.intelligence.service.broad_discovery import (
    DEFAULT_MANIFEST_PATH,
    broad_discovery_enabled,
    resolve_broad_discovery,
)
from talonx_ops.official_dispatch import broad_discovery_dispatch_enabled
from talonx_v2 import form4_source
from talonx_v2.config import V2Config
from talonx_v2.service import V2Service
from talonx_v2.store import V2Store


def _svc(tmp_path, rows):
    svc = V2Service(config=V2Config(db_path=str(tmp_path / "v2.db"), starting_cash_usd=300_000.0,
                                    per_position_allocation_usd=10_000.0),
                    bar_dirs=[tmp_path], form4_kind="parquet", status_path=str(tmp_path / "s.json"))
    svc._records = lambda *, as_of: form4_source.from_rows(rows)
    from talonx_v2 import calendar as vc
    bars = [{"date": s.isoformat(), "open": 100.0, "close": 100.0, "volume": 500_000}
           for s in vc._sessions() if date(2026, 6, 1) <= s <= date(2026, 10, 15)]
    svc._bars = lambda sym: bars
    svc._price = lambda sym, session: next(
        (b for b in bars if b["date"] == (session.isoformat()
                                          if isinstance(session, date) else str(session)[:10])), None)
    return svc


def _rows(sym="COLD"):
    return [
        dict(symbol=sym, issuer_cik=sym + "c", owner_cik=sym + "1", filing_date="2026-08-14",
             accession=sym + "a1", transaction_value=500_000, is_officer=True, transaction_code="P"),
        dict(symbol=sym, issuer_cik=sym + "c", owner_cik=sym + "2", filing_date="2026-08-14",
             accession=sym + "a2", transaction_value=700_000, is_director=True, transaction_code="P"),
    ]


def test_flag_off_reproduces_the_permissive_cold_start_policy(tmp_path, monkeypatch):
    monkeypatch.setenv("TALONX_V2_DURABLE_STORE_ENABLED", "false")
    svc = _svc(tmp_path, _rows())
    assert svc.durable_store_gate_enabled is False
    # single tick, ON the entry session itself, no earlier tick ever ran --
    # the exact scenario the ORIGINAL (pre-131) cold-start-backfill policy
    # allowed, and the gated policy (Directive 2) refuses.
    st = svc.tick(as_of=date(2026, 8, 17))
    assert st["entries_this_tick"] == 1
    store = V2Store(str(tmp_path / "v2.db"), starting_cash=300_000.0)
    assert store.n_open() == 1


def test_flag_on_enforces_the_gated_policy(tmp_path, monkeypatch):
    monkeypatch.setenv("TALONX_V2_DURABLE_STORE_ENABLED", "true")
    svc = _svc(tmp_path, _rows())
    assert svc.durable_store_gate_enabled is True
    st = svc.tick(as_of=date(2026, 8, 17))
    assert st["entries_this_tick"] == 0
    assert st["no_prior_intent_skipped_this_tick"] == 1


def test_flag_defaults_false_when_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("TALONX_V2_DURABLE_STORE_ENABLED", raising=False)
    svc = V2Service(config=V2Config(db_path=str(tmp_path / "v2.db")), bar_dirs=[tmp_path],
                    form4_kind="parquet", status_path=str(tmp_path / "s.json"))
    assert svc.durable_store_gate_enabled is False


def test_all_discovery_and_dispatch_toggles_default_off(monkeypatch):
    for var in ("TALONX_INTEL_ENABLE_BROAD_DISCOVERY", "TALONX_DISPATCH_ENABLE_BROAD_DISCOVERY",
               "TALONX_V2_DURABLE_STORE_ENABLED"):
        monkeypatch.delenv(var, raising=False)
    assert broad_discovery_enabled() is False
    assert broad_discovery_dispatch_enabled() is False


def test_real_manifest_carries_a_valid_static_cik_manifest_v1():
    assert DEFAULT_MANIFEST_PATH.is_file()
    data = json.loads(DEFAULT_MANIFEST_PATH.read_text())
    cm = data.get("cik_manifest")
    assert cm is not None
    assert cm["manifest_version"] == "CIK_MANIFEST_V1"
    assert cm["n_resolved"] == len(cm["resolved"])
    assert cm["n_unresolved"] == len(cm["unresolved"])
    assert cm["n_resolved"] + cm["n_unresolved"] == data["n_symbols"]
    # never a live network/CikDirectory call needed to resolve from it
    res = resolve_broad_discovery(directory=None)
    assert res.universe_n == data["n_symbols"]
    assert len(res.resolved) == cm["n_resolved"]
