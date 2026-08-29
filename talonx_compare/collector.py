"""Task 83 §2 -- the passive Original/PIV comparison collector.

``ComparisonCollector.collect_once`` reads (never writes) the PIV state
directory and, when a Redis client is supplied, the Original ``metrics:*``
counters on DB 0, projects both onto :class:`ComparisonRecord`s, aligns
them for one trading date, classifies divergence, and appends the result
to the date-partitioned evidence store. It is fully idempotent: running it
again over the same inputs adds no duplicate records.

Injectable dependencies (``clock``, ``original_redis``, ``piv_redis``,
``captured_original_messages``, ``captured_piv_messages``) let the offline
rehearsal drive it with deterministic fakes and zero network.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable

from .config import CompareConfig
from .divergence import AGREEMENT_IS_NOT_ALPHA
from .alignment import compare
from .evidence import EvidenceWriter
from .health import (
    classify_json_file,
    classify_jsonl_stream,
    classify_redis,
    QUANT_STATE_STORE_LIMITATION,
)
from .identity import PIPELINE_ORIGINAL, PIPELINE_PIV, ComparisonRecord
from . import projections as P


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _load_json(path: Path) -> tuple[Any, str | None]:
    if not path.exists():
        return None, None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"{type(exc).__name__}: {exc}"
    if not text.strip():
        return None, None
    try:
        return json.loads(text), None
    except json.JSONDecodeError as exc:
        return None, f"JSON error: {exc}"


@dataclass
class CollectResult:
    trading_date: str | None
    manifest_written: bool
    manifest_conflict: bool
    original_appended: int
    piv_appended: int
    duplicates_skipped: int
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    divergences: list[dict[str, Any]] = field(default_factory=list)
    evidence_dir: str | None = None
    source_health: dict[str, Any] = field(default_factory=dict)
    skipped_reason: str | None = None


class ComparisonCollector:
    def __init__(
        self,
        config: CompareConfig | None = None,
        *,
        clock: Callable[[], datetime] = _utcnow,
        original_redis: Any | None = None,
        piv_redis: Any | None = None,
    ) -> None:
        self.config = config or CompareConfig()
        self.clock = clock
        self.original_redis = original_redis
        self.piv_redis = piv_redis
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        self.config.dedup_dir.mkdir(parents=True, exist_ok=True)

    # --- cursors ---------------------------------------------------------

    def _load_cursors(self) -> dict[str, Any]:
        data, _ = _load_json(self.config.cursor_path)
        return data if isinstance(data, dict) else {}

    def _save_cursors(self, cursors: dict[str, Any]) -> None:
        self.config.cursor_path.write_text(
            json.dumps(cursors, sort_keys=True, indent=2), encoding="utf-8")

    # --- Original metrics (Redis DB 0, read-only) -----------------------

    def _read_original_metrics(self, date_candidates: list[str]) -> tuple[dict[str, dict[str, int]], bool | None, list[dict]]:
        """Returns (metrics, redis_ping_ok, diagnostics). ping_ok is None
        when no Redis client was supplied (pure offline).

        Original ``metrics:*`` keys are bucketed by *UTC* date, which only
        usually coincides with the ET trading date -- so every candidate
        date is scanned and the results merged (a counter present under
        more than one date is summed)."""
        if self.original_redis is None:
            return {}, None, []
        diags: list[dict] = []
        try:
            self.original_redis.ping()
            ping_ok = True
        except Exception as exc:  # noqa: BLE001 -- a connection failure is a health signal
            return {}, False, [{"kind": "SOURCE_UNAVAILABLE", "source": "redis:original",
                                "detail": f"ping failed: {exc}"}]
        metrics: dict[str, dict[str, int]] = {}
        for trading_date in dict.fromkeys(date_candidates):
            try:
                keys = list(self.original_redis.scan_iter(match=f"metrics:{trading_date}:*", count=200))
                if not keys:
                    continue
                values = self.original_redis.mget(keys)
                for key, value in zip(keys, values):
                    if value is None:
                        continue
                    k = key.decode() if isinstance(key, bytes) else key
                    parts = k.split(":", 3)
                    if len(parts) != 4:
                        continue
                    _, _, module, counter = parts
                    try:
                        prev = metrics.setdefault(module, {}).get(counter, 0)
                        metrics[module][counter] = prev + int(value)
                    except (ValueError, TypeError):
                        diags.append({"kind": "MALFORMED", "source": f"redis:{k}",
                                      "detail": f"non-integer value {value!r}"})
            except Exception as exc:  # noqa: BLE001
                diags.append({"kind": "SOURCE_UNAVAILABLE", "source": "redis:original",
                              "detail": f"scan/mget failed: {exc}"})
        return metrics, ping_ok, diags

    # --- the main pass -------------------------------------------------

    def collect_once(
        self,
        *,
        now: datetime | None = None,
        trading_date: str | None = None,
        captured_original_messages: list[dict[str, Any]] | None = None,
        captured_piv_messages: list[dict[str, Any]] | None = None,
    ) -> CollectResult:
        now = now or self.clock()
        now_iso = now.isoformat()
        sd = self.config.piv_state_dir
        diagnostics: list[dict[str, Any]] = []

        # --- 1. PIV identity / scope ---
        identity, id_err = _load_json(sd / "session_identity.json")
        if id_err:
            diagnostics.append({"kind": "UNREADABLE", "source": "session_identity.json", "detail": id_err})
        identity = identity if isinstance(identity, dict) else {}
        session_id = identity.get("session_id")
        piv_trading_date = trading_date or identity.get("trading_date_et")

        # --- 2. project PIV file sources ---
        piv_records: list[ComparisonRecord] = []

        events_text = ""
        ep = sd / "piv_events.jsonl"
        if ep.exists():
            try:
                events_text = ep.read_text(encoding="utf-8")
            except OSError as exc:
                diagnostics.append({"kind": "UNREADABLE", "source": "piv_events.jsonl", "detail": str(exc)})
        if piv_trading_date is None and events_text.strip():
            # derive the date from the newest event if identity is absent
            for ln in reversed(events_text.splitlines()):
                if not ln.strip():
                    continue
                try:
                    piv_trading_date = json.loads(ln).get("trading_date_et")
                except json.JSONDecodeError:
                    continue
                if piv_trading_date:
                    break

        recs, d = P.project_piv_events(
            events_text, expected_session_id=session_id, expected_trading_date=piv_trading_date)
        piv_records += recs
        diagnostics += d

        readiness, rd_err = _load_json(sd / "session_readiness_state.json")
        if rd_err:
            diagnostics.append({"kind": "UNREADABLE", "source": "session_readiness_state.json", "detail": rd_err})
        elif readiness is not None:
            recs, d = P.project_piv_readiness(
                readiness, session_id=session_id, expected_trading_date=piv_trading_date)
            piv_records += recs
            diagnostics += d

        decisions, dec_err = _load_json(sd / "decision_ledger.json")
        decision_dates: dict[str, str] = {}
        if dec_err:
            diagnostics.append({"kind": "UNREADABLE", "source": "decision_ledger.json", "detail": dec_err})
        elif decisions is not None:
            recs, d = P.project_piv_decisions(
                decisions, session_id=session_id, expected_trading_date=piv_trading_date)
            piv_records += recs
            diagnostics += d
            if isinstance(decisions, dict):
                for did, rec in decisions.items():
                    if isinstance(rec, dict):
                        decision_dates[did] = rec.get("trading_date_et") or piv_trading_date

        shadow, sh_err = _load_json(sd / "shadow_ledger.json")
        if sh_err:
            diagnostics.append({"kind": "UNREADABLE", "source": "shadow_ledger.json", "detail": sh_err})
        elif shadow is not None:
            recs, d = P.project_piv_shadow(
                shadow, session_id=session_id, decision_dates=decision_dates,
                expected_trading_date=piv_trading_date)
            piv_records += recs
            diagnostics += d

        lifecycle, lc_err = _load_json(sd / "lifecycle_state.json")
        if lc_err:
            diagnostics.append({"kind": "UNREADABLE", "source": "lifecycle_state.json", "detail": lc_err})
        elif lifecycle is not None:
            recs, d = P.project_piv_lifecycle(
                lifecycle, session_id=session_id, expected_trading_date=piv_trading_date)
            piv_records += recs
            diagnostics += d

        freshness, fr_err = _load_json(sd / "freshness_report.json")
        if fr_err:
            diagnostics.append({"kind": "UNREADABLE", "source": "freshness_report.json", "detail": fr_err})
        elif freshness is not None:
            recs, d = P.project_piv_freshness(
                freshness, session_id=session_id, expected_trading_date=piv_trading_date)
            piv_records += recs
            diagnostics += d

        recon, rc_err = _load_json(sd / "latest_reconciliation.json")
        if rc_err:
            diagnostics.append({"kind": "UNREADABLE", "source": "latest_reconciliation.json", "detail": rc_err})
        elif recon is not None:
            recs, d = P.project_piv_reconciliation(
                recon, session_id=session_id, expected_trading_date=piv_trading_date)
            piv_records += recs
            diagnostics += d

        eod, eod_err = _load_json(sd / "eod_state.json")
        if eod_err:
            diagnostics.append({"kind": "UNREADABLE", "source": "eod_state.json", "detail": eod_err})
        elif eod is not None:
            recs, d = P.project_piv_eod(
                eod, session_id=session_id, expected_trading_date=piv_trading_date)
            piv_records += recs
            diagnostics += d

        # --- 3. project Original sources ---
        the_date = trading_date or piv_trading_date
        original_records: list[ComparisonRecord] = []
        redis_ping_ok = None
        metrics: dict[str, dict[str, int]] = {}
        if the_date is not None:
            date_candidates = [the_date, now.astimezone(timezone.utc).date().isoformat()]
            metrics, redis_ping_ok, mdiags = self._read_original_metrics(date_candidates)
            diagnostics += mdiags
            recs, d = P.project_original_metrics(
                metrics, trading_date=the_date, session_id=None, as_of=now_iso)
            original_records += recs
            diagnostics += d
        if captured_original_messages:
            recs, d = P.project_original_messages(
                captured_original_messages, trading_date=the_date, session_id=None)
            original_records += recs
            diagnostics += d
        if captured_piv_messages:
            # PIV pub/sub is a supplementary live signal; project it exactly
            # like the file path (never republished).
            recs, d = P.project_original_messages(
                captured_piv_messages, trading_date=the_date, session_id=session_id)
            for r in recs:
                piv_records.append(ComparisonRecord(
                    pipeline=PIPELINE_PIV, session_id=session_id, trading_date=r.trading_date,
                    stage=r.stage, symbol=r.symbol, event_time=r.event_time,
                    source_bar_time=r.source_bar_time, decision_id=r.decision_id,
                    decision_outcome=r.decision_outcome, reason_codes=r.reason_codes,
                    execution_class=r.execution_class, payload_fingerprint=r.payload_fingerprint,
                    source="redis:piv:" + (r.source or ""),
                ))
            diagnostics += d

        if the_date is None:
            return CollectResult(
                None, False, False, 0, 0, 0, diagnostics, [], None, {},
                skipped_reason="no trading date could be resolved from PIV identity, events, or caller",
            )

        # --- 4. source-health snapshot ---
        cfg = self.config
        source_health = {
            "piv_session_identity": classify_json_file(
                sd / "session_identity.json", required=True, now=now).to_dict(),
            "piv_events": classify_jsonl_stream(
                sd / "piv_events.jsonl", now=now, stale_seconds=cfg.stale_seconds,
                scope_field="session_id", expected_scope=session_id).to_dict(),
            "piv_decision_ledger": classify_json_file(
                sd / "decision_ledger.json", required=False, now=now).to_dict(),
            "piv_shadow_ledger": classify_json_file(
                sd / "shadow_ledger.json", required=False, now=now).to_dict(),
            "piv_lifecycle_state": classify_json_file(
                sd / "lifecycle_state.json", required=True, now=now).to_dict(),
            "piv_freshness_report": classify_json_file(
                sd / "freshness_report.json", required=False, now=now).to_dict(),
            "piv_reconciliation": classify_json_file(
                sd / "latest_reconciliation.json", required=False, now=now).to_dict(),
            "original_redis": classify_redis(redis_ping_ok).to_dict(),
        }
        capability_limitations = {"durable_quant_state_store": QUANT_STATE_STORE_LIMITATION}
        original_health_ok = source_health["original_redis"]["state"] in ("RUNNING", "NOT_RUN")
        piv_health_ok = all(
            source_health[k]["state"] in ("HEALTHY", "RUNNING", "NOT_RUN")
            for k in ("piv_session_identity", "piv_events", "piv_lifecycle_state")
        )

        # --- 5. evidence: manifest (immutable) ---
        writer = EvidenceWriter(cfg.evidence_root, the_date)
        manifest = self._build_manifest(
            the_date, identity, lifecycle if isinstance(lifecycle, dict) else {},
            now_iso, redis_ping_ok,
        )
        mres = writer.write_manifest(manifest)
        if mres.conflict:
            diagnostics.append({
                "kind": "WRONG_SESSION", "source": "manifest.json",
                "detail": mres.detail + " (day-level session/binding conflict)",
            })

        # --- 6. append (dedup) ---
        o_app, o_dup = writer.append_original_events(original_records)
        p_app, p_dup = writer.append_piv_records(piv_records)

        # duplicate detection is explicit, not silent
        if o_dup or p_dup:
            diagnostics.append({
                "kind": "DUPLICATE", "source": "evidence",
                "detail": f"{o_dup} Original + {p_dup} PIV re-delivered record(s) recognised and skipped",
            })

        # --- 7. align + classify over the full evidence set ---
        all_original = writer.read_original_events()
        all_piv = writer.read_piv_records()
        pairs, divs = compare(
            all_original, all_piv, restrict_trading_date=the_date,
            original_source_health_ok=original_health_ok,
            piv_source_health_ok=piv_health_ok,
        )
        self._detect_missing_stages(pairs, diagnostics)

        # --- 8. write derived views ---
        writer.write_comparison(
            self._comparison_payload(the_date, pairs, source_health, capability_limitations))
        writer.write_divergences([d.to_dict() for d in divs])
        writer.write_telegram(self._telegram_payload(the_date, metrics, events_text, identity))
        merged_diags = self._merge_diagnostics(writer.read_diagnostics(), diagnostics)
        writer.write_diagnostics(merged_diags)
        writer.write_file_hashes()

        # --- 9. cursors ---
        cursors = self._load_cursors()
        cursors.setdefault("files", {})
        for p in cfg.observed_paths():
            if p.exists():
                stat = p.stat()
                cursors["files"][str(p)] = {"mtime": stat.st_mtime, "size": stat.st_size}
        cursors["last_run_utc"] = now_iso
        cursors.setdefault("dates_seen", [])
        if the_date not in cursors["dates_seen"]:
            cursors["dates_seen"].append(the_date)
        self._save_cursors(cursors)

        return CollectResult(
            trading_date=the_date,
            manifest_written=mres.written,
            manifest_conflict=mres.conflict,
            original_appended=o_app,
            piv_appended=p_app,
            duplicates_skipped=o_dup + p_dup,
            diagnostics=merged_diags,
            divergences=[d.to_dict() for d in divs],
            evidence_dir=str(writer.dir),
            source_health=source_health,
        )

    # --- helpers -------------------------------------------------------

    def _build_manifest(
        self, the_date: str, identity: dict, lifecycle: dict, now_iso: str, redis_ping_ok: bool | None,
    ) -> dict[str, Any]:
        from talonx_piv.config import PivConfig
        from talonx_piv.execution_settings import load_paper_entry_settings

        piv_cfg = PivConfig()
        # Honest execution mode: SHADOW unless an operator has explicitly
        # enabled a PAPER entry for at least one ticker (paper_entry_settings
        # is fail-closed / all-disabled by default -- Task 83 boundary keeps
        # PAPER entries disabled).
        settings = load_paper_entry_settings(self.config.piv_state_dir / "paper_entry_settings.json")
        any_paper_enabled = any(settings.enabled_for(t) for t in piv_cfg.universe)
        execution_mode = "PAPER" if any_paper_enabled else "SHADOW"
        return {
            "trading_date": the_date,
            "generated_at": now_iso,
            "original": {
                "session_id": None,  # Original does not stamp a session id on its wire records
                "redis_url_scheme": self.config.original_redis_url.split("://", 1)[0],
                "redis_db": self.config.original_redis_url.rsplit("/", 1)[-1],
                "channels": sorted(self.config.original_channels().values()),
                "stage_modules": list(self.config.original_stage_modules()),
                "reachable_at_manifest_time": redis_ping_ok,
                "execution_class": "SIMULATED_PAPER",
            },
            "piv": {
                "session_id": identity.get("session_id"),
                "trading_date_et": identity.get("trading_date_et"),
                "runtime_sha": identity.get("runtime_sha"),
                "config_hash": identity.get("config_hash"),
                "feed_mode": identity.get("feed_mode"),
                "redis_url_scheme": self.config.piv_redis_url.split("://", 1)[0],
                "redis_db": self.config.piv_redis_url.rsplit("/", 1)[-1],
                "channels": sorted(self.config.piv_channels().values()),
                "universe": list(piv_cfg.universe),
                "paper_trading_env": piv_cfg.paper_trading,
                "real_capital": piv_cfg.real_capital,
                "execution_mode": execution_mode,
                "paper_entries_enabled": any_paper_enabled,
                "strategy_approval_status": "UNVALIDATED",
                "real_capital_prohibited": True,
                "session_enabled": bool(lifecycle.get("session_enabled")),
                "kill_switch": bool(lifecycle.get("kill_switch")),
            },
            "collector": {
                "namespace": self.config.namespace,
                "state_dir": str(self.config.state_dir),
                "evidence_root": str(self.config.evidence_root),
                "role": "PASSIVE_OBSERVER",
                "publishes": False,
                "acknowledges": False,
                "mutates_observed_pipelines": False,
            },
            "operational_agreement_only": True,
            "not_alpha_evidence": AGREEMENT_IS_NOT_ALPHA,
        }

    def _comparison_payload(self, the_date, pairs, source_health, capability_limitations=None) -> dict[str, Any]:
        by_stage: dict[str, dict[str, int]] = {}
        by_symbol_stage: list[dict[str, Any]] = []
        for pair in pairs:
            s = by_stage.setdefault(pair.stage, {"original": 0, "piv": 0, "agree": 0, "diverge": 0})
            has_o = pair.original is not None
            has_p = pair.piv is not None
            s["original"] += int(has_o)
            s["piv"] += int(has_p)
            agree = (
                has_o and has_p
                and pair.original.payload_fingerprint == pair.piv.payload_fingerprint
                and pair.original.execution_class == pair.piv.execution_class
            )
            s["agree"] += int(agree)
            s["diverge"] += int(not agree)
            by_symbol_stage.append({
                "trading_date": pair.trading_date, "stage": pair.stage, "symbol": pair.symbol,
                "original_present": has_o, "piv_present": has_p,
                "original_outcome": pair.original.decision_outcome if has_o else None,
                "piv_outcome": pair.piv.decision_outcome if has_p else None,
                "original_execution_class": pair.original.execution_class if has_o else None,
                "piv_execution_class": pair.piv.execution_class if has_p else None,
                "agree": agree,
            })
        return {
            "trading_date": the_date,
            "per_stage_totals": by_stage,
            "per_symbol_stage": by_symbol_stage,
            "source_health": source_health,
            "capability_limitations": capability_limitations or {},
            "operational_agreement_only": True,
            "pnl_streams_note": (
                "Original SIMULATED_PAPER, PIV_SHADOW, PIV_PAPER and EXPERIMENTAL outcomes are "
                "reported under separate execution_class values and are never summed."
            ),
            "not_alpha_evidence": AGREEMENT_IS_NOT_ALPHA,
        }

    def _telegram_payload(self, the_date, metrics: dict, events_text: str, identity: dict) -> dict[str, Any]:
        # Original Telegram totals: every metrics:{date}:dispatch:*telegram* counter.
        dispatch = metrics.get("dispatch", {})
        telegram_totals = {k: int(v) for k, v in sorted(dispatch.items()) if "telegram" in k}

        # Mandatory PIV zero-attempt assertion: scan the PIV events file for
        # ANY outbound Telegram marker. PIV must never attempt one.
        piv_attempts = 0
        for ln in events_text.splitlines():
            if not ln.strip():
                continue
            try:
                row = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if (row.get("telegram_attempt") or row.get("telegram_sent")
                    or row.get("event") in ("TELEGRAM_SENT", "TELEGRAM_ATTEMPT")):
                piv_attempts += 1
        return {
            "trading_date": the_date,
            "original_telegram_totals": telegram_totals,
            "original_telegram_counters": sorted(telegram_totals.keys()),
            "original_telegram_owner": "ORIGINAL",
            "piv_outbound_telegram_attempts": piv_attempts,
            "piv_zero_attempt_assertion": piv_attempts == 0,
            "piv_session_id": identity.get("session_id"),
        }

    @staticmethod
    def _detect_missing_stages(pairs, diagnostics: list[dict[str, Any]]) -> None:
        for pair in pairs:
            if (pair.original is None) ^ (pair.piv is None):
                missing = "PIV" if pair.original is not None else "ORIGINAL"
                diagnostics.append({
                    "kind": "MISSING", "source": f"{pair.stage}/{pair.symbol or '*'}",
                    "detail": f"{missing} has no record for ({pair.trading_date}, {pair.stage}, "
                              f"{pair.symbol or '*'})",
                })

    @staticmethod
    def _merge_diagnostics(existing: list[dict], new: list[dict]) -> list[dict]:
        seen = {json.dumps(d, sort_keys=True) for d in existing}
        out = list(existing)
        for d in new:
            key = json.dumps(d, sort_keys=True)
            if key not in seen:
                seen.add(key)
                out.append(d)
        return out
