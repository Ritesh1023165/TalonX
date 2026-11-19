"""
talonx_scorecard -- TICKER_SCORECARD_V1 (multi-horizon bullish/bearish view per ticker).

Governed by the owner-approved pre-registration
``docs/research/preregistration/2026-11-03_ticker_scorecard_v1.md`` (commit 4a3bec3125e181baea695dab3f2bebb1f9037395).
Nothing in ``config.py`` may change after approval; ``config.spec_fingerprint()`` pins it.

Isolation (pre-registration, "Run budget, failures and isolation"): this package never imports ``talonx_opportunity``
or ``talonx_v2`` and is not registered with any supervisor. It is offline research code until the programme decision
of 2026-11-18.
"""
