"""Task 76S Stage 2 -- per-ticker PAPER-entry setting.

`paper_entry_enabled` controls ONE thing only: whether a NEW PAPER entry
(a BUY-to-open) is permitted to reach the broker for a given ticker. It:
  - never changes any alpha calculation or the recorded `recommendation`
    (talonx_piv.decision_contract.decide computes the same recommendation
    regardless of this setting -- it only downgrades `execution_status`,
    see that module);
  - never suppresses a protective exit, EOD cleanup, or reconciliation
    (lifecycle.py's SELL/exit path and every bulk-flatten call site never
    consult this setting at all -- see execution_path_inventory.md Stage 3);
  - defaults to DISABLED for any ticker that is missing or malformed in the
    settings file, and defaults to a fully-disabled settings object when no
    file/mapping is supplied at all.

Migration note (no prior per-ticker setting existed anywhere in this
repository before this task -- confirmed in execution_path_inventory.md
Stage 0 item 5): the safe migration posture is that NO ticker is silently
carried forward as "enabled" just because it was previously unrestricted.
An operator must explicitly populate the settings file before any PAPER
entry can occur for a given ticker -- see paper_setting_migration.md for
the full write-up.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path


@dataclass(frozen=True)
class PaperEntrySettings:
    """Immutable snapshot of per-ticker `paper_entry_enabled` values.
    `enabled_for` is fail-closed: any ticker not present, or present with a
    value that is not the literal boolean `True`, is disabled."""
    entries: dict[str, bool] = field(default_factory=dict)

    def enabled_for(self, ticker: str) -> bool:
        return self.entries.get(ticker.upper()) is True

    @classmethod
    def all_disabled(cls) -> "PaperEntrySettings":
        return cls(entries={})

    @classmethod
    def for_test(cls, *enabled_tickers: str) -> "PaperEntrySettings":
        """TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE. Convenience constructor
        for isolated test fixtures only -- never used by production code
        (cli.py always goes through `load_paper_entry_settings`, which is
        fail-closed against a real file, never this in-memory shortcut)."""
        return cls(entries={t.upper(): True for t in enabled_tickers})


def load_paper_entry_settings(path: Path) -> PaperEntrySettings:
    """Loads `{"TICKER": true/false, ...}` from `path`. Fail-closed on every
    ambiguous case -- a missing file, a malformed (non-dict) JSON body, a
    non-boolean value for a given ticker, or an unreadable/corrupt file all
    resolve to that ticker being disabled (never an exception that could be
    mistaken for a transient error and retried into an unsafe state)."""
    if not path.exists():
        return PaperEntrySettings.all_disabled()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return PaperEntrySettings.all_disabled()
    if not isinstance(raw, dict):
        return PaperEntrySettings.all_disabled()
    entries: dict[str, bool] = {}
    for ticker, value in raw.items():
        if not isinstance(ticker, str):
            continue
        entries[ticker.upper()] = value is True
    return PaperEntrySettings(entries=entries)
