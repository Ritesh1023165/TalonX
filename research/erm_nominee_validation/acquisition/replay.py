"""Recorded-response REPLAY of the frozen DEVELOPMENT evidence through the PRODUCTION acquirer.

ReplayTransport answers provider requests from archived development bytes ONLY (no network):
  alpaca_bars  Phase D pages (_archive/alpaca, _archive/alpaca_diag), addressed by (adjustment, symbol batch, start,
               end, page_token) from the frozen bar manifests; the token chain is the archived next_page_token
  alpaca_meta  corporate actions: the archived parsed rows (_renames_2019_2023.json, _mergers_2019_2023.json,
               _archive/alpaca_meta_renames_post2023.json, audit _alpaca_v2 ETF cash-dividend pages) served per
               request by process_date (ETF: ex_date) inside [start, end] and the requested types -- RECONSTRUCTED
               responses (the raw pages were not archived; rows and fields are the archived ones)
               assets: RECONSTRUCTED from candidates.json (source-A symbols + their archived names; the raw asset list
               was not archived)
  sec          by archive file name in _archive/sec, audit _sec_pit, audit _sec_v2 (authoritative-archive rule of the
               frozen phase_d.Sec)
  github       S&P listing RECONSTRUCTED from the local point-in-time file (as-of = its last row date) + that file
A request with no archived answer raises ReplayMiss (a ConnectionError): the acquirer records it as
TRANSPORT_OR_PROVIDER_FAILURE and stops -- a miss is never an absence or an empty result.
"""
from __future__ import annotations

import csv
import gzip
import json
from pathlib import Path

from research.erm_nominee_validation.acquisition.transport import Request, Response

ERM = Path(r"C:\workspace\TalonX-erm\results\event_response_map_v1")
AUDIT = Path(r"C:\workspace\TalonX-erm-audit\results\erm_nominee_audit")
PIT = Path("C:/workspace/TalonX/results/task95g_broad_cross_sectional/_fja05680_pit.csv")
SEC_DIRS = (ERM / "_archive/sec", AUDIT / "_sec_pit", AUDIT / "_sec_v2")
TYPE_KEY = {"name_change": "name_changes", "cash_merger": "cash_mergers", "stock_merger": "stock_mergers",
            "stock_and_cash_merger": "stock_and_cash_mergers", "cash_dividend": "cash_dividends"}


class ReplayMiss(ConnectionError):
    pass


