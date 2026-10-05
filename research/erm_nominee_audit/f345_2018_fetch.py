"""Targeted SEC metadata acquisition (V2 identity evidence): the four 2018 Form 3/4/5 quarterly insider data sets, so
that events early in 2019 have a dated ticker observation BEFORE the gap day. Metadata only (issuer CIK, issuer
trading symbol, filing date). Frozen phase_d.Sec client: R5 off-hours refusal, declared User-Agent, <= 3 req/s, bytes
archived with sha256 in a SEPARATE archive results/erm_nominee_audit/_sec_v2/ (frozen archive never written)."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
from research.event_response_map_v1.phase_d import FORM345_URL, Sec  # noqa: E402

OUT = HERE / "results" / "erm_nominee_audit"
sec = Sec(OUT / "_sec_v2")
got = {}
try:
    for q in ("2018q1", "2018q2", "2018q3", "2018q4"):
        got[q] = len(sec.get(FORM345_URL.format(q), f"{q}_form345.zip"))
finally:
    sec.flush()
(OUT / "f345_2018_fetch_result.json").write_text(json.dumps(got, indent=1))
print(got)
