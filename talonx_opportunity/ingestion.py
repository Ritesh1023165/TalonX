"""
DATA_INGESTION component -- the only research-lane process that pulls market bars. Single writer of market.db.

Per cycle (default every 60 s while a usable phase is open):
  * probe the current phase's capability (every ``probe_every_s``); a failed probe marks that phase UNAVAILABLE
    for discovery (fail closed) without affecting any other component;
  * once per trading window: snapshot the broad universe and cache daily history up to the reference session;
  * fold NEW 1-minute SIP bars (exclusive end, per-symbol watermark) into window-to-date aggregates. A symbol whose
    batch failed keeps its watermark and is reported INCOMPLETE -- never "no prints" -- and is re-requested next
    cycle. Bars are never fabricated and never taken from a different feed.

Consistent snapshots (2026-10-01, P0): every cycle publishes ONE generation. Its aggregates, its universe state (the
DTU active set it used) and its as_of are written in ONE transaction, together with the snapshot_generations row; the
generation is visible to readers only after that commit. ``read_state`` reads one committed generation inside one
read transaction and serves a DTU active set only if it is the one recorded for that generation.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from talonx_opportunity import capabilities as C
from talonx_opportunity.aggregates import SymbolAggregate
from talonx_opportunity.db import REPO_ROOT, connect, iso, j, root_dir, unj, utcnow
from talonx_opportunity.phases import CLOSED, phase_at, trading_window
from talonx_premarket.alpaca_data import iso as aiso, data_as_of

SCHEMA = """
CREATE TABLE IF NOT EXISTS universe (window_id TEXT PRIMARY KEY, built_utc TEXT, source TEXT, members_json TEXT,
    eligible INTEGER, total INTEGER);
CREATE TABLE IF NOT EXISTS daily (window_id TEXT, symbol TEXT, bars_json TEXT, PRIMARY KEY (window_id, symbol));
CREATE TABLE IF NOT EXISTS daily_state (window_id TEXT PRIMARY KEY, fetched_utc TEXT, failed_json TEXT);
CREATE TABLE IF NOT EXISTS aggregates (window_id TEXT, symbol TEXT, agg_json TEXT, watermark_utc TEXT,
    PRIMARY KEY (window_id, symbol));
CREATE TABLE IF NOT EXISTS ingestion_state (window_id TEXT PRIMARY KEY, as_of_utc TEXT, cycle_utc TEXT, phase TEXT,
    symbols INTEGER, incomplete_json TEXT, requests INTEGER, errors_json TEXT);
CREATE TABLE IF NOT EXISTS cycles (id INTEGER PRIMARY KEY AUTOINCREMENT, at_utc TEXT, window_id TEXT, phase TEXT,
    as_of_utc TEXT, fetched_symbols INTEGER, bars INTEGER, failed_symbols INTEGER, batches INTEGER,
    failed_batches INTEGER, retried_batches INTEGER, duration_s REAL, note TEXT);
CREATE TABLE IF NOT EXISTS probes (id INTEGER PRIMARY KEY AUTOINCREMENT, at_utc TEXT, phase TEXT, feed TEXT,
    ok INTEGER, detail TEXT);
CREATE TABLE IF NOT EXISTS snapshot_generations (window_id TEXT, generation INTEGER, as_of_utc TEXT, cycle_utc TEXT,
    dtu_cycle_utc TEXT, symbols_changed INTEGER, PRIMARY KEY (window_id, generation));
