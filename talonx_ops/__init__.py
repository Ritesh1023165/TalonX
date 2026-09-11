"""talonx_ops -- operational tooling for the NORMAL full run_talonx.py
application (Task 66B-PREP): read-only preflight, runtime manifest,
provider/execution-path explicitness helpers, and the PIV-vs-full-app
cross-path comparator.

Deliberately separate from talonx_piv (the PAPER PIV validation harness)
-- this package documents/checks the real application's own runtime, not
a narrower validation-only path. Nothing here changes strategy semantics
or execution behavior; the only production-code touchpoint is
run_talonx.py importing the small, non-invasive helpers in
provider_status.py/runtime_metadata.py for explicit logging."""
