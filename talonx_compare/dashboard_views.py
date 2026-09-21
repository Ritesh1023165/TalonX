"""Task 83 §3/§4 -- read-only view builders shared by the browser
dashboard (``dashboard_web.py``) and the Streamlit dashboard
(``talonx_dispatch/app.py``).

Three builders -- ``original_view``, ``piv_view``, ``compare_view`` --
each returning a plain dict. Every source is annotated with one of the
nine explicit health states; a MISSING / UNREADABLE / STALE / NOT_RUN /
WRONG_SESSION source is NEVER rendered as a plausible zero. Original
SIMULATED_PAPER, PIV shadow and PIV PAPER P&L are reported under separate
keys and never merged.

Pure reads: no builder here starts a session, places an order, changes a
setting, or writes to Redis.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from talonx_piv.config import PivConfig

from .archive import CompareArchive
from .config import CompareConfig
from .health import (
    QUANT_STATE_STORE_LIMITATION,
    SourceHealth,
    classify_json_file,
    classify_jsonl_stream,
    classify_redis,
    HEALTHY,
    NOT_RUN,
    RUNNING,
    UNREADABLE,
)

# stages the Original pipeline funnels work through, in order
ORIGINAL_LIFECYCLE_STAGES = ("warmup", "quant", "brain", "core", "dispatch", "telegram")
_MODULE_FOR_STAGE = {
    "warmup": "ingest", "quant": "quant", "brain": "brain",
    "core": "core", "dispatch": "dispatch", "telegram": "dispatch",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _safe_json(path: Path) -> tuple[Any, str | None]:
    if not path.exists():
        return None, "missing"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


# --------------------------------------------------------------------------
# Original view
# --------------------------------------------------------------------------

def original_view(
    *,
    redis_client: Any | None = None,
    runtime_metadata_path: Path | None = None,
    paper_positions: list[dict[str, Any]] | None = None,
    paper_pnl: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or _utcnow()
    utc_date = now.astimezone(timezone.utc).date().isoformat()

    # -- did Original run at all? (runtime_metadata.json) --
    from talonx_ops.runtime_metadata import read_runtime_metadata

    meta = read_runtime_metadata(runtime_metadata_path)
    if meta is None:
        run_health = SourceHealth(NOT_RUN, "no runtime_metadata.json -- Original has not been started")
    else:
        started = meta.get("started_at")
        run_health = SourceHealth(
            HEALTHY, f"last start {started}", last_update=started,
        )

    # -- Redis transport health --
    ping_ok: bool | None = None
    if redis_client is not None:
        try:
            redis_client.ping()
            ping_ok = True
        except Exception:  # noqa: BLE001
            ping_ok = False
    redis_health = classify_redis(ping_ok)

    # -- stage funnel from metrics:{utc_date}:{module}:{counter} --
    metrics: dict[str, dict[str, int]] = {}
    metrics_health = SourceHealth(NOT_RUN, "Redis not contacted")
    if redis_client is not None and ping_ok:
        try:
            keys = list(redis_client.scan_iter(match=f"metrics:{utc_date}:*", count=200))
            if keys:
                values = redis_client.mget(keys)
                for k, v in zip(keys, values):
                    if v is None:
                        continue
                    kk = k.decode() if isinstance(k, bytes) else k
                    _, _, module, counter = kk.split(":", 3)
                    try:
                        metrics.setdefault(module, {})[counter] = int(v)
                    except (ValueError, TypeError):
                        pass
                metrics_health = SourceHealth(HEALTHY, f"{len(keys)} counter(s) for {utc_date}")
            else:
                metrics_health = SourceHealth(
                    NOT_RUN, f"no metrics:{utc_date}:* counters -- no Original activity recorded today")
        except Exception as exc:  # noqa: BLE001
            metrics_health = SourceHealth(UNREADABLE, f"metrics scan failed: {exc}")
    elif redis_client is not None and ping_ok is False:
        metrics_health = SourceHealth("DISCONNECTED", "Redis unreachable")

    stages = []
    for stage in ORIGINAL_LIFECYCLE_STAGES:
        module = _MODULE_FOR_STAGE[stage]
        counters = metrics.get(module, {})
        if stage == "telegram":
            counters = {k: v for k, v in counters.items() if "telegram" in k}
        total = sum(counters.values()) if counters else 0
        stages.append({
            "stage": stage,
            "module": module,
            "counters": dict(sorted(counters.items())),
            "total": total,
            "health": (metrics_health.to_dict() if counters or metrics_health.state in (HEALTHY,)
                       else SourceHealth(metrics_health.state, metrics_health.detail).to_dict()),
        })

    telegram_counters = {
        k: v for k, v in metrics.get("dispatch", {}).items() if "telegram" in k
    }

    return {
        "pipeline": "ORIGINAL",
        "as_of": now.isoformat(),
        "run_health": run_health.to_dict(),
        "redis_health": redis_health.to_dict(),
        "metrics_health": metrics_health.to_dict(),
        "modules_enabled": (meta or {}).get("modules_enabled"),
        "market_data_provider": (meta or {}).get("market_data_provider_configured"),
        "paper_execution_path": (meta or {}).get("paper_execution_path"),
        "lifecycle_stages": stages,
        "telegram": {
            "owner": "ORIGINAL",
            "counters": dict(sorted(telegram_counters.items())),
            "total_pushed": sum(telegram_counters.values()) if telegram_counters else 0,
            "health": metrics_health.to_dict(),
        },
        "simulated_paper": {
            "execution_class": "SIMULATED_PAPER",
            "positions": paper_positions if paper_positions is not None else [],
            "pnl": paper_pnl if paper_pnl is not None else None,
            "health": (SourceHealth(HEALTHY, "supplied").to_dict() if paper_positions is not None
                       else SourceHealth(NOT_RUN, "paper store not read in this context").to_dict()),
            "note": "Original local simulated-paper P&L. NEVER combined with any PIV P&L stream.",
        },
    }


# --------------------------------------------------------------------------
# PIV view
# --------------------------------------------------------------------------

def piv_view(
    *,
    state_dir: Path | None = None,
    now: datetime | None = None,
    stale_seconds: int = 120,
) -> dict[str, Any]:
    now = now or _utcnow()
    piv_cfg = PivConfig()
    sd = Path(state_dir) if state_dir is not None else piv_cfg.state_dir

    from talonx_piv.execution_settings import load_paper_entry_settings

    _settings = load_paper_entry_settings(sd / "paper_entry_settings.json")
    _any_paper = any(_settings.enabled_for(t) for t in piv_cfg.universe)
    execution_mode = "PAPER" if _any_paper else "SHADOW"

    identity, id_err = _safe_json(sd / "session_identity.json")
    identity = identity if isinstance(identity, dict) else {}
    session_id = identity.get("session_id")
    trading_date = identity.get("trading_date_et")

    identity_health = (
        SourceHealth(UNREADABLE, id_err) if id_err and id_err != "missing"
        else classify_json_file(sd / "session_identity.json", required=True, now=now)
    )

    events_health = classify_jsonl_stream(
        sd / "piv_events.jsonl", now=now, stale_seconds=stale_seconds,
        scope_field="session_id", expected_scope=session_id,
    )

    # freshness / provider state
    freshness, fr_err = _safe_json(sd / "freshness_report.json")
    freshness = freshness if isinstance(freshness, dict) else {}
    freshness_health = classify_json_file(sd / "freshness_report.json", required=False, now=now)

    # readiness per symbol
    readiness, rd_err = _safe_json(sd / "session_readiness_state.json")
    readiness = readiness if isinstance(readiness, dict) else {}
    readiness_health = classify_json_file(sd / "session_readiness_state.json", required=False, now=now)
    per_symbol_readiness = {
        sym: (tel.get("status") if isinstance(tel, dict) else None)
        for sym, tel in (readiness.get("finalized") or {}).items()
    }

    # decisions funnel
    decisions, dec_err = _safe_json(sd / "decision_ledger.json")
    decisions = decisions if isinstance(decisions, dict) else {}
    decisions_health = classify_json_file(sd / "decision_ledger.json", required=False, now=now)
    rec_counts: dict[str, int] = {}
    for rec in decisions.values():
        if isinstance(rec, dict) and rec.get("session_id") in (None, session_id):
            r = rec.get("recommendation", "UNKNOWN")
            rec_counts[r] = rec_counts.get(r, 0) + 1

    # shadow ledger by status + execution class
    shadow, sh_err = _safe_json(sd / "shadow_ledger.json")
    shadow = shadow if isinstance(shadow, dict) else {}
    shadow_health = classify_json_file(sd / "shadow_ledger.json", required=False, now=now)
    shadow_status: dict[str, int] = {}
    shadow_experimental = 0
    for rec in shadow.values():
        if not isinstance(rec, dict):
            continue
        shadow_status[rec.get("status", "UNKNOWN")] = shadow_status.get(rec.get("status", "UNKNOWN"), 0) + 1
        if rec.get("experimental"):
            shadow_experimental += 1

    # lifecycle / PAPER
    lifecycle, lc_err = _safe_json(sd / "lifecycle_state.json")
    lifecycle = lifecycle if isinstance(lifecycle, dict) else {}
    lifecycle_health = classify_json_file(sd / "lifecycle_state.json", required=True, now=now)
    orders = lifecycle.get("orders", {}) if isinstance(lifecycle, dict) else {}
    positions = lifecycle.get("positions", {}) if isinstance(lifecycle, dict) else {}
    recon_flags = lifecycle.get("reconciliation_flags", {}) if isinstance(lifecycle, dict) else {}

    reconciliation, rc_err = _safe_json(sd / "latest_reconciliation.json")
    reconciliation = reconciliation if isinstance(reconciliation, dict) else {}
    reconciliation_health = classify_json_file(sd / "latest_reconciliation.json", required=False, now=now)

    eod, eod_err = _safe_json(sd / "eod_state.json")
    eod = eod if isinstance(eod, dict) else {}
    eod_health = classify_json_file(sd / "eod_state.json", required=False, now=now)

    return {
        "pipeline": "PIV",
        "as_of": now.isoformat(),
        "identity": {
            "session_id": session_id,
            "trading_date_et": trading_date,
            "runtime_sha": identity.get("runtime_sha"),
            "config_hash": identity.get("config_hash"),
            "feed_mode": identity.get("feed_mode") or piv_cfg.feed_mode,
            "health": identity_health.to_dict(),
        },
        "strategy_approval_status": "UNVALIDATED",
        "profitability": "UNDETERMINED",
        "execution_mode": execution_mode,
        "feed_mode": piv_cfg.feed_mode,
        "real_capital_prohibited": True,
        "experimental_authorization": "DISABLED",
        "provider_state": {
            "value": freshness.get("provider_state"),
            "health": freshness_health.to_dict(),
        },
        "per_symbol_readiness": {
            "value": per_symbol_readiness,
            "health": readiness_health.to_dict(),
        },
        "per_symbol_freshness": {
            "value": freshness.get("symbols") or {},
            "coverage": freshness.get("coverage") or {},
            "health": freshness_health.to_dict(),
        },
        "stale_recovery_episodes": {
            "stale_events": events_health.to_dict(),
            "note": "STALE_DATA / DATA_RECOVERED counts are in piv_events.jsonl (stage=freshness).",
        },
        "events": events_health.to_dict(),
        "quant_funnel": {
            "by_recommendation": dict(sorted(rec_counts.items())),
            "health": decisions_health.to_dict(),
        },
        "decisions": {
            "total": sum(rec_counts.values()),
            "by_recommendation": dict(sorted(rec_counts.items())),
            "health": decisions_health.to_dict(),
        },
        "shadow": {
            "execution_class": "PIV_SHADOW",
            "by_status": dict(sorted(shadow_status.items())),
            "experimental_count": shadow_experimental,
            "health": shadow_health.to_dict(),
            "note": "PIV shadow P&L. NEVER combined with Original simulated P&L or PIV PAPER P&L.",
        },
        "paper_lifecycle": {
            "execution_class": "PIV_PAPER",
            "orders": len(orders),
            "positions": len(positions),
            "entry_admission_blocked": bool(recon_flags.get("entry_admission_blocked")),
            "health": lifecycle_health.to_dict(),
            "note": "PIV PAPER (Alpaca paper) P&L. NEVER combined with any other stream.",
        },
        "reconciliation": {
            "complete": reconciliation.get("complete"),
            "consistent": reconciliation.get("consistent"),
            "entry_admission_blocked": bool(recon_flags.get("entry_admission_blocked")),
            "health": reconciliation_health.to_dict(),
        },
        "eod": {
            "status": eod.get("status"),
            "trading_date_et": eod.get("trading_date_et"),
            "health": eod_health.to_dict(),
        },
        "capability_limitations": [QUANT_STATE_STORE_LIMITATION],
        "unresolved_questions": [{
            "id": "iex_receipt_vs_source_time",
            "state": "UNRESOLVED",
            "detail": (
                "Whether PIV bar timestamps reflect IEX source time or local receipt time is "
                "not established. Schema carries both event_time and source_bar_time so both can "
                "be shown once a raw per-bar source-time log is available. No live or historical "
                "data acquisition is authorized to resolve it."
            ),
        }],
    }


# --------------------------------------------------------------------------
# Compare view
# --------------------------------------------------------------------------

def compare_view(
    *,
    config: CompareConfig | None = None,
    trading_date: str | None = None,
) -> dict[str, Any]:
    archive = CompareArchive(config or CompareConfig())
    day = archive.day(trading_date) if trading_date else archive.latest()
    trustworthy = day.get("trustworthy", False)
    # Task 83-R1 §6.8: derived totals from a corrupt archive are NOT
    # presented as trustworthy -- they move to a clearly-labelled
    # untrusted block and per_stage_totals reads empty.
    comparison = (day.get("comparison") if trustworthy else None) or {}
    per_stage = comparison.get("per_stage_totals", {})
    per_symbol_stage = comparison.get("per_symbol_stage", [])
    divergences = day.get("divergences", [])
    div_by_class: dict[str, int] = {}
    for d in divergences:
        k = d.get("divergence_class", "UNKNOWN")
        div_by_class[k] = div_by_class.get(k, 0) + 1
    missing_late = [
        d for d in divergences
        if d.get("divergence_class") in ("LATE_OR_MISSING_STAGE", "SOURCE_UNAVAILABLE")
    ]
    return {
        "pipeline": "COMPARE",
        "trading_date": day.get("trading_date"),
        "available_dates": day.get("available_dates", archive.available_dates()),
        "health": day.get("health"),
        "trustworthy": trustworthy,
        "archive_integrity": day.get("archive_integrity"),
        "runtime_status": day.get("runtime_status"),
        "original_run_scope": comparison.get("original_run_scope"),
        "event_level_agreement_assertable": comparison.get("event_level_agreement_assertable"),
        "per_stage_totals": per_stage,
        "per_symbol_stage": per_symbol_stage,
        "untrusted_comparison": day.get("comparison_untrusted") if not trustworthy else None,
        "divergence_by_class": div_by_class,
        "divergences": divergences,
        "missing_or_late_stages": missing_late,
        "diagnostics": day.get("diagnostics", []),
        "telegram": day.get("telegram"),
        "manifest": day.get("manifest"),
        "outcome_streams": {
            "original_simulated": "SIMULATED_PAPER",
            "piv_shadow": "PIV_SHADOW",
            "piv_paper": "PIV_PAPER",
            "experimental": "EXPERIMENTAL",
            "note": "shown separately; never summed into a single P&L or agreement number",
        },
        "operational_agreement_only": True,
        "not_alpha_evidence": (
            "Operational agreement is not profitability or alpha evidence. "
            "Strategy: UNVALIDATED. Profitability: UNDETERMINED."
        ),
    }


# --------------------------------------------------------------------------
# Streamlit "PIV & Comparison" section payload
# --------------------------------------------------------------------------

def streamlit_piv_comparison_payload(
    *,
    config: CompareConfig | None = None,
    piv_state_dir: Path | None = None,
    trading_date: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Everything the read-only Streamlit "PIV & Comparison" section needs
    for one trading date. Pure reads over the collector's archive plus the
    live PIV state dir. No activation / broker / experimental / override /
    strategy-approval control is represented here -- this payload is data
    only."""
    cfg = config or CompareConfig()
    archive = CompareArchive(cfg)
    dates = archive.available_dates()
    selected = trading_date or (dates[-1] if dates else None)

    live_piv = piv_view(state_dir=piv_state_dir, now=now)
    day = archive.day(selected) if selected else {"trading_date": None,
                                                  "health": SourceHealth(NOT_RUN, "no archive").to_dict(),
                                                  "trustworthy": False}
    trustworthy = day.get("trustworthy", False)
    comparison = (day.get("comparison") if trustworthy else None) or {}
    per_stage = comparison.get("per_stage_totals", {})

    # archived Original vs PIV funnels, side by side
    archived_funnels = {"original": {}, "piv": {}}
    for row in comparison.get("per_symbol_stage", []):
        if row.get("original_present"):
            archived_funnels["original"][row["stage"]] = archived_funnels["original"].get(row["stage"], 0) + 1
        if row.get("piv_present"):
            archived_funnels["piv"][row["stage"]] = archived_funnels["piv"].get(row["stage"], 0) + 1

    divergences = day.get("divergences", [])
    divergence_table = [
        {"stage": d.get("stage"), "symbol": d.get("symbol"),
         "class": d.get("divergence_class"), "detail": d.get("detail")}
        for d in divergences
    ]

    return {
        "available_dates": dates,
        "selected_date": selected,
        "archive_health": day.get("health"),
        "archive_trustworthy": trustworthy,
        "archive_integrity": day.get("archive_integrity"),
        "runtime_status": day.get("runtime_status"),
        "manifest": day.get("manifest"),
        "live_piv_identity": live_piv["identity"],
        "strategy_approval_status": "UNVALIDATED",
        "profitability": "UNDETERMINED",
        "feed_mode": live_piv["feed_mode"],
        "execution_mode": live_piv["execution_mode"],
        "archived_funnels": archived_funnels,
        "live_quant_funnel": live_piv["quant_funnel"],
        "readiness_freshness_exclusions": {
            "per_symbol_readiness": live_piv["per_symbol_readiness"],
            "per_symbol_freshness": live_piv["per_symbol_freshness"],
            "provider_state": live_piv["provider_state"],
        },
        "decisions_and_reason_codes": live_piv["decisions"],
        "notification_and_lifecycle": {
            "paper_lifecycle": live_piv["paper_lifecycle"],
            "reconciliation": live_piv["reconciliation"],
        },
        "outcomes_by_execution_class": {
            "SIMULATED_PAPER": {"owner": "ORIGINAL", "source": "Original local paper engine"},
            "PIV_SHADOW": live_piv["shadow"],
            "PIV_PAPER": live_piv["paper_lifecycle"],
            "EXPERIMENTAL": {"count": live_piv["shadow"].get("experimental_count", 0),
                             "authorization": "DISABLED"},
            "note": "kept separate; never summed into one P&L or outcome number",
        },
        "eod_reconciliation": {
            "live": live_piv["eod"],
            "archived_reconciliation": {
                "complete": comparison.get("source_health", {}).get("piv_reconciliation"),
            },
        },
        "per_stage_totals": per_stage,
        "divergence_table": divergence_table,
        "divergence_by_class": {
            k: sum(1 for d in divergences if d.get("divergence_class") == k)
            for k in {d.get("divergence_class") for d in divergences}
        },
        "source_health": comparison.get("source_health", {}),
        "diagnostics": day.get("diagnostics", []),
        "capability_limitations": live_piv["capability_limitations"],
        "unresolved_questions": live_piv["unresolved_questions"],
        "read_only": True,
        "controls": [],  # explicitly: this section exposes NO controls
        "not_alpha_evidence": (
            "Operational agreement is not alpha/profitability evidence. "
            "Strategy UNVALIDATED, profitability UNDETERMINED, PAPER pilot unauthorized."
        ),
    }
