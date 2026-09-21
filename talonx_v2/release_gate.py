"""
talonx_v2.release_gate -- FINAL V2 RELEASE ACCEPTANCE: explicit release profile + read-only readiness gate
========================================================================================================
The first-release V2 configuration is EXPLICIT and AUDITABLE (``RELEASE_PROFILE``).  A release start must
never fall back to the stale default CSV pricing mode, and must not start unless every readiness check
passes.  Research / replay / study paths keep their existing adapters -- the release profile is opt-in
(``talonx_v2.run --release`` / ``python -m talonx_ops.prospective start --release``).

``evaluate_release_readiness`` is READ-ONLY and never sends anything:
  * bounded read-only market-data calls only (provider readiness; no broker endpoint),
  * SQLite opened ``mode=ro``,
  * Telegram destinations are RESOLVED and fingerprint-compared against the previously validated
    delivery record -- no message is sent, no token/chat value is ever emitted.

READY <=> no FAIL.  A WARN is disclosed but not blocking (e.g. a legacy ledger that will be seeded on
first open).
"""
from __future__ import annotations

import importlib
import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ReleaseProfile:
    profile_id: str = "V2_RELEASE_CANDIDATE_PROFILE@1"
    strategy: str = "INSIDER_BUY_CLUSTER_V2"
    strategy_version: str = "INSIDER_BUY_CLUSTER_V2@1"
    strategy_fingerprint: str = "e2acf6454789217e"
    execution_mode: str = "PAPER"
    real_capital: bool = False
    pricing_mode: str = "sip"
    provider: str = "alpaca"
    feed: str = "sip"
    adjustment: str = "split"
    contract_id: str = "V2_RELEASE_PRICE_CONTRACT@1"
    contract_fingerprint: str = "ac5e51aa3599d6c9"
    fallback_mode: str = "NONE"
    default_starting_cash_usd: float = 100_000.0
    default_allocation_usd: float = 10_000.0
    signal_destination: str = "TRADE_EVENT"          # TalonX Signal
    sentinel_destination: str = "OPERATIONS"         # TalonX Sentinel
    lab_destination: str = "RESEARCH"                # TalonX Lab
    lab_enabled: bool = False
    delivery_required: bool = True
    transport: str = "telegram"
    default_validation_record: str = "docs/research/evidence/v2_release_integration_ri4/delivery_validation.json"
    launch_argv: tuple = ("python", "-m", "talonx_ops.prospective", "start", "--release",
                          "--tick-seconds", "150", "--heartbeat-seconds", "30", "--live-lookback-days", "45",
                          "--execution-scope", "resolved-active-watchlist", "--deliver", "--transport", "telegram")


RELEASE_PROFILE = ReleaseProfile()


@dataclass
class Check:
    name: str
    status: str            # PASS | FAIL | WARN
    detail: str = ""


@dataclass
class ReleaseReadinessReport:
    checks: list = field(default_factory=list)

    def add(self, name: str, status: str, detail: str = "") -> None:
        self.checks.append(Check(name, status, detail))

    @property
    def failed(self) -> list:
        return [c for c in self.checks if c.status == "FAIL"]

    @property
    def status(self) -> str:
        return "READY" if not self.failed else "NOT_READY"

    def to_dict(self) -> dict:
        return {"profile": RELEASE_PROFILE.profile_id, "status": self.status,
                "checks": [c.__dict__ for c in self.checks],
                "evaluated_at_utc": datetime.now(timezone.utc).isoformat()}


def resolve_pricing_mode(requested: str | None, *, release: bool) -> str:
    """``--release`` => SIP, explicit and non-negotiable; anything else keeps the pre-existing default."""
    if release:
        if requested not in (None, RELEASE_PROFILE.pricing_mode):
            raise ValueError(f"release mode requires pricing mode {RELEASE_PROFILE.pricing_mode!r}, "
                             f"got {requested!r} (the stale csv default and study modes are not release providers)")
        return RELEASE_PROFILE.pricing_mode
    return requested or "csv"


@contextmanager
def _scoped_env(env):
    """Make ``resolve_destination_config`` see exactly ``env``'s Telegram/notify variables (hermetic for
    tests); a no-op when ``env`` is the real process environment.  Always restored."""
    if env is os.environ:
        yield
        return
    prefixes = ("TELEGRAM_", "TALONX_NOTIFY_")
    saved = {k: os.environ.get(k) for k in set(os.environ) | set(env) if k.startswith(prefixes)}
    try:
        for k in [k for k in os.environ if k.startswith(prefixes)]:
            del os.environ[k]
        for k, v in env.items():
            if k.startswith(prefixes):
                os.environ[k] = v
        yield
    finally:
        for k in [k for k in os.environ if k.startswith(prefixes)]:
            del os.environ[k]
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def _strategy_fingerprint() -> str:
    m = importlib.import_module("research.scripts.task112_v2_release_fingerprint")
    return str(m.v2_release_fingerprint().get("fingerprint", ""))


