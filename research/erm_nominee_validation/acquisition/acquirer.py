"""ERM nominee PRODUCTION acquirer (staged). Replaces the fail-closed stub.

Stages (deterministic order; nothing after S3 can widen the request set beyond what the frozen rules need):
  S1 BASE       current asset list; in-period corporate actions (renames, mergers); identity-only renames
                (period-specific ranges); SEC current reference files; Form 3/4/5 quarterly sets (identity: period
                quarters; V2.1 evidence: 2018Q1..period end); master.idx period quarters; S&P list with explicit
                as-of coverage >= scope end
  S2 SCOPE      candidates A-D and R3 identity / R1a / R1b (scope.build_scope) -> R1-kept and R1a-removed symbols;
                submissions (main + pages overlapping the filing window) and R7 filing headers fetched on demand
  S3 BARS       frozen data.Downloader, two groups exactly as Phase D: KEPT (RETURNS kept + benchmarks, ELIGIBILITY
                kept) and R1A_REMOVED (RETURNS, ELIGIBILITY); bars_from (warm-up) .. events_to
  S4 EVENTS     candidate-event DISCOVERY: gap days and L1 eligibility from the archived bars (frozen events.gap_events
                / universe.eligibility) + V2.1 identity at D. Dates and identities only -- NO forward return, no exit
                price is read for any purpose here
  S5 EVIDENCE   submissions of the verified issuers; point-in-time filing headers (latest company filing <= D)
  S6 ETF        ETF cash-dividend records (OPTIONAL; descriptive subset only)
  S7 COMPLETE   every REQUIRED request must be RETRIEVED_USABLE or (where defined) RETRIEVED_LEGITIMATELY_ABSENT;
                any INSUFFICIENT / TRANSPORT / MALFORMED required request -> AcquisitionFailure (stop before build)
  S8 MATERIAL   loader-format files + acquisition_status.json + ARCHIVE_MANIFEST.json (written last)
Every request: guard.check_acquisition(content_from, content_to, category) BEFORE the request is built; then the
transport; then classification into an explicit evidence state recorded in the ledger. Resume: requests already
USABLE/ABSENT are not re-requested; bar groups are redone only if incomplete (partial group moved aside, preserved).
"""
from __future__ import annotations

import csv
import io
import json
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from research.erm_nominee_validation import builder as B
from research.erm_nominee_validation.acquisition import states as S
from research.erm_nominee_validation.acquisition.period import (BROAD_ENDPOINTS, PAGE_RULE_FROZEN_DEV, PERIODS,
                                                                RETRIEVAL_WINDOW_DAYS, year_ranges)
from research.erm_nominee_validation.acquisition.scope import build_candidates, build_scope
from research.erm_nominee_validation.acquisition.store import ArchiveStore
from research.erm_nominee_validation.acquisition.transport import Request, TransportExhausted, OffHoursRefusal, req

ALPACA_ASSETS = "https://paper-api.alpaca.markets/v2/assets"
ALPACA_CA = "https://data.alpaca.markets/v1/corporate-actions"
SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
SEC_LOOKUP = "https://www.sec.gov/Archives/edgar/cik-lookup-data.txt"
SEC_SUB = "https://data.sec.gov/submissions/{}"
SEC_MASTER = "https://www.sec.gov/Archives/edgar/full-index/{}/master.idx"
SEC_HDR = "https://www.sec.gov/Archives/edgar/data/{}/{}/{}-index-headers.html"
SP500_LISTING = "https://api.github.com/repos/fja05680/sp500/contents"
SP500_FILE = "S&P 500 Historical Components & Changes (Updated).csv"   # README: "historical index membership"
MERGER_TYPES = "cash_merger,stock_merger,stock_and_cash_merger"


def form345_url(q: str) -> str:
    from research.event_response_map_v1.phase_d import FORM345_URL
    return FORM345_URL.format(q)


class _Missing:
    """Marker for a request that ended in a FAIL state (never confused with absence or an empty result)."""


MISSING = _Missing()


class GuardAdapter:
    """The frozen data.Downloader calls guard.check_range(start, end, layer=...) before every pass and guard.record()
    after it. Route both to THIS acquisition's guard and ledger -- never to the real ERM guard state."""

    def __init__(self, guard, store, category="bars"):
        self.guard, self.store, self.category = guard, store, category

    def check_range(self, start, end, *, layer: str) -> None:
        self.guard.check_acquisition(date.fromisoformat(str(start)), date.fromisoformat(str(end)), self.category)

    def record(self, event: dict) -> None:
        self.store.event({"bars_pass": event})


