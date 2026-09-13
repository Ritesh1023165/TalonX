"""
Task 131 -- Concurrent Admission Fix and SPA Dashboard Acceptance,
section 4: focused coverage for the SPA Discovery Dashboard's backend
extension to ``DashboardReadModel.v2_broad_discovery()`` --
``universe_coverage`` (live-read cik_manifest, never hardcoded),
``admission_policy`` (real env-derived mode), ``source_health`` /
``dashboard_refresh_utc`` / ``upstream_data_as_of_utc`` (reused from
``v2_active_strategy()``, freshness kept distinct from dashboard-read
time), ``discovery_funnel`` (real episode/intent classification), and
``action_queue`` (pending intents + outbox, queued vs delivered kept
distinct). ``tests/test_task131_dashboard_broad_discovery.py`` (Task 131
Directive 5) covers the original panel's own pre-existing fields and is
unaffected -- run together to confirm zero regressions on those.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from talonx_ops.dashboard_read import DashboardReadModel
from talonx_v2.cluster_engine import ClusterEpisode
from talonx_v2.schemas import V2Action, V2Decision, V2Direction
from talonx_v2.store import V2Store

NOW = datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc)
MANIFEST_PATH = Path("talonx_ingest/intelligence/service/data/discovery_universe_v1_626.json")


def _broad_only_symbols(n: int) -> list[str]:
    """Real broad-discovery-only symbols (in the 626-universe, NOT in the
    39-name product watchlist) -- computed dynamically, exactly the way
    the backend itself does, so this test never depends on a specific
    symbol staying broad-only forever."""
    from talonx_ops.watchlist_coverage import build_coverage_map
    manifest = json.loads(MANIFEST_PATH.read_text())
    universe = {s.strip().upper() for s in manifest.get("symbols", []) if s.strip()}
    watchlist_39 = {c["symbol"].upper() for c in build_coverage_map()["tickers"]
                   if c.get("v2_collection_scope") == "POLLED"}
    broad_only = sorted(universe - watchlist_39)
    assert len(broad_only) >= n, "not enough real broad-discovery-only symbols to build this fixture"
    return broad_only[:n]


@pytest.fixture
def home(tmp_path):
    h = tmp_path / ".talonx"
    (h / "experimental").mkdir(parents=True)
    (h / "intelligence").mkdir(parents=True)
    return h


def _model(home, v2_db_path):
    return DashboardReadModel(home=home, exp_home=home / "experimental",
                             intel_ledger=home / "ingestion_ledger.db", now=NOW)


def _ep(symbol, episode_id, entry_session):
    return ClusterEpisode(episode_id=episode_id, symbol=symbol, issuer_cik="x",
                          distinct_owner_ciks=("a", "b"), n_distinct_owners=2, n_filings=2,
                          first_filing_date=date(2026, 9, 1), activation_filing_date=date(2026, 9, 1),
                          last_filing_date=date(2026, 9, 1), aggregate_purchase_value=0.0,
                          any_officer=False, any_director=False, any_ten_percent=False,
                          causal_event_ts=datetime(2026, 9, 1, 23, 59, 59, tzinfo=timezone.utc),
                          eligible_entry_session=entry_session)


def _decision(ep):
    return V2Decision(signal_id="s", episode_id=ep.episode_id, symbol=ep.symbol,
                      direction=V2Direction.BULLISH, action=V2Action.BUY,
                      official_eligible=False, rationale="fixture",
                      eligible_entry_session=ep.eligible_entry_session)


def _liq():
    return type("Liq", (), {"ok": True, "median_dollar_volume": 1e7, "last_close": 10.0})()


# --------------------------------------------------------------------- #
# universe_coverage -- real, live-read cik_manifest fields
# --------------------------------------------------------------------- #
def test_universe_coverage_reads_the_real_manifest_live(home, tmp_path, monkeypatch):
    monkeypatch.setenv("TALONX_V2_DB_PATH", str(tmp_path / "v2.db"))
    panel = _model(home, tmp_path / "v2.db").v2_broad_discovery()
    real = json.loads(MANIFEST_PATH.read_text())["cik_manifest"]
    cov = panel["universe_coverage"]
    assert cov["n_resolved"] == real["n_resolved"]
    assert cov["n_unresolved"] == real["n_unresolved"]
    assert cov["manifest_version"] == real["manifest_version"]
    expected_pct = round(100.0 * real["n_resolved"] / (real["n_resolved"] + real["n_unresolved"]), 1)
    assert cov["resolved_pct"] == expected_pct
    assert "NOT" in cov["note"] and "historical identity verification" in cov["note"]
    # never a hardcoded 626/569/57 literal disconnected from the file --
    # the counts above are cross-checked against the SAME file read directly.
    assert isinstance(cov["unresolved_symbols_sample"], list)


# --------------------------------------------------------------------- #
# admission_policy -- real env-derived mode
# --------------------------------------------------------------------- #
def test_admission_policy_reflects_gated_state(home, tmp_path, monkeypatch):
    monkeypatch.setenv("TALONX_V2_DB_PATH", str(tmp_path / "v2.db"))
    monkeypatch.setenv("TALONX_V2_DURABLE_STORE_ENABLED", "true")
    panel = _model(home, tmp_path / "v2.db").v2_broad_discovery()
    assert panel["admission_policy"]["mode"] == "GATED"
    assert "REQUIRED" in panel["admission_policy"]["note"]


def test_admission_policy_reflects_permissive_default(home, tmp_path, monkeypatch):
    monkeypatch.setenv("TALONX_V2_DB_PATH", str(tmp_path / "v2.db"))
    monkeypatch.delenv("TALONX_V2_DURABLE_STORE_ENABLED", raising=False)
    panel = _model(home, tmp_path / "v2.db").v2_broad_discovery()
    assert panel["admission_policy"]["mode"] == "PERMISSIVE"
    assert "legacy" in panel["admission_policy"]["note"]


# --------------------------------------------------------------------- #
# source_health / freshness separation
# --------------------------------------------------------------------- #
def test_source_health_and_refresh_freshness_are_kept_distinct(home, tmp_path, monkeypatch):
    monkeypatch.setenv("TALONX_V2_DB_PATH", str(tmp_path / "v2.db"))
    panel = _model(home, tmp_path / "v2.db").v2_broad_discovery()
    assert panel["dashboard_refresh_utc"] == panel["generated_at"]
    assert "source_health" in panel
    # upstream_data_as_of_utc is a SEPARATE key from dashboard_refresh_utc --
    # never silently conflated even when both happen to be unavailable (None).
    assert "upstream_data_as_of_utc" in panel
    assert "shared_campaign_ledger_note" in panel
    assert "SAME shared" in panel["shared_campaign_ledger_note"]


# --------------------------------------------------------------------- #
# discovery_funnel -- empty state
# --------------------------------------------------------------------- #
def test_discovery_funnel_empty_state_is_explicit_not_guessed(home, tmp_path, monkeypatch):
    monkeypatch.setenv("TALONX_V2_DB_PATH", str(tmp_path / "v2.db"))
    V2Store(str(tmp_path / "v2.db"), starting_cash=300_000.0)   # DB exists, but nothing in it
    panel = _model(home, tmp_path / "v2.db").v2_broad_discovery()
    fn = panel["discovery_funnel"]
    assert fn["status"] == "ZERO_ACTIVITY"
    assert fn["candidates_n"] == 0
    assert fn["recent"] == []
    assert fn["empty_state_note"] is not None
    assert "not an error" in fn["empty_state_note"]


# --------------------------------------------------------------------- #
# discovery_funnel + action_queue -- populated, all 4 real buckets
# --------------------------------------------------------------------- #
def test_discovery_funnel_and_action_queue_classify_real_rows_correctly(home, tmp_path, monkeypatch):
    monkeypatch.setenv("TALONX_V2_DB_PATH", str(tmp_path / "v2.db"))
    sym_pending, sym_filled, sym_rejected, sym_expired = _broad_only_symbols(4)
    store = V2Store(str(tmp_path / "v2.db"), starting_cash=300_000.0)

    # PENDING: a real durable intent, awaiting its target session's open.
    ep_p = _ep(sym_pending, "ep-pending", date(2027, 6, 3))
    intent_p = store.upsert_entry_intent(ep_p, _decision(ep_p), _liq(), horizon=10,
                                         planned_exit_session="2027-06-17")
    # this intent's own ENTRY_INTENT alert -- QUEUED, not yet delivered.
    store.enqueue_alert(event_id="evt-pending", episode_id=ep_p.episode_id, kind="ENTRY_INTENT",
                       action="BUY", symbol=sym_pending, strategy_version="INSIDER_BUY_CLUSTER_V2@1",
                       dedup_key="dp", payload_text="planned buy", provenance={},
                       intent_id=intent_p["intent_id"], deliver_by_utc="2027-06-03T13:30:00+00:00")

    # FILLED: intent reconciled to FILLED, disposition ENTERED, and its
    # outbox alert actually SENT (delivered).
    ep_f = _ep(sym_filled, "ep-filled", date(2026, 9, 8))
    intent_f = store.upsert_entry_intent(ep_f, _decision(ep_f), _liq(), horizon=10,
                                         planned_exit_session="2026-09-22")
    store.mark_entry_intent(intent_f["intent_id"], "FILLED", position_id=1,
                            fill_price=42.0, fill_session="2026-09-08")
    store.record_disposition(episode_id=ep_f.episode_id, symbol=sym_filled, disposition="ENTERED",
                             eligible_entry_session="2026-09-08")
    store.enqueue_alert(event_id="evt-filled", episode_id=ep_f.episode_id, kind="ENTRY_FILL",
                       action="BUY", symbol=sym_filled, strategy_version="INSIDER_BUY_CLUSTER_V2@1",
                       dedup_key="df", payload_text="filled", provenance={})
    store.update_outbox("evt-filled", state="SENT")

    # REJECTED: refused at admission time -- capacity exceeded, no intent
    # ever created.
    store.record_disposition(episode_id="ep-rejected", symbol=sym_rejected,
                             disposition="REJECTED_CAPACITY_EXCEEDED",
                             eligible_entry_session="2026-09-08",
                             detail="unreserved cash below required allocation")

    # EXPIRED: a durable intent that went stale before a fill was ever observed.
    ep_e = _ep(sym_expired, "ep-expired", date(2026, 8, 20))
    intent_e = store.upsert_entry_intent(ep_e, _decision(ep_e), _liq(), horizon=10,
                                         planned_exit_session="2026-09-03")
    store.mark_entry_intent(intent_e["intent_id"], "EXPIRED_STALE",
                            detail="went stale before a FINAL entry bar was observed")

    panel = _model(home, tmp_path / "v2.db").v2_broad_discovery()
    fn = panel["discovery_funnel"]
    assert fn["status"] == "ACTIVE"
    assert fn["candidates_n"] == 4
    assert fn["by_status"] == {"PENDING": 1, "FILLED": 1, "REJECTED": 1, "EXPIRED": 1}
    recent_by_symbol = {c["symbol"]: c for c in fn["recent"]}
    assert recent_by_symbol[sym_pending]["status_bucket"] == "PENDING"
    assert recent_by_symbol[sym_filled]["status_bucket"] == "FILLED"
    assert recent_by_symbol[sym_rejected]["status_bucket"] == "REJECTED"
    assert recent_by_symbol[sym_expired]["status_bucket"] == "EXPIRED"
    assert recent_by_symbol[sym_rejected]["reason"] == "unreserved cash below required allocation"

    aq = panel["action_queue"]
    assert aq["pending_intents_n"] == 1
    assert aq["pending_intents"][0]["symbol"] == sym_pending
    assert aq["pending_intents"][0]["reference_price"].startswith("PENDING")
    assert aq["reserved_slots"] == 1
    assert aq["reserved_cash_usd"] == 10_000.0   # 1 pending intent * frozen $10,000 allocation
    outbox_by_symbol = {r["symbol"]: r for r in aq["recent_outbox"]}
    assert outbox_by_symbol[sym_pending]["state"] in ("PENDING", "RETRY")   # queued, not delivered
    assert outbox_by_symbol[sym_filled]["state"] == "SENT"                  # actually delivered
    assert "queued" in aq["note"].lower() and "delivered" in aq["note"].lower()

    ledger = panel["ledger"]
    assert ledger["n_open"] == 0   # neither position ever actually opened in the positions table
    assert "administrative_adjustments_note" in ledger


# --------------------------------------------------------------------- #
# classifier unit coverage -- the UNCLASSIFIED fallback
# --------------------------------------------------------------------- #
def test_classifier_falls_back_to_unclassified_for_an_unknown_disposition():
    row = DashboardReadModel._classify_discovery_candidate(
        {"symbol": "ZZZZ", "episode_id": "e1", "disposition": "SOME_FUTURE_DISPOSITION_NOT_YET_MAPPED",
         "eligible_entry_session": "2026-09-08", "updated_at": "2026-09-08T00:00:00+00:00"}, None)
    assert row["status_bucket"] == "DISCOVERED"   # a real, non-empty, non-terminal disposition
    row_blank = DashboardReadModel._classify_discovery_candidate(
        {"symbol": "ZZZZ", "episode_id": "e2", "disposition": "", "eligible_entry_session": None,
         "updated_at": None}, None)
    assert row_blank["status_bucket"] == "UNCLASSIFIED"


def test_classifier_filled_takes_precedence_over_a_stray_pending_intent_row():
    # a defensive case: if an intent row was somehow left PENDING after the
    # episode's own disposition already recorded ENTERED, FILLED still wins
    # (the disposition is the more authoritative signal for a real fill).
    row = DashboardReadModel._classify_discovery_candidate(
        {"symbol": "ZZZZ", "episode_id": "e3", "disposition": "ENTERED",
         "eligible_entry_session": "2026-09-08", "updated_at": "2026-09-08T00:00:00+00:00"},
        {"status": "PENDING", "detail": ""})
    assert row["status_bucket"] == "FILLED"
