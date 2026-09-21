"""
talonx_ingest.intelligence.significance
=======================================
The **Information Significance Engine** — TalonX's deterministic
human-attention ranking layer.

It answers *"which events deserve the user's attention first, and why?"* —
never *"which stock will go up or down?"*.

Hard rules (``PRODUCT_CLAIM_POLICY.md`` / ``RISK_LANGUAGE_POLICY.md`` /
Task 95K / this task's authorization):

* no forward-return / P&L / realized-outcome input, anywhere;
* no direction — "good news" and "bad news" score identically;
* every point is attributable to a named, language-safe reason;
* weights are fixed by ``INFORMATION_SIGNIFICANCE_SPEC.md`` and this
  package's ``config.py`` — never tuned against outcomes;
* deterministic and restart-stable: same inputs -> same score/band/reasons.
"""
from talonx_ingest.intelligence.significance.config import RULESET_VERSION
from talonx_ingest.intelligence.significance.domain import (
    InformationSignificance,
    SignificanceComponent,
    SignificanceReason,
)
from talonx_ingest.intelligence.significance.engine import evaluate_significance

__all__ = [
    "RULESET_VERSION",
    "InformationSignificance",
    "SignificanceComponent",
    "SignificanceReason",
    "evaluate_significance",
]