class ReplayTransport:
    def __init__(self, erm: Path = ERM, audit: Path = AUDIT, pit: Path = PIT):
        self.erm, self.audit, self.pit = erm, audit, pit
        self.served: list = []
        self._bars = None
        self._ca = None

    # -------------------------------------------------------------------------------------------- bars
    def _bar_index(self):
        idx = {}
        for d in (self.erm / "_archive/alpaca", self.erm / "_archive/alpaca_diag"):
            man = json.loads((d / "manifest.json").read_text())
            prev_tok = {}
            for f in man["files"]:                                   # pages are listed in request order
                k = (f["adjustment"], tuple(f["symbols"]), f["start"], f["end"])
                body_path = d / f["file"]
                idx[k + (prev_tok.get(k),)] = body_path
                prev_tok[k] = json.loads(gzip.decompress(body_path.read_bytes())).get("next_page_token")
        return idx

    def _bars_fetch(self, p: dict) -> bytes:
        if self._bars is None:
            self._bars = self._bar_index()
        k = (p["adjustment"], tuple(p["symbols"].split(",")), p["start"], p["end"], p.get("page_token"))
        f = self._bars.get(k)
        if f is None:
            raise ReplayMiss(f"no archived bar page for {p['adjustment']} {k[1][:3]}... ({len(k[1])} syms) "
                             f"{p['start']}..{p['end']} token={bool(p.get('page_token'))}")
        return gzip.decompress(f.read_bytes())

    # -------------------------------------------------------------------------------------------- corporate actions
    def _ca_rows(self):
        rows = []
        for r in json.loads((self.erm / "_renames_2019_2023.json").read_text()):
            rows.append((r["_type"], r.get("process_date"), r))
        for r in json.loads((self.erm / "_mergers_2019_2023.json").read_text()):
            rows.append((r["_type"], r.get("process_date"), r))
        for r in json.loads((self.erm / "_archive/alpaca_meta_renames_post2023.json").read_text()):
            rows.append(("name_changes", r.get("process_date"), r))
        for p in sorted((self.audit / "_alpaca_v2").glob("etf_cash_dividends_*_*.json")):
            for typ, rs in (json.loads(p.read_text()).get("corporate_actions") or {}).items():
                for r in rs:
                    rows.append((typ, r.get("ex_date"), r))
        return rows

    def _ca_fetch(self, p: dict) -> bytes:
        if self._ca is None:
            self._ca = self._ca_rows()
        want = {TYPE_KEY[t] for t in p["types"].split(",")}
        syms = set(p["symbols"].split(",")) if p.get("symbols") else None
        out: dict = {}
        for typ, d, r in self._ca:
            if typ in want and d and p["start"] <= d <= p["end"] and (syms is None or r.get("symbol") in syms):
                out.setdefault(typ, []).append({k: v for k, v in r.items() if k != "_type"})
        if p.get("page_token"):
            raise ReplayMiss("replay serves corporate actions in one page")
        return json.dumps({"corporate_actions": out, "next_page_token": None}).encode()

    def _assets(self, status: str) -> bytes:
        if status != "active":
            return b"[]"
        cand = json.loads((self.erm / "candidates.json").read_text())
        names = cand.get("names", {})
        out = [{"symbol": s, "exchange": "NYSE", "name": names.get(s, ""), "status": "active", "class": "us_equity"}
               for s, src in sorted(cand["symbols"].items()) if "A" in src]
        return json.dumps(out).encode()

    # -------------------------------------------------------------------------------------------- sec / github
    def _sec(self, url: str) -> bytes:
        tail = url.rsplit("/", 1)[-1]
        if "/submissions/" in url:
            name = "sub_" + tail
        elif url.endswith("-index-headers.html"):
            name = "hdr_" + tail.replace("-index-headers.html", ".html")
        elif "/full-index/" in url:
            q = url.split("/full-index/")[1].rsplit("/", 1)[0]
            name = "master_" + q.replace("/", "_") + ".idx"
        else:                                                   # form345 zips, company_tickers, cik-lookup
            name = tail
        for d in SEC_DIRS:
            p = d / (name + ".gz")
            if p.exists():
                return gzip.decompress(p.read_bytes())
        raise ReplayMiss(f"no archived SEC file {name}")

    def _sp_asof(self) -> str:
        last = None
        with open(self.pit, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                last = r["date"][:10]
        return last

    def fetch(self, r: Request) -> Response:
        p = dict(r.params)
        if r.provider == "alpaca_bars":
            body = self._bars_fetch(p)
        elif r.provider == "alpaca_meta" and r.url.endswith("/v2/assets"):
            body = self._assets(p["status"])
        elif r.provider == "alpaca_meta":
            body = self._ca_fetch(p)
        elif r.provider == "sec":
            body = self._sec(r.url)
        elif r.provider == "github" and r.url.endswith("/contents"):
            y, m, d = self._sp_asof().split("-")
            body = json.dumps([{"name": f"S&P 500 Historical Components & Changes({m}-{d}-{y}).csv",
                                "download_url": "replay://sp500_pit.csv"}]).encode()
        elif r.provider == "github" and r.url == "replay://sp500_pit.csv":
            body = self.pit.read_bytes()
        else:
            raise ReplayMiss(f"unknown replay request {r.provider} {r.url}")
        self.served.append(r.key)
        return Response(200, body)

