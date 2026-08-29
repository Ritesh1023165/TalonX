"""Task 83 §2 / Task 83-R1 -- the passive Original/PIV comparison collector.

``ComparisonCollector.collect_once`` reads (never writes) the PIV state
directory and, when a Redis client is supplied, the Original ``metrics:*``
counters on DB 0, projects both onto :class:`ComparisonRecord`s, aligns
them per PIV session and event identity for one trading date, classifies
divergence, and folds the result into the date-partitioned evidence store.

Task 83-R1 changes:
  * the immutable ``manifest.json`` carries ONLY stable identity/binding
    fields; everything mutable (timestamps, transport health, PIV
    lifecycle status, collection stats) goes into ``runtime_status.json``
    (atomically rewritten every pass);
  * a ``transport_health`` snapshot from the running ``CollectorService``
    is honoured -- a failed subscription is ``DISCONNECTED``, not
    ``NOT_RUN``, and one pipeline's failure never suppresses the other;
  * the whole write phase is guarded by the collector-owned lock and
    refuses to touch a pre-existing archive that fails integrity
    verification (never regenerates hashes over corruption);
  * PIV Telegram zero-attempt evidence comes from the durable
    ``piv_notification_telemetry.json`` contract, never event-payload
    scanning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from .alignment import compare
from .config import CompareConfig
from .divergence import AGREEMENT_IS_NOT_ALPHA
from .evidence import EvidenceWriter
from .health import (
    QUANT_STATE_STORE_LIMITATION,
    classify_json_file,
    classify_jsonl_stream,
    classify_redis,
)
from .identity import (
    KIND_AGGREGATE,
    ORIGINAL_SCOPE_PREFIX,
    PIPELINE_PIV,
    UNSCOPED,
    ComparisonRecord,
)
from .lock import CollectorLock
from .notification import assess_piv_notification
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
    manifest_changed_fields: tuple[str, ...] = ()
    archive_integrity: dict[str, Any] = field(default_factory=dict)
    write_aborted: bool = False
    runtime_status: dict[str, Any] = field(default_factory=dict)


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
        self._pass_count = 0
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        self.config.dedup_dir.mkdir(parents=True, exist_ok=True)

    # --- cursors ------------------------------------------------------

    def _load_cursors(self) -> dict[str, Any]:
        data, _ = _load_json(self.config.cursor_path)
        return data if isinstance(data, dict) else {}

    def _save_cursors(self, cursors: dict[str, Any]) -> None:
        from .evidence import _atomic_write

        _atomic_write(self.config.cursor_path, json.dumps(cursors, sort_keys=True, indent=2) + "\n")

    # --- Original run scope (collector-derived, from verified metadata) ---

    def _derive_original_run_scope(self) -> tuple[str, dict[str, Any] | None]:
        """A COLLECTOR-DERIVED scope for the Original pipeline, built only
        from verified runtime metadata / bindings. Never an Original
        session id (Original does not emit one). Returns
        (scope, metadata) -- scope is ``UNSCOPED`` when metadata is absent
        or ambiguous, and event-level agreement is then not asserted."""
        from talonx_ops.runtime_metadata import read_runtime_metadata

        try:
            meta = read_runtime_metadata(self.config.original_runtime_metadata_path)
        except Exception:  # noqa: BLE001
            meta = None
        if not isinstance(meta, dict):
            return UNSCOPED, None
        sha = meta.get("commit_sha")
        started = meta.get("started_at")
        run_mode = meta.get("run_mode")
        provider = meta.get("market_data_provider_configured")
        if not sha or not started:
            return UNSCOPED, meta
        material = f"{sha}|{started}|{run_mode}|{provider}"
        digest = hashlib.sha256(material.encode()).hexdigest()[:12]
        return f"{ORIGINAL_SCOPE_PREFIX}{digest}", meta

    # --- Original metrics (Redis DB 0, read-only) ------------------

    def _read_original_metrics(self, date_candidates: list[str]) -> tuple[dict[str, dict[str, int]], bool | None, list[dict]]:
        if self.original_redis is None:
            return {}, None, []
        diags: list[dict] = []
        # a genuinely read-only client: reject any mutating attribute up front.
        for banned in ("set", "delete", "publish", "incr", "hset", "expire"):
            fn = getattr(self.original_redis, banned, None)
            if fn is not None and getattr(fn, "_compare_readonly_blocked", False):
                pass  # a wrapper already blocks it; fine
        try:
            self.original_redis.ping()
            ping_ok = True
        except Exception as exc:  # noqa: BLE001 -- a connection failure is a health signal
            return {}, False, [{"kind": "SOURCE_UNAVAILABLE", "source": "redis:original",
                                "detail": f"metrics read failed -- ping: {exc}"}]
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
                              "detail": f"metrics scan/mget failed: {exc}"})
        return metrics, ping_ok, diags

    # --- the main pass ---------------------------------------------

    def collect_once(
        self,
        *,
        now: datetime | None = None,
        trading_date: str | None = None,
        captured_original_messages: list[dict[str, Any]] | None = None,
        captured_piv_messages: list[dict[str, Any]] | None = None,
        transport_health: dict[str, Any] | None = None,
    ) -> CollectResult:
        now = now or self.clock()
        now_iso = now.isoformat()
        self._pass_count += 1
        sd = self.config.piv_state_dir
        diagnostics: list[dict[str, Any]] = []
        transport_health = dict(transport_health or {})  # own copy -- never a live ref

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

        # --- 3. Original run scope + sources ---
        the_date = trading_date or piv_trading_date
        original_run_scope, original_meta = self._derive_original_run_scope()
        original_records: list[ComparisonRecord] = []
        redis_ping_ok = None
        metrics: dict[str, dict[str, int]] = {}
        if the_date is not None:
            date_candidates = [the_date, now.astimezone(timezone.utc).date().isoformat()]
            metrics, redis_ping_ok, mdiags = self._read_original_metrics(date_candidates)
            diagnostics += mdiags
            recs, d = P.project_original_metrics(
                metrics, trading_date=the_date, run_scope=original_run_scope, as_of=now_iso)
            original_records += recs
            diagnostics += d
        if captured_original_messages:
            recs, d = P.project_original_messages(
                captured_original_messages, trading_date=the_date, run_scope=original_run_scope)
            original_records += recs
            diagnostics += d
        if captured_piv_messages:
            recs, d = P.project_original_messages(
                captured_piv_messages, trading_date=the_date, run_scope=session_id, pipeline=PIPELINE_PIV)
            for r in recs:
                piv_records.append(r)
            diagnostics += d

        if the_date is None:
            return CollectResult(
                None, False, False, 0, 0, 0, diagnostics, [], None, {},
                skipped_reason="no trading date could be resolved -- immutable manifest NOT written",
            )

        # --- 4. transport-aware source-health snapshot ---
        cfg = self.config
        orig_transport = transport_health.get("ORIGINAL") or {}
        piv_transport = transport_health.get("PIV") or {}
        redis_state = self._original_redis_state(redis_ping_ok, orig_transport)
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
            # PIV Pub/Sub health is SEPARATE from PIV state-file health (§4.7)
            "piv_pubsub": piv_transport or classify_redis(None, detail="PIV Pub/Sub not observed").to_dict(),
            "original_redis": redis_state,
            "original_pubsub": orig_transport or classify_redis(
                None, detail="Original Pub/Sub not observed").to_dict(),
        }
        capability_limitations = {"durable_quant_state_store": QUANT_STATE_STORE_LIMITATION}
        original_health_ok = redis_state["state"] in ("RUNNING", "NOT_RUN")
        piv_health_ok = all(
            source_health[k]["state"] in ("HEALTHY", "RUNNING", "NOT_RUN")
            for k in ("piv_session_identity", "piv_events", "piv_lifecycle_state")
        )

        # --- 5. WRITE PHASE (collector-lock guarded; integrity fail-closed) ---
        with CollectorLock(cfg.lock_path, stale_after_seconds=120.0, acquire_wait=15.0):
            writer = EvidenceWriter(cfg.evidence_root, the_date)

            expected_sessions = {s for s in (session_id, original_run_scope) if s}
            pre = writer.verify_before_write(expect_session_ids=expected_sessions or None)
            if not pre.ok and (writer.dir / "manifest.json").exists():
                merged_diags = self._merge_diagnostics(writer.read_diagnostics(), diagnostics + [{
                    "kind": "UNREADABLE", "source": "archive",
                    "detail": f"pre-existing archive integrity {pre.state}: {'; '.join(pre.problems)} "
                              f"-- write phase ABORTED, hashes NOT regenerated",
                }])
                return CollectResult(
                    trading_date=the_date, manifest_written=False, manifest_conflict=False,
                    original_appended=0, piv_appended=0, duplicates_skipped=0,
                    diagnostics=merged_diags, divergences=[], evidence_dir=str(writer.dir),
                    source_health=source_health, archive_integrity=pre.to_dict(),
                    write_aborted=True,
                    skipped_reason="pre-existing archive failed integrity verification",
                )

            # 5a. immutable manifest -- written only now that date + PIV
            # bindings are resolved.
            manifest = self._build_immutable_manifest(the_date, identity)
            mres = writer.write_manifest(manifest)
            if mres.conflict:
                diagnostics.append({
                    "kind": "WRONG_SESSION", "source": "manifest.json",
                    "detail": mres.detail,
                })

            # 5b. append (dedup)
            o_app, o_dup = writer.append_original_events(original_records)
            p_app, p_dup = writer.append_piv_records(piv_records)
            if o_dup or p_dup:
                diagnostics.append({
                    "kind": "DUPLICATE", "source": "evidence",
                    "detail": f"{o_dup} Original + {p_dup} PIV re-delivered record(s) recognised and skipped",
                })

            # 5c. read back (surfacing any malformed lines, never dropping silently)
            all_original, o_bad = writer.read_records_with_problems("original_events.jsonl")
            all_piv, p_bad = writer.read_records_with_problems("piv_records.jsonl")
            for desc in o_bad + p_bad:
                diagnostics.append({"kind": "MALFORMED", "source": "evidence", "detail": desc})

            # 5d. align + classify (session- and event-safe)
            pairs, divs = compare(
                all_original, all_piv, restrict_trading_date=the_date,
                original_run_scope=original_run_scope,
                original_source_health_ok=original_health_ok,
                piv_source_health_ok=piv_health_ok,
            )
            self._detect_missing_stages(pairs, diagnostics)

            # 5e. telegram / notification telemetry verdict
            notif = assess_piv_notification(sd, session_id)

            # 5f. derived views + runtime status + hashes (all atomic)
            writer.write_comparison(
                self._comparison_payload(the_date, pairs, source_health, capability_limitations,
                                         original_run_scope))
            writer.write_divergences([x.to_dict() for x in divs])
            writer.write_telegram(self._telegram_payload(the_date, metrics, notif, session_id))
            merged_diags = self._merge_diagnostics(writer.read_diagnostics(), diagnostics)
            writer.write_diagnostics(merged_diags)

            runtime_status = self._runtime_status(
                the_date, now_iso, identity, lifecycle if isinstance(lifecycle, dict) else {},
                redis_ping_ok, transport_health, source_health, pairs, divs,
                o_app, p_app, o_dup + p_dup, original_run_scope, original_meta, notif,
                eod if isinstance(eod, dict) else {},
            )
            writer.write_runtime_status(runtime_status)
            writer.write_file_hashes()
            post = writer.verify_archive(expect_session_ids=expected_sessions or None)

            # 5g. cursors (collector-owned)
            cursors = self._load_cursors()
            cursors.setdefault("files", {})
            for p in cfg.observed_paths():
                if p.exists():
                    st = p.stat()
                    cursors["files"][str(p)] = {"mtime": st.st_mtime, "size": st.st_size}
            cursors["last_run_utc"] = now_iso
            cursors["pass_count"] = self._pass_count
            cursors.setdefault("dates_seen", [])
            if the_date not in cursors["dates_seen"]:
                cursors["dates_seen"].append(the_date)
            self._save_cursors(cursors)

        return CollectResult(
            trading_date=the_date,
            manifest_written=mres.written,
            manifest_conflict=mres.conflict,
            manifest_changed_fields=mres.changed_fields,
            original_appended=o_app,
            piv_appended=p_app,
            duplicates_skipped=o_dup + p_dup,
            diagnostics=merged_diags,
            divergences=[x.to_dict() for x in divs],
            evidence_dir=str(writer.dir),
            source_health=source_health,
            archive_integrity=post.to_dict(),
            runtime_status=runtime_status,
        )

    # --- helpers ---------------------------------------------------

    @staticmethod
    def _original_redis_state(redis_ping_ok: bool | None, orig_transport: dict[str, Any]) -> dict[str, Any]:
        """A failed subscription (transport) OR a failed metrics ping is
        DISCONNECTED, never NOT_RUN. A live transport with no metrics read
        yet is still RUNNING."""
        t_state = orig_transport.get("state")
        if t_state == "DISCONNECTED":
            return {"state": "DISCONNECTED", "detail": orig_transport.get("last_error")
                    or "Original Pub/Sub subscription failed", "age_seconds": None,
                    "last_update": orig_transport.get("last_message_at"), "scope": None,
                    "trustworthy_zero": False}
        if redis_ping_ok is False:
            return {"state": "DISCONNECTED", "detail": "Original metrics Redis unreachable",
                    "age_seconds": None, "last_update": None, "scope": None, "trustworthy_zero": False}
        if redis_ping_ok is True or t_state in ("RUNNING", "STALE"):
            return {"state": "STALE" if t_state == "STALE" else "RUNNING",
                    "detail": "Original metrics Redis reachable" if redis_ping_ok else
                              "Original Pub/Sub connected",
                    "age_seconds": None, "last_update": orig_transport.get("last_message_at"),
                    "scope": None, "trustworthy_zero": t_state != "STALE"}
        return classify_redis(None).to_dict()

    def _build_immutable_manifest(self, the_date: str, identity: dict) -> dict[str, Any]:
        """ONLY stable identity/binding fields (§2.2). Any change to one of
        these against a previously-written manifest is a visible conflict;
        the original is never overwritten."""
        from talonx_piv.config import PivConfig
        from talonx_piv.execution_settings import load_paper_entry_settings

        piv_cfg = PivConfig()
        settings = load_paper_entry_settings(self.config.piv_state_dir / "paper_entry_settings.json")
        any_paper_enabled = any(settings.enabled_for(t) for t in piv_cfg.universe)
        execution_mode = "PAPER" if any_paper_enabled else "SHADOW"
        return {
            "schema_version": "83r1",
            "trading_date": the_date,
            "original": {
                "redis_url_scheme": self.config.original_redis_url.split("://", 1)[0],
                "redis_db": self.config.original_redis_url.rsplit("/", 1)[-1],
                "channels": sorted(self.config.original_channels().values()),
                "stage_modules": list(self.config.original_stage_modules()),
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
                "redis_namespace": PivConfig().redis_namespace,
                "channels": sorted(self.config.piv_channels().values()),
                "universe": sorted(piv_cfg.universe),
                "execution_mode": execution_mode,
                "strategy_approval_status": "UNVALIDATED",
                "real_capital_prohibited": True,
            },
            "collector": {
                "namespace": self.config.namespace,
                "role": "PASSIVE_OBSERVER",
                "publishes": False,
                "acknowledges": False,
                "mutates_observed_pipelines": False,
            },
            "not_alpha_evidence": AGREEMENT_IS_NOT_ALPHA,
        }

    def _runtime_status(
        self, the_date, now_iso, identity, lifecycle, redis_ping_ok, transport_health,
        source_health, pairs, divs, o_app, p_app, dup, original_run_scope, original_meta, notif, eod,
    ) -> dict[str, Any]:
        return {
            "trading_date": the_date,
            "generated_at": now_iso,
            "collection": {
                "pass_count": self._pass_count,
                "records_appended": {"original": o_app, "piv": p_app},
                "duplicates_skipped": dup,
                "aligned_pairs": len(pairs),
                "divergences": len(divs),
            },
            "transport_health": transport_health,
            "original_metrics_redis_reachable": redis_ping_ok,
            "original_run_scope": {
                "value": original_run_scope,
                "derivation": "collector-derived from verified runtime_metadata.json "
                              "(commit_sha|started_at|run_mode|provider) -- NOT an Original session id",
                "runtime_metadata_present": original_meta is not None,
            },
            "piv_lifecycle_status": {
                "session_enabled": bool(lifecycle.get("session_enabled")),
                "kill_switch": bool(lifecycle.get("kill_switch")),
                "entry_admission_blocked": bool(
                    (lifecycle.get("reconciliation_flags") or {}).get("entry_admission_blocked")),
            },
            "piv_session_id": identity.get("session_id"),
            "eod_status": eod.get("status"),
            "eod_trading_date_et": eod.get("trading_date_et"),
            "source_health": source_health,
            "notification_telemetry_verdict": notif.get("verdict"),
            "not_alpha_evidence": AGREEMENT_IS_NOT_ALPHA,
        }

    def _comparison_payload(self, the_date, pairs, source_health, capability_limitations,
                            original_run_scope) -> dict[str, Any]:
        by_stage: dict[str, dict[str, Any]] = {}
        by_symbol_stage: list[dict[str, Any]] = []
        for pair in pairs:
            s = by_stage.setdefault(pair.stage, {
                "kind": pair.record_kind, "original_events": 0, "piv_events": 0,
                "original_aggregate_total": 0.0, "piv_aggregate_total": 0.0,
                "agree": 0, "diverge": 0,
            })
            has_o = pair.original is not None
            has_p = pair.piv is not None
            if pair.record_kind == KIND_AGGREGATE:
                if has_o:
                    s["original_aggregate_total"] += float(pair.original.aggregate_value or 0)
                if has_p:
                    s["piv_aggregate_total"] += float(pair.piv.aggregate_value or 0)
            else:
                s["original_events"] += int(has_o)
                s["piv_events"] += int(has_p)
            agree = (
                has_o and has_p
                and pair.original_run_scope not in (None, UNSCOPED)
                and pair.original.payload_fingerprint == pair.piv.payload_fingerprint
                and pair.original.execution_class == pair.piv.execution_class
            )
            s["agree"] += int(agree)
            s["diverge"] += int(has_o and has_p and not agree)
            by_symbol_stage.append({
                "trading_date": pair.trading_date, "stage": pair.stage, "symbol": pair.symbol,
                "event_identity": pair.event_identity, "record_kind": pair.record_kind,
                "piv_run_scope": pair.piv_run_scope, "original_run_scope": pair.original_run_scope,
                "original_present": has_o, "piv_present": has_p,
                "original_outcome": pair.original.decision_outcome if has_o else None,
                "piv_outcome": pair.piv.decision_outcome if has_p else None,
                "original_execution_class": pair.original.execution_class if has_o else None,
                "piv_execution_class": pair.piv.execution_class if has_p else None,
                "agree": agree,
                "event_level_agreement_assertable": pair.original_run_scope not in (None, UNSCOPED),
            })
        return {
            "trading_date": the_date,
            "original_run_scope": original_run_scope,
            "event_level_agreement_assertable": original_run_scope not in (None, UNSCOPED),
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

    def _telegram_payload(self, the_date, metrics: dict, notif: dict, session_id: str | None) -> dict[str, Any]:
        dispatch = metrics.get("dispatch", {})
        telegram_totals = {k: int(v) for k, v in sorted(dispatch.items()) if "telegram" in k}
        return {
            "trading_date": the_date,
            "original_telegram_totals": telegram_totals,
            "original_telegram_counters": sorted(telegram_totals.keys()),
            "original_telegram_owner": "ORIGINAL",
            "piv_session_id": session_id,
            "piv_notification_telemetry": {
                "verdict": notif.get("verdict"),
                "detail": notif.get("detail"),
                "telemetry": notif.get("telemetry"),
            },
            "piv_zero_attempt_assertion": bool(notif.get("piv_zero_attempt_assertion")),
        }

    @staticmethod
    def _detect_missing_stages(pairs, diagnostics: list[dict[str, Any]]) -> None:
        for pair in pairs:
            if pair.record_kind == KIND_AGGREGATE:
                continue
            if (pair.original is None) ^ (pair.piv is None):
                missing = "PIV" if pair.original is not None else "ORIGINAL"
                diagnostics.append({
                    "kind": "MISSING", "source": f"{pair.stage}/{pair.symbol or '*'}",
                    "detail": f"{missing} has no record for ({pair.trading_date}, {pair.stage}, "
                              f"{pair.symbol or '*'}, {pair.event_identity})",
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
