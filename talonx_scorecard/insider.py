"""F10: net open-market insider buyers over 90 days from SEC Form 3/4/5 bulk data sets.

Distinct reporting owners with a code-P (purchase) Form 4 minus distinct owners with a code-S (sale) Form 4, counted over
filings dated in (t-90d, t). Only filing dates are available, so a filing counts from the session AFTER its filing date.
"""
from __future__ import annotations

import io
import zipfile

import numpy as np
import pandas as pd

WINDOW_DAYS = 90


def parse_form345_zip(raw: bytes) -> pd.DataFrame:
    """One quarterly ``*_form345.zip`` -> rows (issuer_cik, owner_cik, filed, code) for Form 4 code P / S."""
    z = zipfile.ZipFile(io.BytesIO(raw))
    def tsv(name, cols):
        with z.open(name) as fh:
            return pd.read_csv(fh, sep="\t", usecols=cols, dtype=str, low_memory=False)
    sub = tsv("SUBMISSION.tsv", ["ACCESSION_NUMBER", "FILING_DATE", "DOCUMENT_TYPE", "ISSUERCIK"])
    sub = sub[sub["DOCUMENT_TYPE"] == "4"]
    tr = tsv("NONDERIV_TRANS.tsv", ["ACCESSION_NUMBER", "TRANS_CODE"])
    tr = tr[tr["TRANS_CODE"].isin(["P", "S"])]
    ow = tsv("REPORTINGOWNER.tsv", ["ACCESSION_NUMBER", "RPTOWNERCIK"])
    m = tr.merge(sub, on="ACCESSION_NUMBER").merge(ow, on="ACCESSION_NUMBER")
    out = pd.DataFrame({"issuer_cik": pd.to_numeric(m["ISSUERCIK"], errors="coerce"),
                        "owner_cik": pd.to_numeric(m["RPTOWNERCIK"], errors="coerce"),
                        "filed": pd.to_datetime(m["FILING_DATE"], format="%d-%b-%Y", errors="coerce"),
                        "code": m["TRANS_CODE"]})
    return out.dropna().astype({"issuer_cik": "int64", "owner_cik": "int64"}).drop_duplicates()


def net_buyers_wide(events: pd.DataFrame, sessions: pd.DatetimeIndex, ciks) -> pd.DataFrame:
    """sessions x issuer-cik panel of (#distinct buyers - #distinct sellers) active in the last 90 days. Zero when none."""
    ciks = list(ciks)
    col = {c: i for i, c in enumerate(ciks)}
    diff = np.zeros((len(sessions) + 1, len(ciks)))
    ses = sessions.values
    for (iss, own, code), g in events[events["issuer_cik"].isin(col)].groupby(["issuer_cik", "owner_cik", "code"]):
        sign = 1.0 if code == "P" else -1.0
        cur_s = cur_e = None
        for f in np.sort(g["filed"].values):
            s = np.searchsorted(ses, f, side="right")                               # first session strictly after filing
            e = np.searchsorted(ses, f + np.timedelta64(WINDOW_DAYS, "D"), side="right")
            if cur_e is not None and s <= cur_e:
                cur_e = max(cur_e, e)
            else:
                if cur_e is not None:
                    diff[cur_s, col[iss]] += sign; diff[cur_e, col[iss]] -= sign
                cur_s, cur_e = s, e
        if cur_e is not None:
            diff[cur_s, col[iss]] += sign; diff[cur_e, col[iss]] -= sign
    return pd.DataFrame(np.cumsum(diff, axis=0)[:-1], index=sessions, columns=ciks)
