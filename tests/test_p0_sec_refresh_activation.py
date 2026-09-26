"""Next-version P0 package 1, change A (2026-09-26): SEC background refresh activation support.

sec_refresh.py is part of discovery's version identity; the SEC cache mode is the only discovery config key a
declaration can classify DATA_FIX (closed list, declaration required, never a downgrade otherwise); per-scan cache
metrics never change what is served.
"""
from __future__ import annotations

import shutil

import pytest

from talonx_opportunity import runtime as RT
from talonx_opportunity import sec_refresh as SR
from talonx_opportunity.store import OpportunityStore
from talonx_premarket.catalysts import SecSubmissions

# ======================================================================================== SEC: version identity
def _copy_sources(dst):
    rels = set(RT._SHARED)
    for v in RT.COMPONENT_SOURCES.values():
        rels |= set(v)
    for rel in rels:
        src = RT.REPO_ROOT / rel
        if src.exists():
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst / rel)


def test_sec_refresh_is_part_of_discovery_version_identity(tmp_path, monkeypatch):
    assert "talonx_opportunity/sec_refresh.py" in RT.COMPONENT_SOURCES["discovery"]
    _copy_sources(tmp_path)
    monkeypatch.setattr(RT, "REPO_ROOT", tmp_path)
    before = {c: RT.component_version(c) for c in RT.COMPONENT_SOURCES}
    f = tmp_path / "talonx_opportunity" / "sec_refresh.py"
    f.write_text(f.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    after = {c: RT.component_version(c) for c in RT.COMPONENT_SOURCES}
    assert after["discovery"] != before["discovery"]
    assert {c: v for c, v in after.items() if c != "discovery"} == \
        {c: v for c, v in before.items() if c != "discovery"}          # no other component identity moves


# ======================================================================================== SEC: boundary class mapping
BASE_FPS = {"CONTINUOUS_RESEARCH": "a", "PREMARKET_RESEARCH_V1": "b"}
ON_FPS = {**BASE_FPS, "SEC_CATALYST_CACHE": "BACKGROUND_REFRESH_V1"}


def _start(tmp_path, fps, version="v2", decl=None, component="discovery"):
    rs = RT.RuntimeStore(tmp_path)
    if decl:
        rs.declare_change(component, decl, "SEC catalyst cache served by the idle-gated background refresher")
    out = rs.record_start(component, version=version, config_fps=fps, commit="x")
    row = rs._last_deployment(component)
    rs.close()
    return out, row


def _first(tmp_path, component="discovery", fps=BASE_FPS):
    rs = RT.RuntimeStore(tmp_path)
    rs.record_start(component, version="v1", config_fps=fps, commit="x")
    rs.close()


def test_sec_cache_key_with_data_fix_declaration_is_a_data_fix_boundary(tmp_path):
    _first(tmp_path)
    out, row = _start(tmp_path, ON_FPS, decl="DATA_FIX")
    assert out["classification"] == "DATA_FIX" and out["decided_by"] == "RULE:CONFIG_KEY_MAPPED+DECLARED"
    assert row["declared"] == 1 and not out["restart_only"]
    # rollback (flag removed) is the same kind of boundary
    out2, _ = _start(tmp_path, BASE_FPS, version="v2", decl="DATA_FIX")
    assert out2["classification"] == "DATA_FIX"


def test_sec_cache_key_without_declaration_stays_strategy_material(tmp_path):
    _first(tmp_path)
    out, _ = _start(tmp_path, ON_FPS)
    assert out["classification"] == "STRATEGY_MATERIAL" and out["decided_by"] == "RULE:CONFIG_FINGERPRINT_CHANGED"


@pytest.mark.parametrize("decl", ["OPERATIONS_ONLY", "ROUTING_FIX", "REPORTING_ONLY"])
def test_sec_cache_key_cannot_be_declared_to_another_class(tmp_path, decl):
    _first(tmp_path)
    out, _ = _start(tmp_path, ON_FPS, decl=decl)
    assert out["classification"] == "STRATEGY_MATERIAL"


def test_any_other_discovery_config_change_is_still_forced_strategy_material(tmp_path):
    _first(tmp_path)
    out, _ = _start(tmp_path, {**ON_FPS, "CONTINUOUS_RESEARCH": "changed"}, decl="DATA_FIX")
    assert out["classification"] == "STRATEGY_MATERIAL"


def test_mapping_is_discovery_only(tmp_path):
    _first(tmp_path, component="notifier", fps={"LAB_NOTIFY_POLICY": "p"})
    out, _ = _start(tmp_path, {"LAB_NOTIFY_POLICY": "p", "SEC_CATALYST_CACHE": "x"}, decl="DATA_FIX",
                    component="notifier")
    assert out["classification"] == "ROUTING_FIX"                        # notifier's forced config class


# ======================================================================================== SEC: per-scan metrics
def _subs():
    return {"filings": {"recent": {"form": ["8-K"], "filingDate": ["2026-09-24"],
                                   "acceptanceDateTime": ["2026-09-24T12:00:00Z"],
                                   "accessionNumber": ["0000000000-26-000001"], "items": ["2.02"]}}}


def _sec(fail=None):
    t = [0.0]

    def get(url, headers):
        if fail and fail["on"]:
            raise TimeoutError("timed out")
        return _subs()
    return SecSubmissions(user_agent="ua", http_get=get, clock=lambda: t[0], ttl_s=600), t


def test_scan_metrics_count_hits_fallbacks_age_and_requests_without_changing_what_is_served():
    sec, t = _sec()
    w = SR.BackgroundSecCache(sec, start=False)
    ref, tr = _sec()
    w.begin_scan()
    a = w.get("1")                                   # cold: sync fetch
    t[0] = 300.0
    b = w.get("1")                                   # fresh hit, age 300
    w.get("2")                                       # cold: sync fetch
    m = w.end_scan()
    assert (m["lookups"], m["cache_hits"], m["cache_misses"], m["sync_fallbacks"], m["sec_requests"]) == (3, 1, 2, 2, 2)
    assert m["max_served_age_s"] == 300.0 and m["hit_wait_p99_s"] is not None
    assert m["refresher_requests_during_scan"] == 0 and m["mode"] == "BACKGROUND_REFRESH"
    tr[0] = 0.0
    assert ref.get("1")[0] == a[0] == b[0]           # identical served submissions
    assert w.end_scan() == {"mode": "BACKGROUND_REFRESH"}      # no open scan -> no metrics, no error


def test_scan_metrics_report_a_stale_copy_served_on_sec_failure():
    fail = {"on": False}
    sec, t = _sec(fail)
    w = SR.BackgroundSecCache(sec, start=False)
    w.get("1")
    fail["on"] = True
    t[0] = 700.0                                     # expired + SEC down -> today's stale-copy behaviour
    w.begin_scan()
    got = w.get("1")
    m = w.end_scan()
    assert got[0] is not None and m["max_served_age_s"] == 700.0 and m["cache_misses"] == 1


def test_refresh_in_flight_when_a_scan_begins_is_counted():
    sec, t = _sec()
    w = SR.BackgroundSecCache(sec, start=False)
    w.get("1")
    t[0] = 400.0
    w.begin_scan()
    assert w.refresh_one("1") is True
    assert w.end_scan()["refresher_requests_during_scan"] == 1


def test_discovery_records_sec_cache_metrics_per_scan(tmp_path):
    from tests.test_continuous_opportunity_engine import U, Clock, FakeData, _world
    from talonx_opportunity.discovery import Discovery
    from talonx_opportunity.ingestion import Ingestion

    def run(root, sec):
        minute, daily, members = _world()
        for i, m in enumerate(members):
            m["cik"] = f"000000000{i + 1}"
        clock = Clock(U(14, 30))
        Ingestion(data=FakeData(minute, daily), root=root, clock=clock,
                  universe_loader=lambda: (members, "test")).tick()
        Discovery(root=root, clock=clock, sec=sec).tick()
        s = OpportunityStore(root, readonly=True)
        try:
            return s.con.execute("SELECT funnel_json FROM scans ORDER BY decision_utc DESC LIMIT 1").fetchone()[0]
        finally:
            s.close()

    import json
    frozen = lambda: SecSubmissions(user_agent="ua", http_get=lambda url, headers: _subs(), ttl_s=600,
                                    clock=lambda: 0.0)
    on = json.loads(run(tmp_path / "on", SR.BackgroundSecCache(frozen(), start=False)))["sec_cache"]
    off = json.loads(run(tmp_path / "off", frozen()))["sec_cache"]
    assert on["mode"] == "BACKGROUND_REFRESH" and on["lookups"] >= 1 and on["sec_requests"] == off["sec_requests"]
    assert off["mode"] == "SYNC"


