"""
talonx_v2.run -- V2 lane entry point (opt-in, additive)
=====================================================
Modes
-----
  --mode replay   deterministic offline replay from the Task 107A research
                  parquet + a local daily-bar directory (Alpaca SIP CSVs).
                  Produces v2_lane.db + a JSON summary.  No network beyond
                  the bar files already on disk.  DEFAULT.
  --mode recover  print restart-recovery summary for an existing v2_lane.db
                  (open positions, overdue exits) and exit.
  --mode live     the Tuesday companion loop -- detect causally-ripe
                  episodes, open/hold/close the frozen 10-td paper
                  positions, write a heartbeat + status file.  --once
                  runs a single tick (dry-run / supervisor readiness).
  --mode status   print the current v2_service_status.json and exit.

This is NOT started by the Original supervisor automatically.  It is the
V2 lane, run explicitly:  ``python -m talonx_v2.run --mode replay ...``.

Never sends Telegram, never touches a broker, never uses real capital.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

# Task 132: load the shared .env (same resolution approach as dashboard.py /
# talonx_ops/supervisor.py) BEFORE anything reads an env var -- this is the
# V2 companion's own standalone entrypoint (not a supervisor child), so
# without this, TELEGRAM_BOT_TOKEN/CHAT_ID and the TALONX_* toggles are only
# visible if the invoking shell happened to export them first. override=False:
# a real env var already set in the shell always wins.
try:
    from dotenv import load_dotenv
    _shared_env = Path(__file__).resolve().parent.parent / ".env"
    if _shared_env.is_file():
        load_dotenv(_shared_env, override=False)
except ImportError:  # pragma: no cover
    pass

from talonx_v2 import form4_source, pipeline
from talonx_v2.config import V2_VERSION, V2Config
from talonx_v2.store import V2Store


def _bar_dir_lookup(bar_dirs: list[Path]):
    import pandas as pd

    cache: dict[str, list[dict]] = {}

    def _load(sym: str) -> list[dict]:
        if sym in cache:
            return cache[sym]
        for d in bar_dirs:
            f = d / f"{sym}.csv"
            if f.exists() and f.stat().st_size > 20:
                try:
                    df = pd.read_csv(f)
                except Exception:  # noqa: BLE001
                    continue
                if "date" not in df.columns:
                    continue
                rows = [{"date": str(r.date)[:10], "open": float(getattr(r, "open", "nan")),
                         "close": float(r.close), "volume": float(getattr(r, "volume", 0) or 0)}
                        for r in df.itertuples(index=False)]
                cache[sym] = rows
                return rows
        cache[sym] = []
        return []

    def bars_lookup(sym: str) -> list[dict]:
        return _load(sym)

    def price_lookup(sym: str, session: date) -> dict | None:
        s = session.isoformat() if isinstance(session, date) else str(session)[:10]
        for row in _load(sym):
            if row["date"] == s:
                return row
        return None

    return bars_lookup, price_lookup


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser("talonx_v2.run")
    ap.add_argument("--mode", choices=["replay", "recover", "live", "status"], default="replay")
    ap.add_argument("--once", action="store_true", help="live mode: run one tick and exit")
    ap.add_argument("--tick-seconds", type=int, default=300,
                    help="strategy evaluation cadence (seconds)")
    ap.add_argument("--heartbeat-seconds", type=int, default=30,
                    help="lightweight health-heartbeat cadence, decoupled from --tick-seconds")
    ap.add_argument("--form4-source", choices=["parquet", "insider"], default="parquet")
    ap.add_argument("--status-path", default="")
    ap.add_argument("--as-of", default="", help="live --once: pin the tick date (dry-run only)")
    ap.add_argument("--live-lookback-days", type=int, default=45)
    ap.add_argument("--execution-scope", default="none",
                    choices=["none", "resolved-active-watchlist"],
                    help="live mode: enforce the V2 execution universe. "
                         "'resolved-active-watchlist' = ONLY issuers the authoritative "
                         "intelligence.service resolver marks SEC-covered active (POLLED). "
                         "'none' (default) = unrestricted -- offline replay / tests only.")
    ap.add_argument("--execution-scope-file", default="",
                    help="live mode: a text file of allowed issuer symbols (one per line); "
                         "overrides --execution-scope when given.")
    ap.add_argument("--enable-broad-discovery", action="store_true",
                    help="Task 131 Directive 4/5: additively union the frozen 626-name "
                         "Discovery Universe v1 into the execution scope (a no-op when "
                         "--execution-scope is 'none' -- already unrestricted) and tag "
                         "those symbols' alerts BROAD_DISCOVERY origin for the dispatcher's "
                         "own, separately-toggled (TALONX_DISPATCH_ENABLE_BROAD_DISCOVERY) "
                         "external-send gate. OFF by default -- the original watchlist "
                         "execution scope is completely unaffected unless explicitly set.")
    ap.add_argument("--broad-discovery-manifest",
                    default="talonx_ingest/intelligence/service/data/discovery_universe_v1_626.json",
                    help="path to the frozen Discovery Universe v1 symbol manifest")
    ap.add_argument("--deliver", action="store_true",
                    help="live mode: drain the durable V2 alert outbox each tick "
                         "through OfficialExternalRouter + the selected --transport")
    ap.add_argument("--transport", choices=["dryrun", "telegram"], default="dryrun",
                    help="delivery transport when --deliver is set: dryrun (HOLD, default) | "
                         "telegram (the real official Telegram sender; HOLDS unless "
                         "TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID are configured)")
    ap.add_argument("--release", action="store_true",
                    help="FIRST-RELEASE profile (live mode only): pricing mode is EXPLICITLY sip "
                         "(V2_RELEASE_PRICE_CONTRACT@1), paper only, Signal delivery required "
                         "(--deliver --transport telegram); refuses to start unless the read-only release "
                         "readiness gate is READY.  Never falls back to the stale csv default.")
    ap.add_argument("--pricing-mode", default=None,
                    choices=["csv", "composite-yf", "composite-iex", "sip"],
                    help="daily-bar source: csv (frozen snapshot, default; STALE prospectively) | "
                         "composite-yf / composite-iex (candidate/study only; refused when the "
                         "snapshot and tail are on different adjustment bases) | "
                         "sip (PQ-2B RELEASE provider: Alpaca SIP daily bars, adjustment=split, one "
                         "authoritative provider, fail closed; requires a QUALIFIED readiness check)")
    ap.add_argument("--form4-parquet",
                    default="results/task107a_form4_feasibility/_build/form4_open_market_txn.parquet")
    ap.add_argument("--bar-dir", action="append", default=[
        "results/task95g_broad_cross_sectional/_daily",
        "results/task107a_form4_feasibility/_prices",
    ])
    ap.add_argument("--symbols", default="", help="comma-separated filter (default: all)")
    ap.add_argument("--since", default="2019-06-03")
    ap.add_argument("--db", default="v2_lane.db")
    ap.add_argument("--out", default="results/task110_v2_integration/_replay_summary.json")
    args = ap.parse_args(argv)

    if args.mode == "status":
        from talonx_ops.operator_read import operator_snapshot
        import os
        status_path = Path(args.status_path or os.environ.get("TALONX_V2_STATUS_PATH")
                           or str(Path(args.db).parent / "v2_service_status.json"))
        try:
            status = json.loads(status_path.read_text())
        except (OSError, ValueError):
            status = {}
        print(json.dumps(operator_snapshot(args.db, status=status), indent=2, default=str))
        return 0

    from talonx_v2.release_gate import resolve_pricing_mode
    try:
        args.pricing_mode = resolve_pricing_mode(args.pricing_mode, release=args.release)
    except ValueError as exc:
        raise SystemExit(f"FATAL: {exc}") from exc
    if args.release and args.mode != "live":
        raise SystemExit("FATAL: --release is only valid with --mode live")
    cfg = V2Config(db_path=args.db)
    cfg.validate_frozen()
    store = V2Store(args.db, starting_cash=cfg.starting_cash_usd,
                    campaign_id=cfg.campaign_id, execution_mode=cfg.execution_mode,
                    strategy_version=V2_VERSION, per_position_allocation_usd=cfg.per_position_allocation_usd)

    if args.mode == "recover":
        summary = pipeline.paper.recover(store, as_of_session=date.today())
        print(json.dumps(summary, indent=2))
        return 0

    if args.mode == "live":
        import logging
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
        from talonx_v2.service import V2Service
        router = transport = None
        if args.deliver:
            # durable alert outbox is ALWAYS written; --deliver additionally drains
            # it each tick through the ONE official routing authority.  Default
            # transport is dry-run HOLD; --transport telegram uses the real
            # official sender (which itself HOLDS unless creds are configured).
            from talonx_ops.official_dispatch import OfficialExternalRouter
            from talonx_v2.delivery import DryRunTransport, OfficialTelegramTransport
            router = OfficialExternalRouter()
            transport = (OfficialTelegramTransport() if args.transport == "telegram"
                         else DryRunTransport())
            logging.getLogger("talonx_v2.run").info(
                "V2 delivery ENABLED -- transport=%s", transport.name)
        allowlist = None
        _scope_requested = bool(args.execution_scope_file) or args.execution_scope != "none"
        if args.execution_scope_file:
            allowlist = [ln.strip().upper() for ln in
                         Path(args.execution_scope_file).read_text().splitlines()
                         if ln.strip() and not ln.strip().startswith("#")]
        elif args.execution_scope == "resolved-active-watchlist":
            try:
                from talonx_ops.watchlist_coverage import build_coverage_map
                allowlist = sorted(c["symbol"] for c in build_coverage_map()["tickers"]
                                   if c["v2_collection_scope"] == "POLLED")
            except Exception as exc:  # noqa: BLE001
                raise SystemExit(
                    f"FATAL: --execution-scope resolved-active-watchlist could not be "
                    f"resolved ({exc!r}) -- refusing to start (fail closed, not unrestricted)."
                ) from exc
        # FAIL CLOSED: a requested scope that resolves to 0 issuers must NOT
        # become unrestricted execution.
        if _scope_requested and not allowlist:
            raise SystemExit(
                "FATAL: --execution-scope was requested but resolved to 0 allowed issuers "
                "-- refusing to start (fail closed, not unrestricted).")
        if allowlist is not None:
            logging.getLogger("talonx_v2.run").info(
                "V2 execution scope ENFORCED -- %d allowed issuers: %s",
                len(allowlist), ", ".join(allowlist))

        # Task 131 Directive 4/5: additive, opt-in broad-discovery union.
        broad_discovery_symbols: list[str] = []
        if args.enable_broad_discovery:
            mp = Path(args.broad_discovery_manifest)
            if not mp.is_file():
                raise SystemExit(
                    f"FATAL: --enable-broad-discovery requested but manifest not found "
                    f"at {mp} -- refusing to start (fail closed).")
            universe = sorted({s.strip().upper() for s in
                               json.loads(mp.read_text()).get("symbols", []) if s.strip()})
            if allowlist is not None:
                # union additively -- never SHRINKS the existing scope
                broad_discovery_symbols = sorted(set(universe) - set(allowlist))
                allowlist = sorted(set(allowlist) | set(universe))
            else:
                broad_discovery_symbols = universe  # allowlist already unrestricted (None)
            import os as _os
            logging.getLogger("talonx_v2.run").info(
                "V2 broad discovery ENABLED -- %d symbols added (manifest=%s); dispatch "
                "toggle TALONX_DISPATCH_ENABLE_BROAD_DISCOVERY=%s",
                len(broad_discovery_symbols), mp,
                "on" if _os.environ.get("TALONX_DISPATCH_ENABLE_BROAD_DISCOVERY") else "off")

        # PQ-2A: corporate-action evidence is MANDATORY for a live run.  Without
        # it a split during a hold would be booked as a trading loss/profit.
        from talonx_v2.corporate_actions import AlpacaCorporateActionSource, CorporateActionGuard
        _ca_src = AlpacaCorporateActionSource()
        if not (_ca_src._kid and _ca_src._sec):
            raise SystemExit(
                "FATAL: corporate-action source (Alpaca market-data credentials "
                "APCA_API_KEY_ID/APCA_API_SECRET_KEY) not configured -- refusing to start "
                "live (fail closed: splits cannot be accounted for).")
        ca_guard = CorporateActionGuard(_ca_src)

        if args.release:
            # FINAL ACCEPTANCE: the complete read-only release gate (provider QUALIFIED, contract + strategy
            # fingerprints, Signal/Sentinel configured + previously validated for the ACTIVE config, Lab OFF,
            # no active account block, ledger reconciles).  Nothing is sent; no secret is printed.
            from talonx_v2.release_gate import evaluate_release_readiness
            _gate = evaluate_release_readiness(db_path=args.db, pricing_mode=args.pricing_mode,
                                               deliver=args.deliver, transport=args.transport)
            if _gate.status != "READY":
                raise SystemExit("FATAL: release readiness gate NOT_READY -- refusing to start: "
                                 + "; ".join(f"{c.name}: {c.detail}" for c in _gate.failed))
            logging.getLogger("talonx_v2.run").info("V2 release readiness gate READY (%d checks)", len(_gate.checks))
        # PQ-2B: the release provider is selected EXPLICITLY (never implicitly) and only starts when a
        # bounded, read-only readiness check reaches QUALIFIED (configured -> reachable -> entitled ->
        # split-only basis honoured).  Env vars merely existing is NOT enough.
        if args.pricing_mode == "sip":
            from talonx_v2.provider_contract import check_readiness
            _rd = check_readiness()
            if not _rd.qualified:
                raise SystemExit(
                    f"FATAL: --pricing-mode sip requested but the release provider is not QUALIFIED "
                    f"(level={_rd.level}; problems={_rd.problems}) -- refusing to start (fail closed).")
            logging.getLogger("talonx_v2.run").info(
                "V2 release provider QUALIFIED -- contract %s fingerprint %s",
                _rd.to_dict()["contract_id"], _rd.to_dict()["contract_fingerprint"])

        import os as _os
        ops_store = None
        if _os.environ.get("TALONX_NOTIFY_OPERATIONS_ENABLED", "0") == "1":
            from talonx_ops.notify.outbox import NotifyStore
            ops_store = NotifyStore(_os.environ.get("TALONX_NOTIFY_DB_PATH", "notifications.db"))
        svc = V2Service(
            config=cfg, bar_dirs=[Path(p) for p in args.bar_dir],
            form4_kind=args.form4_source, form4_parquet=args.form4_parquet,
            status_path=args.status_path or None,
            since=None, live_lookback_days=args.live_lookback_days,
            execution_allowlist=allowlist,
            pricing_mode=args.pricing_mode,
            router=router, transport=transport, deliver=args.deliver,
            broad_discovery_symbols=broad_discovery_symbols,
            ops_notify_store=ops_store,
            corporate_actions=ca_guard,
            release_mode=args.release,
        )
        if args.once and args.as_of:
            st = svc.tick(as_of=date.fromisoformat(args.as_of))
            print(json.dumps(st, indent=2, default=str))
            return 0
        return svc.run(once=args.once, tick_seconds=args.tick_seconds,
                       heartbeat_seconds=args.heartbeat_seconds)

    syms = {s.strip().upper() for s in args.symbols.split(",") if s.strip()} or None
    records = form4_source.from_research_parquet(
        args.form4_parquet, symbols=syms,
        since=date.fromisoformat(args.since) if args.since else None,
    )
    bars_lookup, price_lookup = _bar_dir_lookup([Path(p) for p in args.bar_dir])
    res = pipeline.run_replay(records, store=store, bars_lookup=bars_lookup,
                              price_lookup=price_lookup, config=cfg)

    out = {
        "mode": "replay", "records": len(records),
        "episodes_detected": res.episodes_detected,
        "signals_built": res.signals_built,
        "entries": len(res.entries), "exits": len(res.exits),
        "skipped": len(res.skipped),
        "realized_pnl_usd": round(sum(e["realized_pnl_usd"] for e in res.exits), 2),
        "sample_entries": res.entries[:5],
        "sample_exits": res.exits[:5],
        "skip_reasons": _tally(res.skipped),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, default=str))
    print(json.dumps(out, indent=2, default=str)[:3000])
    return 0


def _tally(skips: list[dict]) -> dict:
    t: dict[str, int] = {}
    for s in skips:
        t[s["reason"]] = t.get(s["reason"], 0) + 1
    return dict(sorted(t.items(), key=lambda kv: -kv[1]))


if __name__ == "__main__":
    sys.exit(main())