def _ro(path: str | Path) -> sqlite3.Connection | None:
    p = Path(path)
    if not p.is_file():
        return None
    con = sqlite3.connect(p.resolve().as_uri() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def evaluate_release_readiness(*, db_path: str | Path, pricing_mode: str | None, deliver: bool = False,
                               transport: str | None = None, env: dict | None = None,
                               http_get: Callable | None = None, now: Callable[[], datetime] | None = None,
                               validation_path: str | Path | None = None,
                               profile: ReleaseProfile = RELEASE_PROFILE) -> ReleaseReadinessReport:
    from talonx_ops.notify import DESTINATIONS, resolve_destination_config
    from talonx_ops.operator_read import notification_validation_view
    from talonx_v2 import provider_contract as pc
    from talonx_v2.config import V2Config

    env = os.environ if env is None else env
    rep = ReleaseReadinessReport()

    # 1. release pricing mode: SIP, never the stale csv default
    rep.add("release_pricing_mode", "PASS" if pricing_mode == profile.pricing_mode else "FAIL",
            f"pricing_mode={pricing_mode!r}; release requires {profile.pricing_mode!r} "
            f"(csv default is stale prospectively and is NOT a release provider)")

    # 2. provider readiness: configured -> reachable -> entitled -> qualified (bounded, read-only)
    pr = pc.check_readiness(env=dict(env), http_get=http_get, now=now)
    rep.add("provider_readiness", "PASS" if pr.qualified else "FAIL",
            f"level={pr.level}" + (f"; problems={pr.problems}" if pr.problems else ""))

    # 3-4. fingerprints
    cid, cfp = pc.RELEASE_CONTRACT.contract_id, pc.RELEASE_CONTRACT.fingerprint()
    rep.add("provider_contract_fingerprint",
            "PASS" if (cid == profile.contract_id and cfp == profile.contract_fingerprint) else "FAIL",
            f"contract={cid} fingerprint={cfp} expected={profile.contract_id}/{profile.contract_fingerprint}")
    try:
        sfp = _strategy_fingerprint()
        rep.add("strategy_fingerprint", "PASS" if sfp == profile.strategy_fingerprint else "FAIL",
                f"computed={sfp} expected={profile.strategy_fingerprint}")
    except Exception as exc:  # noqa: BLE001
        rep.add("strategy_fingerprint", "FAIL", f"could not compute: {type(exc).__name__}: {exc}"[:200])
    rep.add("provider_semantics", "PASS" if (pc.RELEASE_CONTRACT.provider, pc.RELEASE_CONTRACT.feed,
                                            pc.RELEASE_CONTRACT.adjustment, pc.RELEASE_CONTRACT.fallback_mode)
            == (profile.provider, profile.feed, profile.adjustment, profile.fallback_mode) else "FAIL",
            f"{pc.RELEASE_CONTRACT.provider}/{pc.RELEASE_CONTRACT.feed}/adjustment={pc.RELEASE_CONTRACT.adjustment}"
            f"/fallback={pc.RELEASE_CONTRACT.fallback_mode}")

    # 5. paper only, no real capital, frozen contract intact
    try:
        cfg = V2Config()
        cfg.validate_frozen()
        ok = (cfg.allow_real_capital is False and cfg.execution_mode == profile.execution_mode
              and not profile.real_capital)
        rep.add("paper_only_frozen_contract", "PASS" if ok else "FAIL",
                f"execution_mode={cfg.execution_mode} allow_real_capital={cfg.allow_real_capital} "
                f"starting_cash={cfg.starting_cash_usd:,.0f} allocation={cfg.per_position_allocation_usd:,.0f}")
    except AssertionError as exc:
        rep.add("paper_only_frozen_contract", "FAIL", f"frozen contract violated: {exc}")

    # 6. Telegram: Signal + Sentinel configured, distinct, validated delivery still bound to the ACTIVE config;
    #    Lab OFF.  NOTHING is sent and no token/chat is emitted.
    with _scoped_env(env):
        cfgs = {d: resolve_destination_config(d) for d in DESTINATIONS}
        sig, sen, lab = (cfgs[profile.signal_destination], cfgs[profile.sentinel_destination],
                         cfgs[profile.lab_destination])
        rep.add("signal_destination_configured", "PASS" if sig.enabled else "FAIL", sig.reason)
        rep.add("sentinel_destination_configured", "PASS" if sen.enabled else "FAIL", sen.reason)
        distinct = bool(sig.enabled and sen.enabled and (sig.bot_token, sig.chat_id) != (sen.bot_token, sen.chat_id))
        rep.add("signal_sentinel_distinct", "PASS" if distinct else "FAIL",
                "Signal and Sentinel resolve to different destination pairs" if distinct
                else "Signal/Sentinel not both configured or alias one another")
        rep.add("lab_off", "PASS" if not lab.enabled else "FAIL", lab.reason)
        vpath = validation_path or env.get("TALONX_NOTIFY_VALIDATION_PATH") or (REPO_ROOT / profile.default_validation_record)
        val = notification_validation_view(str(vpath), cfgs)
        for dest, label in ((profile.signal_destination, "signal"), (profile.sentinel_destination, "sentinel")):
            rep.add(f"{label}_delivery_validation_bound", "PASS" if val.get(dest) else "FAIL",
                    f"{dest}: prior controlled delivery "
                    + ("VALIDATED and its one-way fingerprint matches the ACTIVE config" if val.get(dest)
                       else "NOT validated for the ACTIVE config (missing record, not SENT, or credentials/chat changed)"))
    if profile.delivery_required:
        ok = bool(deliver and (transport == profile.transport))
        rep.add("signal_delivery_enabled", "PASS" if ok else "FAIL",
                f"deliver={deliver} transport={transport!r}; release requires --deliver --transport {profile.transport}")

    # 6b. Company-development (Intelligence) Telegram delivery is opt-in and NOT part of the V2 primary release:
    #     primary Telegram for company developments requires the Session 7 acceptance criteria (OPS-011, not built).
    #     Disclosed, not blocking -- an operator decision.
    intel_on = str(env.get("TALONX_INTEL_DELIVER_CARDS", "")).strip().lower() in ("1", "true", "yes", "on")
    rep.add("intelligence_card_delivery", "WARN" if intel_on else "PASS",
            "Intelligence card delivery is ENABLED: company-development Telegram is opt-in and its Session-7 "
            "acceptance (OPS-011) is not built -- disclosed operator decision" if intel_on
            else "Intelligence card delivery is OFF (company developments stay dashboard-visible)")

    # 7. ledger / campaign / account state (read-only)
    con = _ro(db_path)
    if con is None:
        rep.add("campaign_identity", "WARN", "no ledger file yet: a fresh campaign is seeded once at first open")
        rep.add("account_blocks", "PASS", "no ledger -> no active block")
        rep.add("startup_reconciliation", "PASS", "no ledger -> nothing to reconcile")
    else:
        try:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            row = con.execute("SELECT * FROM campaign WHERE id=1").fetchone() if "campaign" in tables else None
            if row is None:
                rep.add("campaign_identity", "WARN",
                        "legacy ledger without a campaign record: it is migrated once (starting cash NOT fabricated)")
            else:
                ok = (row["strategy_version"] == profile.strategy_version and row["execution_mode"] == profile.execution_mode)
                rep.add("campaign_identity", "PASS" if ok else "FAIL",
                        f"campaign_id={row['campaign_id']} strategy_version={row['strategy_version']} "
                        f"execution_mode={row['execution_mode']} provenance={row['provenance']}")
            blocks = []
            if "account_blocks" in tables:
                blocks = [dict(r) for r in con.execute(
                    "SELECT reason_type, reference FROM account_blocks WHERE status='ACTIVE'")]
            rep.add("account_blocks", "PASS" if not blocks else "FAIL",
                    "no active account block" if not blocks else f"ACTIVE blocks: {[b['reason_type'] for b in blocks]}")
        finally:
            con.close()
        try:
            from talonx_ops.prospective.ledger_guard import check_ledger_continuity
            lc = check_ledger_continuity(db_path)
            rep.add("startup_reconciliation", "PASS" if not lc.problems else "FAIL",
                    "ledger reconciles" if not lc.problems else f"problems: {lc.problems[:3]}")
        except Exception as exc:  # noqa: BLE001
            rep.add("startup_reconciliation", "FAIL", f"could not verify: {type(exc).__name__}: {exc}"[:200])
    return rep


def main(argv=None) -> int:      # pragma: no cover - CLI, read-only
    import argparse
    from dotenv import load_dotenv
    load_dotenv(".env", override=False)
    ap = argparse.ArgumentParser(description="V2 release readiness gate (read-only; sends nothing)")
    ap.add_argument("--db", default=str(REPO_ROOT / "v2_lane.db"))
    ap.add_argument("--pricing-mode", default="sip")
    ap.add_argument("--deliver", action="store_true", default=True)
    ap.add_argument("--transport", default="telegram")
    a = ap.parse_args(argv)
    rep = evaluate_release_readiness(db_path=a.db, pricing_mode=a.pricing_mode, deliver=a.deliver, transport=a.transport)
    print(json.dumps(rep.to_dict(), indent=2))
    return 0 if rep.status == "READY" else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