"""
# additive columns (existing stores are migrated in place; old rows read as generation NULL)
_ADDED_COLUMNS = {"ingestion_state": "generation", "aggregates": "generation"}

UNIVERSE_MAX_AGE_H = 30.0


def market_db(root=None) -> Path:
    return root_dir(root) / "market.db"


class Ingestion:
    def __init__(self, *, data=None, root=None, cycle_s: float = 60.0, probe_every_s: float = 900.0,
                 clock=None, universe_loader=None, dtu_mode: str | None = None, dtu=None):
        from talonx_opportunity import universe_tiers as U
        self.dtu_mode = dtu_mode or U.mode()
        self.dtu_policy = dtu.policy if dtu is not None else U.policy_from_env()
        self._dtu, self.dtu_last, self.dtu_prep = dtu, None, None
        self._dtu_cache: tuple[str, list[dict], dict] | None = None
        self.root = root
        self.con = connect(market_db(root), schema=SCHEMA)
        for table, col in _ADDED_COLUMNS.items():
            if col not in {r[1] for r in self.con.execute(f"PRAGMA table_info({table})")}:
                self.con.execute(f"ALTER TABLE {table} ADD COLUMN {col} INTEGER")
        self.con.commit()
        self.published_generation: int | None = None
        self._data = data
        self.cycle_s, self.probe_every_s = cycle_s, probe_every_s
        self.clock = clock or utcnow
        self.universe_loader = universe_loader or self._load_universe
        self._aggs: dict[str, SymbolAggregate] = {}
        self._wm: dict[str, datetime] = {}
        self._window_id: str | None = None
        self._last_probe: dict[str, float] = {}
        self.last_note = ""

    @property
    def data(self):
        if self._data is None:
            from talonx_premarket import __main__ as M
            from talonx_premarket.alpaca_data import AlpacaData, RateLimiter
            M._env()
            base = M._data()
            # own limiter: ingestion 120/min + outcome tracking 40/min stays under Alpaca's 200/min
            self._data = AlpacaData(key_id=base._headers["APCA-API-KEY-ID"],
                                    secret=base._headers["APCA-API-SECRET-KEY"], limiter=RateLimiter(120))
        return self._data

    # -- universe ------------------------------------------------------------------------------------------------
    def _load_universe(self) -> tuple[list[dict], str]:
        from talonx_premarket.universe import build_universe, load, save
        p = REPO_ROOT / "results" / "premarket_research" / "universe.json"
        if p.exists() and (time.time() - p.stat().st_mtime) < UNIVERSE_MAX_AGE_H * 3600:
            members = load(p)
            src = f"{p.name} (age {(time.time() - p.stat().st_mtime) / 3600:.1f}h)"
        else:
            ct = Path.home() / ".talonx" / "intelligence" / "company_tickers.json"
            members = build_universe(self.data.assets(), json.loads(ct.read_text(encoding="utf-8")))
            save(members, p)
            src = "rebuilt from Alpaca assets x SEC company_tickers"
        return [m.__dict__ for m in members], src

    def _ensure_window(self, w) -> None:
        if self._window_id == w.window_id:
            return
        row = self.con.execute("SELECT * FROM universe WHERE window_id=?", (w.window_id,)).fetchone()
        if row is None:
            members, src = self.universe_loader()
            elig = sum(1 for m in members if m.get("status") == "ELIGIBLE")
            self.con.execute("INSERT INTO universe VALUES (?,?,?,?,?,?)",
                             (w.window_id, iso(self.clock()), src, j(members), elig, len(members)))
            self.con.commit()
        self._aggs, self._wm = {}, {}
        for r in self.con.execute("SELECT * FROM aggregates WHERE window_id=?", (w.window_id,)):
            self._aggs[r["symbol"]] = SymbolAggregate(**unj(r["agg_json"]))
            self._wm[r["symbol"]] = datetime.fromisoformat(r["watermark_utc"])
        self._window_id = w.window_id

    def eligible(self, window_id: str) -> list[str]:
        row = self.con.execute("SELECT members_json FROM universe WHERE window_id=?", (window_id,)).fetchone()
        return sorted(m["symbol"] for m in unj(row["members_json"], []) if m.get("status") == "ELIGIBLE") if row else []

    # -- probes / daily ------------------------------------------------------------------------------------------
    def probe(self, phase: str, now: datetime) -> dict:
        cap = C.STATIC_CAPABILITIES.get(phase)
        if cap is None or cap.availability != C.AVAILABLE:
            return {"ok": False, "detail": f"static capability {cap.availability if cap else 'NONE'}"}
        end = data_as_of(now)
        try:
            res = self.data.bars_ex(["SPY"], timeframe="1Min", start=end - timedelta(minutes=30),
                                    end=end - timedelta(seconds=1), attempts=1)
            ok = res.complete
            detail = "ok" if ok else (list(getattr(self.data, "errors", [])) or ["fetch failed"])[-1][:300]
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"{type(exc).__name__}: {exc}"[:300]
        self.con.execute("INSERT INTO probes(at_utc, phase, feed, ok, detail) VALUES (?,?,?,?,?)",
                         (iso(now), phase, cap.feed, int(ok), detail))
        self.con.commit()
        return {"ok": ok, "detail": detail}

    def _ensure_daily(self, w, symbols: list[str], now: datetime) -> None:
        st = self.con.execute("SELECT * FROM daily_state WHERE window_id=?", (w.window_id,)).fetchone()
        pending = set(unj(st["failed_json"], [])) if st else set(symbols)
        if st and not pending:
            return
        start = datetime.combine(w.reference_session - timedelta(days=45), datetime.min.time(), timezone.utc)
        end = min(datetime.combine(w.session, datetime.min.time(), timezone.utc), data_as_of(now)) \
            - timedelta(seconds=1)
        res = self.data.bars_ex(sorted(pending), timeframe="1Day", start=start, end=end)
        with self.con:
            for s in sorted(pending - res.failed):
                self.con.execute("INSERT OR REPLACE INTO daily VALUES (?,?,?)",
                                 (w.window_id, s, j(res.bars.get(s, []))))
            self.con.execute("INSERT OR REPLACE INTO daily_state VALUES (?,?,?)",
                             (w.window_id, iso(now), j(sorted(res.failed))))

    # -- one cycle -------------------------------------------------------------------------------------------------
    def tick(self) -> float:
        t0 = time.monotonic()
        now = self.clock()
        phase, w = phase_at(now)
        if w is None or phase == CLOSED:
            self.last_note = "CLOSED: no trading window"
            return 300.0
        self._ensure_window(w)
        last = self._last_probe.get(phase, 0.0)
        probe = None
        if time.monotonic() - last >= self.probe_every_s or not last:
            probe = self.probe(phase, now)
            self._last_probe[phase] = time.monotonic()
        cap = C.effective_capability(phase, probe or self.latest_probe(phase))
        from talonx_ops.operator_control.gates import effective_symbols     # identity unless ACTIVE (operator control)
        symbols = effective_symbols(self.eligible(w.window_id))
        self._ensure_daily(w, symbols, now)
        from talonx_opportunity import universe_tiers as U
        if self.dtu_mode == U.ACTIVE and U.has_live_floor(self.dtu_policy):
            self._dtu_prepare(w, symbols, now)          # D-1 inputs + snapshot + report at window start (any phase)
        if not cap.usable_for_discovery:
            self.last_note = f"{phase}: {cap.availability} ({cap.evidence[:80]})"
            self._write_cycle(w, phase, None, 0, 0, None, t0, self.last_note)
            return 300.0
        if self.dtu_mode == U.ACTIVE:                   # DTU: the effective active set, BEFORE any fetch batch is built
            symbols = self._dtu_symbols(w, symbols, now)
        as_of = data_as_of(now)
        bounds_start = w.premarket_start_utc          # SIP extended session starts 04:00 ET (no SIP overnight)
        end = min(as_of, w.after_hours_end_utc)
        groups: dict[datetime, list[str]] = {}
        for s in symbols:
            wm = self._wm.get(s, bounds_start)
            if wm < end:
                groups.setdefault(wm, []).append(s)
        failed: set[str] = set()
        agg_stats = {"batches": 0, "failed_batches": 0, "retried_batches": 0}
        nbars = 0
        changed: set[str] = set()
        for start, syms in sorted(groups.items()):
            res = self.data.bars_ex(syms, timeframe="1Min", start=start, end=end - timedelta(seconds=1))
            for k in agg_stats:
                agg_stats[k] += getattr(res, k)
            for s in syms:
                if s in res.failed:
                    failed.add(s)
                    continue
                rows = sorted(res.bars.get(s, []), key=lambda r: r["t"])
                if rows:
                    a = self._aggs.setdefault(s, SymbolAggregate(s, w.window_id))
                    nbars += a.add(rows)
                self._wm[s] = end
                changed.add(s)
        incomplete = sorted(s for s in symbols if self._wm.get(s, bounds_start) < end)
        dtu = self._dtu if self.dtu_mode == U.ACTIVE else None
        # ONE generation: aggregates + universe state (DTU active set) + as_of in ONE transaction, published on commit
        try:
            with self.con:
                if not self.con.in_transaction:
                    self.con.execute("BEGIN IMMEDIATE")      # write lock before the generation number is taken
                gen = self.con.execute("SELECT COALESCE(MAX(generation), 0) + 1 FROM snapshot_generations "
                                       "WHERE window_id=?", (w.window_id,)).fetchone()[0]
                dtu_cycle = dtu.write_pending() if dtu is not None else None
                for s in changed:
                    a = self._aggs.get(s)
                    self.con.execute("INSERT OR REPLACE INTO aggregates (window_id, symbol, agg_json, watermark_utc, "
                                     "generation) VALUES (?,?,?,?,?)",
                                     (w.window_id, s,
                                      j(a.as_dict() if a else SymbolAggregate(s, w.window_id).as_dict()),
                                      self._wm[s].isoformat(), gen))
                self.con.execute("INSERT OR REPLACE INTO ingestion_state (window_id, as_of_utc, cycle_utc, phase, "
                                 "symbols, incomplete_json, requests, errors_json, generation) "
                                 "VALUES (?,?,?,?,?,?,?,?,?)",
                                 (w.window_id, end.isoformat(), iso(now), phase, len(symbols), j(incomplete),
                                  getattr(self.data, "requests", 0), j(list(getattr(self.data, "errors", []))[-5:]),
                                  gen))
                self.con.execute("INSERT INTO snapshot_generations VALUES (?,?,?,?,?,?)",
                                 (w.window_id, gen, end.isoformat(), iso(now), dtu_cycle, len(changed)))
        except BaseException:
            if dtu is not None:
                dtu.discard_pending()
            raise
        if dtu is not None:
            dtu.confirm_pending()
        self.published_generation = gen                   # published only after the commit
        self.last_note = f"{phase}: as_of {aiso(end)} bars+{nbars} incomplete {len(incomplete)}"
        self._write_cycle(w, phase, end, len(changed), nbars, (len(failed), agg_stats), t0, self.last_note)
        return self.cycle_s

    def _dtu_init(self, w) -> None:
        from talonx_opportunity import universe_tiers as U
        if self._dtu is None:
            from talonx_premarket import __main__ as M
            M._env()
            self._dtu = U.DTU(self.con, root=self.root, policy=self.dtu_policy, headers=dict(self.data._headers),
                              sec_ua=M._sec()._ua, clock=self.clock, limiter=getattr(self.data, "limiter", None))
        if self._dtu_cache is None or self._dtu_cache[0] != w.window_id:
            row = self.con.execute("SELECT members_json FROM universe WHERE window_id=?", (w.window_id,)).fetchone()
            daily = {r["symbol"]: unj(r["bars_json"], []) for r in
                     self.con.execute("SELECT symbol, bars_json FROM daily WHERE window_id=?", (w.window_id,))}
            self._dtu_cache = (w.window_id, unj(row["members_json"], []) if row else [], daily)

    def _dtu_prepare(self, w, symbols: list[str], now: datetime) -> None:
        """Live-floor policy: as-traded D-1 inputs, the window snapshot and its local report as soon as the window
        opens (before PREMARKET). Builds only once the inputs are complete; the per-cycle resolution builds anyway
        (explicit LIVE_DATA_FETCH_FAILED reasons) if a fetch is still failing then. Errors never stop ingestion."""
        from talonx_opportunity import universe_tiers as U
        try:
            st = self.con.execute("SELECT 1 FROM daily_state WHERE window_id=? AND failed_json='[]'",
                                  (w.window_id,)).fetchone()
            if st is None:
                return                                   # V1 reference data first (same window, same members)
            self._dtu_init(w)
            live = self._dtu.ensure_live_daily(w, symbols, now)
            if not live.get("complete"):
                self.dtu_prep = {"window_id": w.window_id, "live_daily": live}
                return
            self._dtu.ensure_snapshot(w, self._dtu_cache[1], self._dtu_cache[2])
            out = U.report_dir(self.root, w.window_id)
            if not (out / f"universe_{w.window_id}.json").exists():
                from talonx_premarket import __main__ as M
                rep = self._dtu.report(w, self._dtu_cache[1], self._dtu_cache[2], v2_scope=set(M._v2_scope(None)))
                self.dtu_prep = {"window_id": w.window_id, "report": U.write_report(rep, out),
                                 "counts": {k: rep["counts"][k] for k in ("qualifying", "core", "removed")},
                                 "reconciled": rep["reconciled"]}
        except Exception as exc:  # noqa: BLE001 -- recorded; the per-cycle resolution keeps its own fail-safe
            self.dtu_prep = {"window_id": w.window_id, "error": f"{type(exc).__name__}: {str(exc)[:200]}"}

    def _dtu_symbols(self, w, symbols: list[str], now: datetime) -> list[str]:
        from talonx_ops.operator_control.gates import _state
        self._dtu_init(w)
        st = _state()                                   # operator overrides apply only in mutation mode ACTIVE
        added, removed, excluded = st if st is not None else (set(), set(), set())
        try:
            from talonx_premarket import __main__ as M
            v2 = set(M._v2_scope(None))
        except Exception:  # noqa: BLE001 -- unknown V2 scope: fall back safely (full universe) below
            v2 = None
        if v2 is None:
            self.dtu_last = {"fallback": "V2_SCOPE_UNAVAILABLE", "effective_active": len(symbols)}
            return symbols
        fetch, self.dtu_last = self._dtu.active_symbols(
            w, symbols, members=self._dtu_cache[1], daily=self._dtu_cache[2], sip_as_of=data_as_of(now),
            operator_added=set(added), operator_excluded=set(excluded) | set(removed), v2_forced=v2,
            defer_write=True)                         # written in the cycle's generation transaction (P0)
        return fetch

    def latest_probe(self, phase: str) -> dict | None:
        r = self.con.execute("SELECT * FROM probes WHERE phase=? ORDER BY id DESC LIMIT 1", (phase,)).fetchone()
        return {"ok": bool(r["ok"]), "at_utc": r["at_utc"], "detail": r["detail"]} if r else None

    def _write_cycle(self, w, phase, as_of, nsym, nbars, fails, t0, note) -> None:
        nf, st = fails if fails else (0, {"batches": 0, "failed_batches": 0, "retried_batches": 0})
        self.con.execute("INSERT INTO cycles(at_utc, window_id, phase, as_of_utc, fetched_symbols, bars, "
                         "failed_symbols, batches, failed_batches, retried_batches, duration_s, note) "
                         "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (iso(self.clock()), w.window_id, phase, as_of.isoformat() if as_of else None, nsym, nbars,
                          nf, st["batches"], st["failed_batches"], st["retried_batches"],
                          round(time.monotonic() - t0, 2), note))
        self.con.commit()

    def detail(self) -> dict:
        return {"window_id": self._window_id, "note": self.last_note,
                "requests": getattr(self._data, "requests", 0) if self._data else 0,
                "dtu_mode": self.dtu_mode, "dtu_policy": self.dtu_policy.version, "dtu": self.dtu_last,
                "dtu_prep": self.dtu_prep}


# -- read-only accessors used by other components -------------------------------------------------------------
def read_state(root, window_id: str) -> dict:
    """ONE committed generation, read inside ONE read transaction (WAL snapshot): as_of, aggregates, universe and
    DTU active set can never come from different ingestion cycles. The DTU active set is served only if it is the
    one recorded for this generation (else None -> discovery's existing fail-safe full-universe path)."""
    con = connect(market_db(root), readonly=True)
    try:
        con.execute("BEGIN")                              # deferred: the snapshot is pinned at the first SELECT
        st = con.execute("SELECT * FROM ingestion_state WHERE window_id=?", (window_id,)).fetchone()
        uni = con.execute("SELECT * FROM universe WHERE window_id=?", (window_id,)).fetchone()
        daily = {r["symbol"]: unj(r["bars_json"], []) for r in
                 con.execute("SELECT symbol, bars_json FROM daily WHERE window_id=?", (window_id,))}
        aggs = {r["symbol"]: SymbolAggregate(**unj(r["agg_json"])) for r in
                con.execute("SELECT symbol, agg_json FROM aggregates WHERE window_id=?", (window_id,))}
        probes = {}
        for r in con.execute("SELECT * FROM probes ORDER BY id"):
            probes[r["phase"]] = {"ok": bool(r["ok"]), "at_utc": r["at_utc"], "detail": r["detail"]}
        from talonx_opportunity.universe_tiers import latest_active
        dtu = latest_active(con, window_id)
        gen = st["generation"] if st is not None and "generation" in st.keys() else None
        meta = None
        if gen is not None:
            meta = con.execute("SELECT * FROM snapshot_generations WHERE window_id=? AND generation=?",
                               (window_id, gen)).fetchone()
            if dtu is not None and (meta is None or meta["dtu_cycle_utc"] != dtu["cycle_utc"]):
                dtu = None                                # not this generation's universe state: never mix
        return {"state": dict(st) if st else None, "members": unj(uni["members_json"], []) if uni else [],
                "daily": daily, "aggs": aggs, "probes": probes, "dtu": dtu, "generation": gen}
    finally:
        try:
            con.rollback()                                # end the read transaction (nothing to commit)
        finally:
            con.close()


def main(argv=None) -> int:
    from talonx_opportunity.runtime import run_component
    root = os.environ.get("TALONX_OPP_ROOT")
    ing = Ingestion(root=root)
    from talonx_opportunity import universe_tiers as U
    fps = {} if ing.dtu_mode == U.OFF else {"DTU": ing.dtu_policy.fingerprint()}   # OFF keeps today's fingerprints
    run_component("ingestion", tick=ing.tick, config_fps=fps, root=root, detail=ing.detail)
    return 0