class ProductionAcquirer:
    def __init__(self, guard, transport, *, bars_clock=None, bars_sleep=None, reference_date: date | None = None,
                 download_date: date | None = None, clock=None):
        """reference_date (alias download_date): the ONE acquisition reference date R (see period.py). Pinned in
        acquisition/reference.json at first use; a resume must present the same R (or none), and a released guard's
        R must equal it. clock: real time used to refuse broad requests after R + RETRIEVAL_WINDOW_DAYS."""
        self.guard, self.transport = guard, transport
        self.bars_clock, self.bars_sleep = bars_clock, bars_sleep
        self.requested_reference = reference_date or download_date
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.download_date = self.requested_reference or self.clock().date()
        self.failures, self.absences = [], []

    # ------------------------------------------------------------------------------------------------ one request
    def get(self, category: str, r: Request, scope: tuple, rel_path: str, *, required: bool,
            absent_on_404: bool = False, insufficient_on_404: bool = False, validate=None, within=None,
            malformed_on_404: str | None = None):
        """-> bytes (USABLE) | None (LEGITIMATELY ABSENT) | MISSING (fail state, recorded).
        within(body) -> None | str: RESPONSE-scope check against the declared envelope; a violation quarantines the
        bytes, records the exposure and raises ScopeExceeded (RUN_INVALID) -- filtering afterwards never makes a
        broader response unexposed."""
        if self.store.done(r.key):
            rec = self.store.latest(r.key)
            return None if rec["state"] == S.ABSENT else self.store.read(r.key)
        if category in BROAD_ENDPOINTS:                                  # content runs to the retrieval moment
            today = self.clock().astimezone(timezone.utc).date()
            if today > self.download_date + timedelta(days=RETRIEVAL_WINDOW_DAYS):
                self.store.event({"blocked": "RESUME_AFTER_REFERENCE_WINDOW", "category": category, "request": r.key,
                                  "reference_date": str(self.download_date), "today": str(today)})
                self._write_status("REFERENCE_WINDOW", complete=False)
                raise S.AcquisitionBlocked(
                    f"RESUME_AFTER_REFERENCE_WINDOW: broad endpoint {category} on {today} would return content after "
                    f"the reference date {self.download_date} + {RETRIEVAL_WINDOW_DAYS} d; start a new acquisition "
                    f"under a new release instead")
        self.guard.check_acquisition(scope[0], scope[1], category)       # BEFORE the request exists
        try:
            resp = self.transport.fetch(r)
        except (TransportExhausted, OffHoursRefusal, ConnectionError, TimeoutError) as e:
            self.store.record(r, category, scope, S.TRANSPORT, detail=f"{type(e).__name__}: {e}"[:300])
            return self._fail(category, r, S.TRANSPORT, required, str(e))
        if resp.status == 404 and malformed_on_404:
            self.store.record(r, category, scope, S.MALFORMED, http_status=404, attempts=resp.attempts,
                              detail=malformed_on_404)
            return self._fail(category, r, S.MALFORMED, True, malformed_on_404)
        if resp.status == 404 and absent_on_404:
            self.store.record(r, category, scope, S.ABSENT, http_status=404, attempts=resp.attempts,
                              detail="provider 404: legitimately absent")
            self.absences.append({"category": category, "request": r.key, "rationale": "provider 404"})
            return None
        if resp.status == 404 and insufficient_on_404:
            self.store.record(r, category, scope, S.INSUFFICIENT, http_status=404, attempts=resp.attempts,
                              detail="provider 404: dataset not (yet) available")
            return self._fail(category, r, S.INSUFFICIENT, required, "404")
        if resp.status != 200:
            self.store.record(r, category, scope, S.TRANSPORT, http_status=resp.status, attempts=resp.attempts,
                              detail=f"HTTP {resp.status}")
            return self._fail(category, r, S.TRANSPORT, required, f"HTTP {resp.status}")
        problem = None
        try:
            problem = validate(resp.body) if validate else None
        except Exception as e:  # noqa: BLE001 -- any parse error is MALFORMED
            problem = f"{type(e).__name__}: {e}"
        if problem:
            self.store.record(r, category, scope, S.MALFORMED, http_status=200, attempts=resp.attempts,
                              body=resp.body, rel_path="acquisition/malformed/" + rel_path.replace("/", "__"),
                              detail=str(problem)[:300])
            return self._fail(category, r, S.MALFORMED, required, problem)
        out = None
        try:
            out = within(resp.body) if within else None
        except Exception as e:  # noqa: BLE001 -- an unreadable date field cannot be shown to be inside the scope
            out = f"scope not verifiable: {type(e).__name__}: {e}"
        if out:
            self.store.record(r, category, scope, S.SCOPE_EXCEEDED, http_status=200, attempts=resp.attempts,
                              body=resp.body, rel_path="acquisition/scope_exceeded/" + rel_path.replace("/", "__"),
                              detail=str(out)[:300])
            self.store.event({"exposure": "RESPONSE_EXCEEDS_AUTHORISED_SCOPE", "category": category,
                              "request": r.key, "declared_scope": [str(scope[0]), str(scope[1])], "detail": str(out)})
            self._fail(category, r, S.SCOPE_EXCEEDED, True, out)
            self._write_status("RESPONSE_SCOPE", complete=False)
            raise S.ScopeExceeded(f"{category}: response outside the authorised envelope {scope[0]}..{scope[1]}: {out}")
        self.store.record(r, category, scope, S.USABLE, http_status=200, attempts=resp.attempts, body=resp.body,
                          rel_path=rel_path)
        return resp.body

    def _fail(self, category, r, state, required, detail):
        self.failures.append({"category": category, "request": r.key, "state": state, "required": required,
                              "detail": str(detail)[:300]})
        return MISSING

    def _require(self, stage: str) -> None:
        bad = [f for f in self.failures if f["required"]]
        if bad:
            self._write_status(stage, complete=False)
            raise S.AcquisitionBlocked(f"ACQUISITION_BLOCKED at {stage}: {len(bad)} required request(s) failed; "
                                       f"first: {bad[0]}")

    # ------------------------------------------------------------------------------------------------ validators
    @staticmethod
    def _json_obj(key):
        def v(body):
            j = json.loads(body)
            return None if key is None or key in j else f"missing key {key!r}"
        return v

    @staticmethod
    def _json_list(body):
        j = json.loads(body)
        return None if isinstance(j, list) and j else "empty or non-list asset response"

    @staticmethod
    def _zip_form345(body):
        import zipfile
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            return None if any(n.split("/")[-1].upper() == "SUBMISSION.TSV" for n in z.namelist()) else "no SUBMISSION.TSV"

    @staticmethod
    def _master(body):
        t = body.decode("latin-1")
        return None if "CIK|Company Name|Form Type|Date Filed|Filename" in t or t.count("|") >= 4 else "not a master.idx"

    # ------------------------------------------------------------------------------------------------ response scope
    @staticmethod
    def _iso_dates(row):
        import re as _re
        return {k: v[:10] for k, v in row.items() if isinstance(v, str) and _re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", v)}

    def _ca_within(self, start, end):
        """Declared corporate-action response envelope (period.CA_*): at least one primary date (process_date /
        ex_date: the provider's range filter) inside [start, end]; the named attribute dates (payable / record /
        effective / process / ex) at most CA_ATTRIBUTE_LAG_DAYS after end; any other date field never after end."""
        from research.erm_nominee_validation.acquisition.period import (CA_ATTRIBUTE_DATE_FIELDS, CA_ATTRIBUTE_LAG_DAYS,
                                                                        CA_PRIMARY_DATE_FIELDS)
        lag_end = (date.fromisoformat(end) + timedelta(days=CA_ATTRIBUTE_LAG_DAYS)).isoformat()

        def w(body):
            for typ, rs in (json.loads(body).get("corporate_actions") or {}).items():
                for x in rs:
                    ds = self._iso_dates(x)
                    prim = [ds[k] for k in CA_PRIMARY_DATE_FIELDS if k in ds]
                    if not prim:
                        return f"{typ} row without a primary date field"
                    if not any(start <= v <= end for v in prim):
                        return f"{typ} primary dates {prim} outside {start}..{end}"
                    for k, v in ds.items():
                        if v > (lag_end if k in CA_ATTRIBUTE_DATE_FIELDS else end):
                            return f"{typ} {k} {v} after the declared bound"
            return None
        return w

    @staticmethod
    def _f345_within(lo: date, hi: date):
        def w(body):
            import csv as _csv
            import zipfile
            with zipfile.ZipFile(io.BytesIO(body)) as z:
                n = next(x for x in z.namelist() if x.split("/")[-1].upper() == "SUBMISSION.TSV")
                with z.open(n) as fh:
                    for r in _csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8", errors="replace"), delimiter="\t"):
                        raw = str(r.get("FILING_DATE", "")).strip()
                        try:
                            fd = datetime.strptime(raw[:11], "%d-%b-%Y").date()
                        except ValueError:
                            fd = date.fromisoformat(raw[:10])
                        if not (lo <= fd <= hi):
                            return f"Form 3/4/5 filing dated {fd} outside {lo}..{hi}"
            return None
        return w

    @staticmethod
    def _master_within(lo: date, hi: date):
        def w(body):
            for line in body.decode("latin-1").splitlines():
                q = line.split("|")
                if len(q) == 5 and q[0].strip().isdigit() and not (lo.isoformat() <= q[3].strip() <= hi.isoformat()):
                    return f"master.idx row dated {q[3].strip()} outside {lo}..{hi}"
            return None
        return w

    @staticmethod
    def _header_within(hi: date):
        def w(body):
            import re as _re
            m = _re.search(r"FILED AS OF DATE:\s*(\d{8})", body.decode("latin-1"))
            if m is None:
                return None                                   # no date field: content is that one filing's header
            fd = date(int(m.group(1)[:4]), int(m.group(1)[4:6]), int(m.group(1)[6:]))
            return None if fd <= hi else f"filing header FILED AS OF {fd} after {hi}"
        return w

    def _retrieval_within(self, key):
        """Broad JSON with dated rows: nothing may be dated after the authorised retrieval bound."""
        bound = (self.download_date + timedelta(days=RETRIEVAL_WINDOW_DAYS)).isoformat()

        def w(body):
            j = json.loads(body)
            blocks = [j["filings"]["recent"]] if key == "filings" else [j]
            for b in blocks:
                late = [d for d in b.get("filingDate", []) if d > bound]
                if late:
                    return f"{len(late)} filing rows after the retrieval bound {bound}"
            return None
        return w

    # ------------------------------------------------------------------------------------------------ paginated CA
    def corporate_actions(self, category, types, start, end, *, symbols=None, required=True):
        rows, token, page = [], None, 0
        while True:
            p = {"start": start, "end": end, "types": types, "limit": 1000}
            if symbols:
                p["symbols"] = symbols
            if token:
                p["page_token"] = token
            tag = f"alpaca/ca_{types.replace(',', '+')}_{symbols or 'all'}_{start}_{end}_{page:03d}.json".replace(",", "+")
            body = self.get(category, req("alpaca_meta", ALPACA_CA, p), (date.fromisoformat(start), date.fromisoformat(end)),
                            tag, required=required, validate=self._json_obj("corporate_actions"),
                            within=self._ca_within(start, end))
            if body is MISSING or body is None:
                if page:                                                  # truncated pagination
                    self.failures.append({"category": category, "request": f"{types} {start}..{end} page {page}",
                                          "state": S.MALFORMED, "required": required,
                                          "detail": "pagination truncated"})
                return MISSING
            j = json.loads(body)
            for typ, rs in (j.get("corporate_actions") or {}).items():
                rows += [{**x, "_type": typ} for x in rs]
            token, page = j.get("next_page_token"), page + 1
            if not token:
                return rows

    # ------------------------------------------------------------------------------------------------ SEC helpers
    def sec_file(self, category, url, name, scope, **kw):
        return self.get(category, req("sec", url), scope, f"sec/{name}.gz", **kw)

    def submissions_main(self, cik):
        """SEC submissions JSON (broad: full history to the retrieval date). 404 = legitimately absent (frozen
        unresolved policy downstream); any other failure is REQUIRED (never treated as 'no filings')."""
        if cik in self._subs:
            return self._subs[cik]
        b = self.sec_file("submissions", SEC_SUB.format(f"CIK{cik}.json"), f"sub_CIK{cik}.json",
                          (None, self.download_date), required=True, absent_on_404=True,
                          validate=self._json_obj("filings"), within=self._retrieval_within("filings"))
        self._subs[cik] = None if b is None or b is MISSING else json.loads(b)
        for f in (self._subs[cik] or {}).get("filings", {}).get("files", []):
            self._adv[f["name"]] = f                             # authoritative page list from THIS main
        return self._subs[cik]

    @staticmethod
    def verify_page(adv: dict, page: dict) -> str | None:
        """A history page must match what the main JSON fetched in the same acquisition advertises:
        row count == filingCount, first filingDate == filingFrom, last filingDate <= filingTo + 1 day (SEC's filingTo
        lags by at most one day: all 431 development pages satisfy exactly these bounds). A same-named page whose
        content moved (repagination between the main and the page retrieval) fails here -- never silently mixed."""
        fd = page.get("filingDate")
        if not isinstance(fd, list) or any(len(page.get(k, [])) != len(fd) for k in ("form", "accessionNumber")):
            return "page columns missing or of unequal length"
        if len(fd) != adv.get("filingCount"):
            return f"REPAGINATION_OR_INCOMPLETE_PAGE: {len(fd)} rows, main advertises {adv.get('filingCount')}"
        if fd and min(fd) != adv.get("filingFrom"):
            return f"REPAGINATION_OR_INCOMPLETE_PAGE: first filing {min(fd)}, main advertises {adv.get('filingFrom')}"
        if fd and date.fromisoformat(max(fd)) > date.fromisoformat(adv["filingTo"]) + timedelta(days=1):
            return f"REPAGINATION_OR_INCOMPLETE_PAGE: last filing {max(fd)} after advertised {adv['filingTo']} + 1 d"
        return None

    def submissions_page(self, name):
        """A page ADVERTISED by the issuer's main: 404 = incomplete pagination (required failure, never an absence),
        content must verify against the advertisement."""
        adv = self._adv.get(name)
        if adv is None:
            self.failures.append({"category": "submissions", "request": name, "state": S.MALFORMED, "required": True,
                                  "detail": "page requested without an advertisement in a main fetched this run"})
            return None
        b = self.sec_file("submissions", SEC_SUB.format(name), "sub_" + name, (None, self.download_date),
                          required=True, malformed_on_404="advertised history page missing (incomplete pagination)",
                          validate=lambda x: self.verify_page(adv, json.loads(x)),
                          within=self._retrieval_within("page"))
        return None if b is None or b is MISSING else json.loads(b)

    def header_text(self, cik, acc, filed: str | None = None):
        """Point-in-time filing header (R7 / V2.1 SIC). Content scope = the filing date when known, else
        (history, filings_to): every accession requested comes from rows already filtered to <= filings_to."""
        if acc in self._hdr:
            return self._hdr[acc]
        url = SEC_HDR.format(int(cik), acc.replace("-", ""), acc)
        scope = (date.fromisoformat(filed), date.fromisoformat(filed)) if filed else (None, self.per.filings_to)
        b = self.sec_file("filing_headers", url, f"hdr_{acc}.html", scope, required=True, absent_on_404=True,
                          within=self._header_within(scope[1]))
        self._hdr[acc] = None if b is None or b is MISSING else b.decode("latin-1")
        return self._hdr[acc]

    # ------------------------------------------------------------------------------------------------ S&P coverage
    @staticmethod
    def git_blob_sha(b: bytes) -> str:
        import hashlib
        return hashlib.sha1(b"blob %d\0" % len(b) + b).hexdigest()

    def sp500(self, per):
        """S0 -- FIRST acquisition prerequisite. fja05680 publishes no as-of date in file names, README ("from 1996 til
        MM-DD-YYYY", a placeholder), releases or tags (metadata check 2026-10-05). Coverage is therefore established
        only from the acquired file itself, after authorisation: a membership row dated on or after the scope end must
        exist (a row dated >= T fixes membership through T; without one, membership after the last row is unknown and
        is NEVER assumed unchanged). Otherwise INSUFFICIENT -> ACQUISITION_BLOCKED before any other request.
        Provenance: the listing entry (git blob sha, size) and the downloaded bytes must agree."""
        lst = self.get("sp500_pit", req("github", SP500_LISTING), (None, self.download_date), "sp500/listing.json",
                       required=True, validate=lambda b: None if isinstance(json.loads(b), list) else "listing not a list")
        if lst is MISSING:
            return MISSING, None
        item = next((it for it in json.loads(lst) if it.get("name") == SP500_FILE), None)
        if item is None:
            self.failures.append({"category": "sp500_pit", "request": SP500_LISTING, "state": S.INSUFFICIENT,
                                  "required": True, "detail": f"{SP500_FILE!r} not published in the listing"})
            return MISSING, None

        def valid(b):
            if not b.decode("utf-8").startswith("date,tickers"):
                return "unexpected CSV header"
            if item.get("sha") and self.git_blob_sha(b) != item["sha"]:
                return "downloaded bytes do not match the listing's git blob sha (file changed between calls)"
            return None
        bound = (self.download_date + timedelta(days=RETRIEVAL_WINDOW_DAYS)).isoformat()
        body = self.get("sp500_pit", req("github", item["download_url"]), (None, self.download_date), "sp500/raw.csv",
                        required=True, validate=valid, within=lambda b: (
                            None if max(r["date"][:10] for r in csv.DictReader(io.StringIO(b.decode("utf-8")))) <= bound
                            else "membership rows dated after the retrieval bound"))
        if body is MISSING:
            return MISSING, None
        last = max(r["date"][:10] for r in csv.DictReader(io.StringIO(body.decode("utf-8"))))
        cov = {"sp500_coverage_last_row": last, "required_through": str(per.sp500_to),
               "listing_entry": {k: item.get(k) for k in ("name", "sha", "size")}}
        if last < per.sp500_to.isoformat():
            self.failures.append({"category": "sp500_pit", "request": item["download_url"], "state": S.INSUFFICIENT,
                                  "required": True, "detail": f"last membership row {last} < required coverage "
                                                              f"{per.sp500_to}: membership after {last} unknown"})
            self.store.event({"sp500_coverage": "INSUFFICIENT", **cov})
            return MISSING, last
        self.store.event({"sp500_coverage": "SUFFICIENT", **cov})
        return body, last

    # ------------------------------------------------------------------------------------------------ reference date
    def _pin_reference(self) -> None:
        """One acquisition = one reference date R, pinned at first use. A resume never moves R: a different requested
        R, or a released guard naming another R, blocks before any request."""
        p = self.archive / "acquisition" / "reference.json"
        rel = getattr(self.guard, "release", None)
        if p.exists():
            pinned = json.loads(p.read_text())
            if pinned["window_id"] != self.cfg.window_id:
                raise S.AcquisitionBlocked(f"archive pinned to window {pinned['window_id']}, not {self.cfg.window_id}")
            if self.requested_reference and self.requested_reference.isoformat() != pinned["reference_date"]:
                raise S.AcquisitionBlocked(f"REFERENCE_DATE_MISMATCH: archive pinned to {pinned['reference_date']}, "
                                           f"resume asked for {self.requested_reference}")
            self.download_date = date.fromisoformat(pinned["reference_date"])
        else:
            if rel is not None and rel.download_date != self.download_date.isoformat():
                raise S.AcquisitionBlocked(f"REFERENCE_DATE_MISMATCH: release names {rel.download_date}, acquisition "
                                           f"reference is {self.download_date}")
            B.atomic(p, json.dumps({"reference_date": self.download_date.isoformat(), "window_id": self.cfg.window_id,
                                    "retrieval_window_days": RETRIEVAL_WINDOW_DAYS,
                                    "submissions_page_rule": self.per.submissions_page_rule,
                                    "pinned_utc": self.clock().isoformat()}, indent=1))
        if rel is not None and rel.download_date != self.download_date.isoformat():
            raise S.AcquisitionBlocked(f"REFERENCE_DATE_MISMATCH: release names {rel.download_date}, acquisition "
                                       f"reference is {self.download_date}")

    def _exposure(self) -> dict:
        """Requests whose declared content range reaches a locked ERM range (2024 / 2025-01-02 onward)."""
        out = {}
        for r in self.store._latest.values():
            to = r.get("content_to")
            if to and to >= "2024-01-01":
                out.setdefault(r["category"], {}).setdefault(r["state"], 0)
                out[r["category"]][r["state"]] += 1
        return out

    # ------------------------------------------------------------------------------------------------ status
    def _write_status(self, stage, *, complete, extra=None):
        st = {"stage": stage, "complete": complete, "window_id": self.cfg.window_id,
              "period": {k: str(v) for k, v in self.per.__dict__.items() if k != "notes"},
              "download_date": str(self.download_date), "by_category": self.store.summary(),
              "required_failures": [f for f in self.failures if f["required"]],
              "optional_failures": [f for f in self.failures if not f["required"]],
              "legitimate_absences": self.absences, "protected_range_requests": self._exposure(),
              "reference_date": str(self.download_date), **(extra or {})}
        B.atomic(self.archive / "acquisition" / "acquisition_status.json", json.dumps(st, indent=1, default=str))

    # ------------------------------------------------------------------------------------------------ main
    def acquire(self, cfg, archive: Path) -> dict:
        from research.event_response_map_v1 import data as D
        self.cfg, self.archive, self.per = cfg, Path(archive), PERIODS[cfg.window_id]
        per = self.per
        self.store = ArchiveStore(self.archive)
        self._subs, self._hdr, self._adv = {}, {}, {}
        self._pin_reference()
        dd = self.download_date
        # ---------------- S0 S&P coverage: the first prerequisite (stops before any other request if insufficient)
        sp_body, sp_asof = self.sp500(per)
        self._require("S0_SP500_COVERAGE")
        # ---------------- S1 BASE
        assets = []
        for st in ("active", "inactive"):
            b = self.get("assets_current", req("alpaca_meta", ALPACA_ASSETS, {"status": st, "asset_class": "us_equity"}),
                         (None, dd), f"alpaca/assets_{st}.json", required=True,
                         validate=self._json_list if st == "active" else self._json_obj(None))
            if b is not MISSING:
                assets += json.loads(b)
        ca_from, ca_to = per.corporate_actions_from, per.corporate_actions_to
        renames, mergers = [], []
        for s_, e_ in year_ranges(ca_from, ca_to):
            r_ = self.corporate_actions("corporate_actions", "name_change", s_, e_)
            m_ = self.corporate_actions("corporate_actions", MERGER_TYPES, s_, e_)
            renames += [] if r_ is MISSING else r_
            mergers += [] if m_ is MISSING else m_
        ident_renames = []
        for s_, e_ in per.identity_rename_ranges:
            e_ = dd.isoformat() if e_ == "DOWNLOAD_DATE" else e_          # fixed reference date, never "today"
            r_ = self.corporate_actions("identity_renames", "name_change", s_, e_)
            if r_ is not MISSING:
                ident_renames += [{"old_symbol": x.get("old_symbol"), "new_symbol": x.get("new_symbol"),
                                   "process_date": x.get("process_date")} for x in r_]
        tick = self.sec_file("sec_reference_current", SEC_TICKERS, "company_tickers.json", (None, dd), required=True,
                             validate=self._json_obj(None))
        lookup = self.sec_file("sec_reference_current", SEC_LOOKUP, "cik-lookup-data.txt", (None, dd), required=True)
        f345 = {}
        for q in per.f345_quarters(per.evidence_f345_from):
            y, qq = int(q[:4]), int(q[-1])
            qa, qb = date(y, 3 * qq - 2, 1), date(y + (qq == 4), (3 * qq) % 12 + 1, 1)
            f345[q] = self.sec_file("form345", form345_url(q), f"{q}_form345.zip", (qa, qb - timedelta(days=1)),
                                    required=True, insufficient_on_404=True, validate=self._zip_form345,
                                    within=self._f345_within(qa, qb - timedelta(days=1)))
        masters = {}
        for q in per.master_quarters():
            y, qq = int(q[:4]), int(q[-1])
            qlo = date(y, 3 * qq - 2, 1)
            qend = date(y + (qq == 4), (3 * qq) % 12 + 1, 1) - timedelta(days=1)
            masters[q] = self.sec_file("master_idx", SEC_MASTER.format(q), "master_" + q.replace("/", "_") + ".idx",
                                       (qlo, per.filings_to), required=True, insufficient_on_404=True,
                                       validate=self._master, within=self._master_within(qlo, qend))
        self._require("S1_BASE")
        # ---------------- S2 SCOPE
        sp_text = sp_body.decode("utf-8")
        cand = build_candidates(assets, renames, mergers, sp_text, per)
        ident_q = set(per.f345_quarters(per.identity_f345_from))
        scope = build_scope(cand, per, renames_in_period=renames, renames_identity=ident_renames,
                            company_tickers=json.loads(tick), cik_lookup_text=lookup.decode("latin-1"),
                            f345_zips=[f345[q] for q in sorted(f345) if q in ident_q],
                            master_texts=[masters[q].decode("latin-1") for q in sorted(masters)],
                            sp_csv_text=sp_text, submissions_main=self.submissions_main,
                            submissions_page=self.submissions_page_overlapping, header_text=self.header_text)
        self._require("S2_SCOPE")
        # ---------------- S3 BARS (frozen Downloader; groups exactly as Phase D)
        groups = {"KEPT": (sorted(scope.kept) + list(D.BENCHMARKS), sorted(scope.kept)),
                  "R1A_REMOVED": (sorted(scope.r1a_removed), sorted(scope.r1a_removed))}
        for g, (ret_syms, elig_syms) in groups.items():
            self.bars_group(g, ret_syms, elig_syms, per)
        self._require("S3_BARS")
        # ---------------- S4 EVENTS (discovery only) + S5 EVIDENCE
        events = self.discover_events(per, renames + ident_renames, f345)
        self.issuer_evidence(events, per, set(scope.submissions_ciks))
        self._require("S5_EVIDENCE")
        # ---------------- S6 ETF cash dividends (OPTIONAL)
        etf = []
        for s_, e_ in year_ranges(per.etf_dividends_from, per.etf_dividends_to):
            r_ = self.corporate_actions("etf_cash_dividends", "cash_dividend", s_, e_,
                                        symbols=",".join(D.BENCHMARKS), required=False)
            if r_ is not MISSING:
                etf += [{"symbol": x.get("symbol"), "ex_date": x.get("ex_date")} for x in r_]
        etf_ok = not any(f["category"] == "etf_cash_dividends" for f in self.failures)
        # ---------------- S7 COMPLETE + S8 MATERIALISE
        self._require("S7_COMPLETE")
        return self.materialise(cand, scope, renames + ident_renames, sp_text, sp_asof, etf if etf_ok else None,
                                events, groups)

    def submissions_page_overlapping(self, name):
        return self.submissions_page(name)

    def issuer_evidence(self, events, per, s2_ciks):
        """S5. History pages per the window's declared rule (period.submissions_page_rule):
          ALL_PAGES_TO_WINDOW_END  every event issuer: main + EVERY advertised page with filingFrom <= window end,
                                   each verified against the advertisement (complete history to D)
          FROZEN_DEV_EVIDENCE      DEV replay only: issuers without an S2 main get main + pages <= window end; S2
                                   issuers keep the R3 overlapping pages (the development evidence as acquired)
        then the point-in-time header of the issuer's latest company filing <= D, read through the SAME reader the
        builder uses (builder.subs_reader over the materialised sec/ directory) so S5 and BUILD see one evidence set.
        A history that is complete but holds no qualifying filing is evidence (frozen V2.1 policy applies); a page that
        is missing, malformed or repaginated is a required failure (never an exclusion)."""
        from research.event_response_map_v1 import identity as I
        fhi = per.filings_to.isoformat()
        issuers = sorted({e["issuer"] for e in events if e["issuer"]})
        hist = {}
        for cik in issuers:
            if per.submissions_page_rule == PAGE_RULE_FROZEN_DEV and cik in s2_ciks:
                hist[cik] = {"rule": PAGE_RULE_FROZEN_DEV, "pages": "R3 overlapping pages (as acquired)"}
                continue
            m = self.submissions_main(cik)
            req_pages = [f["name"] for f in (m or {}).get("filings", {}).get("files", [])
                         if f.get("filingFrom", "9999") <= fhi]
            got = [n for n in req_pages if self.submissions_page(n) is not None]
            hist[cik] = {"rule": per.submissions_page_rule, "main": "ABSENT" if m is None else "USABLE",
                         "pages_required": len(req_pages), "pages_verified": len(got),
                         "complete": len(got) == len(req_pages)}
        B.atomic(self.archive / "acquisition" / "issuer_history.json", json.dumps(hist, indent=0, sort_keys=True))
        if any(f["required"] for f in self.failures):
            return
        subs = B.subs_reader([self.archive / "sec"], per.events_to.isoformat())
        for e in events:
            if not e["issuer"]:
                continue
            co = [(fd, a) for fd, f, a, _, _ in (subs(e["issuer"]) or [])
                  if fd <= e["gap_day"] and f in I.COMPANY_FORMS]
            if co:
                self.header_text(e["issuer"], co[-1][1], co[-1][0])

    def bars_group(self, g, ret_syms, elig_syms, per):
        from research.event_response_map_v1 import data as D
        d = self.archive / "bars" / g
        done = self.archive / "acquisition" / f"bars_{g}.COMPLETE"
        if done.exists():
            return
        if not ret_syms and not elig_syms:                 # e.g. no R1a-removed symbols: nothing to request
            done.write_text(json.dumps({"group": g, "returns": 0, "eligibility": 0}))
            return
        if d.exists():                                     # partial pass: preserve, then redo from scratch (frozen §6)
            k = 1
            while (self.archive / "bars_incomplete" / f"{g}_{k}").exists():
                k += 1
            (self.archive / "bars_incomplete").mkdir(exist_ok=True)
            shutil.move(str(d), str(self.archive / "bars_incomplete" / f"{g}_{k}"))
        transport = self.transport

        def opener(r):
            import urllib.parse
            u = urllib.parse.urlsplit(r.full_url)
            q = urllib.parse.parse_qsl(u.query)
            resp = transport.fetch(Request("alpaca_bars", f"{u.scheme}://{u.netloc}{u.path}", tuple(sorted(q))))
            if resp.status != 200:
                raise ConnectionError(f"bars HTTP {resp.status}")
            return resp.body
        kw = {"opener": opener, "guard": GuardAdapter(self.guard, self.store)}
        if self.bars_clock:
            kw["clock"] = self.bars_clock
        if self.bars_sleep:
            kw["sleep"] = self.bars_sleep
        dl = D.Downloader(d, {}, **kw)
        s_, e_ = per.bars_from.isoformat(), per.events_to.isoformat()
        try:
            if ret_syms:
                dl.pass_(ret_syms, purpose="RETURNS", start=s_, end=e_)
            if elig_syms:
                dl.pass_(elig_syms, purpose="ELIGIBILITY_ONLY", start=s_, end=e_)
        except (TransportExhausted, OffHoursRefusal, ConnectionError, TimeoutError, D.MarketHoursRefusal) as e:
            self.failures.append({"category": "bars", "request": f"group {g}", "state": S.TRANSPORT, "required": True,
                                  "detail": f"{type(e).__name__}: {e}"[:300]})
            return
        except ValueError as e:                            # json decode of a page
            self.failures.append({"category": "bars", "request": f"group {g}", "state": S.MALFORMED, "required": True,
                                  "detail": str(e)[:300]})
            return
        if not (d / "manifest.json").exists():
            d.mkdir(parents=True, exist_ok=True)
            dl.write_manifest()
        import gzip as _gz
        for f in dl.manifest["files"]:                       # response scope: every bar inside [start, end]
            for sym, bs in (json.loads(_gz.decompress((d / f["file"]).read_bytes())).get("bars") or {}).items():
                out = [x["t"][:10] for x in bs if not (s_ <= x["t"][:10] <= e_)]
                if out:
                    self.store.event({"exposure": "RESPONSE_EXCEEDS_AUTHORISED_SCOPE", "category": "bars",
                                      "file": f["file"], "symbol": sym, "dates": out[:5], "declared": [s_, e_]})
                    self._write_status("S3_BARS_SCOPE", complete=False)
                    raise S.ScopeExceeded(f"bars: {sym} bars dated {out[:3]} outside {s_}..{e_} ({f['file']})")
        done.write_text(json.dumps({"group": g, "returns": len(ret_syms), "eligibility": len(elig_syms)}))

    def discover_events(self, per, renames_all, f345):
        """S4. Gap days + L1 eligibility (frozen events.gap_events / universe.eligibility via builder.population) and
        the V2.1 identity at D (dated Form 3/4/5 + renames + raw-volume continuity, via builder.series exactly as BUILD
        computes it). Writes dates and identities ONLY: no exit session, no forward price, no return is computed."""
        from collections import defaultdict
        import pandas as pd
        from research.erm_nominee_audit import v2_rules as R
        from research.event_response_map_v1 import data as D, identity as I
        fg = self.guard.frame_guard()
        frames = []
        for g in ("KEPT", "R1A_REMOVED"):
            d = self.archive / "bars" / g
            if (d / "manifest.json").exists():
                a, _ = D.load(d, purpose="RETURNS", guard=fg)
                r, _ = D.load(d, purpose="ELIGIBILITY_ONLY", guard=fg)
                frames.append((g, a, r))
        sessions = sorted(frames[0][1].loc[frames[0][1]["symbol"] == "SPY", "date"].unique())
        pop = []
        for g, a, r in frames:
            pop += B.population(a[~a["symbol"].isin(D.BENCHMARKS)], r, sessions, per.events_from, per.events_to, g)
        syms = {s for _, s, _, _ in pop}
        alls = pd.concat([a[a["symbol"].isin(syms)] for _, a, _ in frames])
        raws = pd.concat([r[r["symbol"].isin(syms)] for _, _, r in frames])
        vol = {s: v["vol"] for s, v in B.series(alls, raws).items()} if syms else {}
        f = defaultdict(list)
        for q in sorted(f345):
            B.f345_parse(f345[q], f, per.events_to.isoformat())
        f = {k: sorted(set(v)) for k, v in f.items()}
        edges = I.rename_edges(renames_all)
        out = []
        for g, s, d0, ent in sorted(pop, key=lambda x: (x[3], x[1], x[0])):
            idt = R.identity_at(s, d0, edges, f, vol.get(s, {}))
            out.append({"group": g, "symbol": s, "gap_day": d0.isoformat(), "entry": ent.isoformat(),
                        "issuer": idt["issuer"], "identity": idt["identity"]})
        B.atomic(self.archive / "acquisition" / "candidate_events.json",
                 json.dumps({"note": "S4 discovery only: gap dates, entry dates and identities; no outcomes",
                             "events": out}, indent=0))
        return out

    def materialise(self, cand, scope, renames_all, sp_text, sp_asof, etf, events, groups):
        from research.erm_nominee_validation.adapters import write_archive_manifest
        a = self.archive
        cand_doc = {**cand, "identity_cik": {s: v["cik"] for s, v in scope.identity.items()},
                    "scope": {"kept": scope.kept, "r1a_removed": scope.r1a_removed, "r1b_removed": scope.r1b_removed}}
        B.atomic(a / "candidates.json", json.dumps(cand_doc, sort_keys=True, indent=0))
        B.atomic(a / "renames.json", json.dumps(renames_all))
        rows = list(csv.DictReader(io.StringIO(sp_text)))
        keep = [r for r in rows if r["date"][:10] <= self.per.sp500_to.isoformat()]
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=["date", "tickers"], lineterminator="\n")
        w.writeheader()
        w.writerows({"date": r["date"], "tickers": r["tickers"]} for r in keep)
        B.atomic(a / "sp500.csv", buf.getvalue())
        B.atomic(a / "etf_div.json", json.dumps(etf if etf is not None else []))
        inputs = {
            "bars": [p.relative_to(a).as_posix() for p in sorted((a / "bars").rglob("*")) if p.is_file()],
            "candidates": ["candidates.json"], "renames": ["renames.json"], "sp500_pit": ["sp500.csv"],
            "form345": [p.relative_to(a).as_posix() for p in sorted((a / "sec").glob("*_form345.zip.gz"))],
            "submissions": [p.relative_to(a).as_posix() for p in sorted((a / "sec").glob("sub_*.gz"))],
            "master_idx": [p.relative_to(a).as_posix() for p in sorted((a / "sec").glob("master_*.idx.gz"))],
            "filing_headers": [p.relative_to(a).as_posix() for p in sorted((a / "sec").glob("hdr_*.html.gz"))],
            "etf_cash_dividends": ["etf_div.json"],
        }
        self._write_status("S8_MATERIALISE", complete=True,
                           extra={"sp500_asof": str(sp_asof), "etf_cash_dividends": "USABLE" if etf is not None else
                                  "OPTIONAL_FAILED -> descriptive subset UNKNOWN",
                                  "scope_counts": {"candidates": len(cand["symbols"]), "kept": len(scope.kept),
                                                   "r1a_removed": len(scope.r1a_removed),
                                                   "r1b_removed": len(scope.r1b_removed)},
                                  "candidate_events": len(events)})
        # per-request evidence indexes: a category whose every request is USABLE or LEGITIMATELY_ABSENT is complete even
        # when it holds no bytes (e.g. every header 404); the index is part of that input and hashed with it
        for cat in ("submissions", "filing_headers"):
            B.atomic(a / "acquisition" / f"index_{cat}.json", json.dumps(self.store.index(cat), indent=0))
            inputs[cat].append(f"acquisition/index_{cat}.json")
        inputs["acquisition_status"] = ["acquisition/acquisition_status.json", "acquisition/ledger.jsonl"]
        return write_archive_manifest(a, inputs)
