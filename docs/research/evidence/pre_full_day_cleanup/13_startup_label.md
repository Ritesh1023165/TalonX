# Startup label (TASK L) - **STARTUP CAMPAIGN LABEL: V2-PAPER-RC1 (fixed)**
Presentation-only + hardcoded fallback: `prospective start` read the campaign from `resolve_env()` (a dict of only 4 variables that never includes it) and fell back to `"V2"`. It did not affect routing or business logic.
Fix: `_campaign_label(env)` prefers the real `TALONX_V2_CAMPAIGN_ID` (legacy default `V2` unchanged when unset). Test: `test_14`.
