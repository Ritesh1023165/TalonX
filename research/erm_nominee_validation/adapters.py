"""ERM nominee validation -- archive manifest, verified loader and PRODUCTION acquisition (fail-closed).

Archive layout (one directory per run): `archive/` holds every acquired input plus `ARCHIVE_MANIFEST.json`
({files: [{path, input, sha256, bytes}], required: [...], complete: bool}). Bars use the frozen Phase D layout
(`bars/manifest.json` + gz JSON pages, purposes RETURNS / ELIGIBILITY_ONLY) so the FROZEN data.load verifies them.

ProductionLoader: verifies EVERY file's sha256 against ARCHIVE_MANIFEST.json before parsing, then loads bars through
the frozen data.load with the guard's frame guard (LOAD layer), and every metadata file from local bytes only.
ProductionAcquirer: NOT IMPLEMENTED (named remaining gap). It checks the guard first (which refuses every protected
range today) and otherwise raises AcquisitionNotImplemented. There is no network code in this package.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from research.erm_nominee_validation import builder as B
from research.erm_nominee_validation.inventory import inventory

REQUIRED = ("bars", "candidates", "form345", "renames", "submissions", "master_idx", "filing_headers", "sp500_pit",
            "etf_cash_dividends")


class AcquisitionIncomplete(RuntimeError):
    pass


class AcquisitionNotImplemented(RuntimeError):
    pass


class InputHashMismatch(RuntimeError):
    pass


def sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def write_archive_manifest(archive: Path, inputs: dict[str, list[str]]) -> dict:
    """inputs: input name -> relative file paths (already written under archive/). Records sha256 of every file."""
    files = []
    for name, rels in sorted(inputs.items()):
        for rel in sorted(rels):
            p = archive / rel
            files.append({"path": rel, "input": name, "sha256": sha(p), "bytes": p.stat().st_size})
    present = {f["input"] for f in files}
    man = {"files": files, "required": list(REQUIRED), "missing": sorted(set(REQUIRED) - present),
           "complete": set(REQUIRED) <= present}
    B.atomic(archive / "ARCHIVE_MANIFEST.json", json.dumps(man, indent=1))
    return man


@dataclass
class Loaded:
    sessions: list
    archives: list            # [(tag, all_df, raw_df)]
    bench: dict               # ETF -> ALL frame
    meta: B.Meta
    bars_all: object          # concatenated ALL frame (stocks) for outcomes / diagnostics


class ProductionLoader:
    def __init__(self, guard, mapping_path: Path):
        self.guard, self.mapping_path = guard, Path(mapping_path)

    def load(self, archive: Path, cfg) -> Loaded:
        import pandas as pd
        from research.event_response_map_v1 import data as D, events as E
        man = json.loads((archive / "ARCHIVE_MANIFEST.json").read_text())
        if not man.get("complete"):
            raise AcquisitionIncomplete(f"archive incomplete: missing {man.get('missing')}")
        for f in man["files"]:                                        # verify BEFORE any parse
            if sha(archive / f["path"]) != f["sha256"]:
                raise InputHashMismatch(f"sha256 mismatch: {f['path']}")
        by = defaultdict(list)
        for f in man["files"]:
            by[f["input"]].append(archive / f["path"])
        fg = self.guard.frame_guard()
        a_all, _ = D.load(archive / "bars", purpose="RETURNS", guard=fg)          # frozen sha256 + LOAD guard
        a_raw, _ = D.load(archive / "bars", purpose="ELIGIBILITY_ONLY", guard=fg)
        sessions = sorted(a_all.loc[a_all["symbol"] == "SPY", "date"].unique())
        bench = {b: a_all[a_all["symbol"] == b] for b in D.BENCHMARKS if (a_all["symbol"] == b).any()}
        eq = a_all[~a_all["symbol"].isin(D.BENCHMARKS)]
        end = cfg.end.isoformat()
        cand = json.loads(by["candidates"][0].read_text())
        from research.event_response_map_v1 import identity as I
        renames = []
        for p in by["renames"]:
            renames += json.loads(p.read_text())
        f345 = defaultdict(list)
        for p in by["form345"]:
            B.f345_parse(gzip.decompress(p.read_bytes()), f345, end)
        f345 = {k: sorted(set(v)) for k, v in f345.items()}
        sp_rows = []
        for p in by["sp500_pit"]:
            with open(p, encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    sp_rows.append((r["date"], {t.strip().upper() for t in r["tickers"].split(",") if t.strip()}))
        sp_rows.sort(key=lambda x: x[0])
        from research.event_response_map_v1.instrument_filter import PERIODIC_FORMS
        periodic = defaultdict(set)
        for p in by["master_idx"]:
            for line in gzip.decompress(p.read_bytes()).decode("latin-1").splitlines():
                q = line.split("|")
                if len(q) == 5 and q[0].strip().isdigit() and q[2].strip() in PERIODIC_FORMS and q[3].strip() <= end:
                    periodic[q[0].strip().zfill(10)].add(q[3].strip())
        etf_div = defaultdict(list)
        for p in by["etf_cash_dividends"]:
            for r in json.loads(p.read_text()):
                etf_div[r["symbol"]].append(r["ex_date"])
        mapping = json.loads(self.mapping_path.read_text())["mapping"]
        sub_dirs = sorted({p.parent for p in by["submissions"]})
        hdr_dirs = sorted({p.parent for p in by["filing_headers"]})
        meta = B.Meta(names=cand.get("names", {}), frozen_cik=cand.get("identity_cik", {}),
                      edges=I.rename_edges(renames), f345=f345, sp_rows=sp_rows, periodic=periodic,
                      subs=B.subs_reader(sub_dirs, end), header=B.header_reader(hdr_dirs), etf_div=etf_div,
                      sic_to_etf=lambda x: E.sic_benchmark(x, mapping))
        return Loaded(sessions=sessions, archives=[("MAIN", eq, a_raw[~a_raw["symbol"].isin(D.BENCHMARKS)])],
                      bench=bench, meta=meta, bars_all=eq)


class ProductionAcquirer:
    """REMAINING GAP after approval: window candidate rebuild ([MAP->W] sources A-D), R1 download scope, metadata
    acquisition (Form 3/4/5 2018Q1..window end, renames to the download date incl. the Task75 windows, submissions,
    master.idx, per-event filing headers, S&P lists, ETF cash dividends) and bars via the frozen data.Downloader with
    window start/end. Guard first: every protected range is refused today."""

    def __init__(self, guard):
        self.guard = guard

    def acquire(self, cfg, archive: Path) -> dict:
        for item in inventory(cfg):
            a = item["coverage_from"]
            b = item["coverage_to"]
            from datetime import date
            a_ = date.fromisoformat(a) if a[0].isdigit() else date(1993, 1, 1)
            b_ = date.fromisoformat(b) if b[0].isdigit() else cfg.end
            self.guard.check_acquisition(a_, b_, item["input"])
        raise AcquisitionNotImplemented("production acquisition adapters are not implemented (r9 §10 remaining gap)")
