"""Forward alpha validation: the pre-registered SQF_V1 filter is frozen, its decisions are explicit (UNKNOWN_DATA,
never dropped), the verdict gates follow the registration, and the cumulative doc is append-only."""
from __future__ import annotations

from talonx_paperperf import forward as FW
from talonx_paperperf import hypotheses as H


def test_sqf_v1_is_frozen():
    assert H.SQF_V1.fingerprint() == "460ee466c5ae8d6f"            # any edit to the registered filter fails here
    assert (H.SQF_V1.max_spread_bps, H.SQF_V1.min_adv20_usd, H.SQF_V1.horizon, H.SQF_V1.validation_start) == \
        (25.0, 20_000_000.0, "30", "2026-09-30")
    assert H.control_fingerprint("4926c12e5eace04e", "f0c3b237b589", "2ef115ee19f99574",
                                 "62ba413daf85e674") == "2a9c14d678b54a4d"


def test_8k_only_definition():
    assert H.is_8k_only("8-K earnings (item 2.02) filed 2026-09-28")
    assert H.is_8k_only("8-K items 7.01,9.01 filed 2026-09-28; 8-K items 3.01 filed 2026-09-25")
    assert not H.is_8k_only("8-K items 5.02 filed 2026-09-28; 1 other SEC filing(s): S-8")
    assert not H.is_8k_only("6-K filed 2026-09-28") and not H.is_8k_only("none found") and not H.is_8k_only(None)


def test_filter_decisions_record_every_reason_and_unknown_data():
    ok = {"act_entry_price": 10.0, "spread_bps": 12.0, "adv20_usd": 5e7, "catalyst": "none found"}
    assert H.SQF_V1.decide(ok) == (True, [])
    bad = {"act_entry_price": None, "spread_bps": 40.0, "adv20_usd": 1e6, "catalyst": "8-K items 8.01 filed x"}
    assert H.SQF_V1.decide(bad) == (False, ["NO_ACTIONABLE_ENTRY", "SPREAD_GT_25BPS", "ADV20_LT_20M",
                                            "CATALYST_8K_ONLY"])
    unk = {"act_entry_price": 10.0, "spread_bps": None, "adv20_usd": None, "catalyst": None}
    assert H.SQF_V1.decide(unk)[1] == ["SPREAD_UNKNOWN_DATA", "ADV20_UNKNOWN_DATA"]


def _side(n, mean, se, pf=1.2, wo3=0.1):
    return {"gross_30m": {"n": n, "mean_pct": mean}, "net_30m": {"n": n, "mean_pct": mean - 0.2, "profit_factor": pf},
            "gross_mean_se_pct": se, "concentration_30m": {"mean_without_best_3_pct": wo3}}


def test_verdict_gates_follow_the_registration():
    assert FW.verdict(_side(80, -0.5, 0.1), 3).startswith("EARLY_FAILURE_CANDIDATE")
    assert FW.verdict(_side(80, 0.5, 0.1), 3).startswith("IN_PROGRESS")          # never early success
    assert FW.verdict(_side(200, 0.5, 0.1), 10) == "PRELIMINARY_FORWARD_EDGE"
    assert FW.verdict(_side(200, 0.1, 0.1), 10).startswith("FAILED")              # net = -0.1 <= 0
    assert FW.verdict(_side(200, 0.5, 0.1, wo3=-0.05), 10).startswith("FAILED")   # concentrated


def test_cumulative_doc_is_append_only(tmp_path, monkeypatch):
    doc = tmp_path / "fav.md"
    doc.write_text("# header\n", encoding="utf-8")
    monkeypatch.setattr(FW, "DOC", doc)
    monkeypatch.setattr(FW, "report", lambda wids, live=False: {
        "windows": wids, "control": FW.side([], "C"), "shadow": FW.side([], "S"), "shadow_fail_reasons": {},
        "entry_drift_median_pct": None, "data_to_send_median_s": None, "control_verdict": "x", "shadow_verdict": "y"})
    monkeypatch.setattr(FW, "windows_done", lambda: ["2026-09-30"])
    assert FW.append_session("2026-09-30") is True
    first = doc.read_text(encoding="utf-8")
    assert FW.append_session("2026-09-30") is False and doc.read_text(encoding="utf-8") == first
    assert first.startswith("# header\n")
