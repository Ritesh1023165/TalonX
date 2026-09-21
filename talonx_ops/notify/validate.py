"""Controlled physical-delivery validation (the RI-4 procedure as a command) -- for RE-validating a destination after its bot
credential was rotated.

Rotating a bot token changes the one-way fingerprint that binds a validation record to the ACTIVE destination pair, so the
previous validation no longer applies (release gate: ``*_delivery_validation_bound`` FAIL -> NEEDS_REVALIDATION).  This sends ONE
harmless notice per selected destination through the normal durable path

    validation event -> TEMPORARY outbox PENDING -> destination worker -> Telegram -> SENT

and records a sanitized validation record (logical event id, state, attempts, timestamp, one-way fingerprint -- never a token,
chat id, URL or payload).  DRY-RUN unless ``--send`` is given; TalonX Lab (RESEARCH) can never be validated here; a destination
whose token still matches a known-compromised fingerprint is refused.

    .venv\\Scripts\\python.exe -m talonx_ops.notify.validate --destination OPERATIONS --destination TRADE_EVENT --send
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from talonx_ops.notify import OPERATIONS, TRADE_EVENT, resolve_destination_config
from talonx_ops.notify.outbox import NotifyStore
from talonx_ops.notify.worker import drain

_TEXT = {
    TRADE_EVENT: "TalonX Signal - release validation notice. No trade was executed. No action required.",
    OPERATIONS: "TalonX Sentinel - release validation notice. No incident was detected. No action required.",
}
DEFAULT_RECORD = "docs/research/evidence/v2_release_integration_ri4/delivery_validation.json"


def validate(destinations, *, record_path: str | Path = DEFAULT_RECORD, send: bool = False, client_factory=None) -> dict:
    """Validate ``destinations``; returns a sanitized result dict.  ``client_factory(destination)`` is injectable for tests."""
    from talonx_ops.log_redaction import secret_fingerprint
    from talonx_ops.operator_read import _destination_fingerprint
    from talonx_v2.release_gate import RELEASE_PROFILE

    out: dict = {"send": bool(send), "destinations": {}}
    record: dict = {}
    rp = Path(record_path)
    if rp.is_file():
        try:
            record = json.loads(rp.read_text(encoding="utf-8"))
        except ValueError:
            record = {}
    if record.get("schema_version") != 1 or record.get("kind") != "ri4_controlled_telegram_validation":
        record = {"schema_version": 1, "kind": "ri4_controlled_telegram_validation", "destinations": {}}
    record.setdefault("destinations", {})

    for dest in destinations:
        if dest not in (TRADE_EVENT, OPERATIONS):
            out["destinations"][dest] = {"result": "REFUSED", "reason": "only Signal (TRADE_EVENT) and Sentinel (OPERATIONS) are validated; Lab stays OFF"}
            continue
        cfg = resolve_destination_config(dest)
        if not (cfg.enabled and cfg.bot_token and cfg.chat_id):
            out["destinations"][dest] = {"result": "NOT_CONFIGURED", "reason": cfg.reason}
            continue
        if secret_fingerprint(cfg.bot_token) in RELEASE_PROFILE.compromised_secret_fingerprints:
            out["destinations"][dest] = {"result": "REFUSED", "reason": "ROTATION_REQUIRED: this destination still uses a compromised bot token"}
            continue
        fp = _destination_fingerprint(cfg)
        if not send:
            out["destinations"][dest] = {"result": "DRY_RUN", "would_send": "one harmless validation notice", "active_pair_fingerprint": fp[:12]}
            continue
        with tempfile.TemporaryDirectory() as td:                                   # NEVER the production/release outbox
            store = NotifyStore(str(Path(td) / "validation_outbox.db"))
            eid = f"ri4-{'signal' if dest == TRADE_EVENT else 'sentinel'}-{uuid.uuid4().hex}"
            store.enqueue(event_id=eid, destination=dest, event_type="RELEASE_VALIDATION", producer="talonx_ops.notify.validate",
                          dedup_key=eid, payload_text=_TEXT[dest], provenance={"purpose": "post-rotation controlled validation"})
            res = drain(store, destination=dest, client=(client_factory(dest) if client_factory else None))
            row = store.all_outbox(destination=dest)[0]
        ok = row["state"] == "SENT"
        out["destinations"][dest] = {"result": "SENT" if ok else row["state"], "attempts": row["attempts"], "drain": {k: v for k, v in res.items() if isinstance(v, int)}}
        if ok:
            record["destinations"][dest] = {"event_id": eid, "state": "SENT", "attempts": row["attempts"],
                                            "configuration_fingerprint": fp}
    if send and any(v.get("result") == "SENT" for v in out["destinations"].values()):
        record["validated_at_utc"] = datetime.now(timezone.utc).isoformat()
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(json.dumps(record, indent=2), encoding="utf-8")
        out["record_written"] = str(rp)
    return out


def main(argv=None) -> int:
    import argparse
    from dotenv import load_dotenv
    load_dotenv(".env", override=False)
    ap = argparse.ArgumentParser(description="controlled Signal/Sentinel delivery validation (dry-run unless --send)")
    ap.add_argument("--destination", action="append", choices=[TRADE_EVENT, OPERATIONS, "RESEARCH"], required=True)
    ap.add_argument("--record", default=DEFAULT_RECORD)
    ap.add_argument("--send", action="store_true", help="actually send ONE harmless notice per destination")
    a = ap.parse_args(argv)
    res = validate(a.destination, record_path=a.record, send=a.send)
    print(json.dumps(res, indent=2))
    return 0 if all(v.get("result") in ("SENT", "DRY_RUN") for v in res["destinations"].values()) else 2


if __name__ == "__main__":
    sys.exit(main())
