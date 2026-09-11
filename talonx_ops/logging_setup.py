"""Task 87B FC_07 -- bounded, lower-noise logging for the live runtime.

Task 87A: a ~13h session produced ~10.7 MB of logs, ~73% of it noise --
~20,000 ``regime_shadow symbol=...`` INFO lines (one per symbol per
evaluation cycle), ~1,500 ``httpx`` getUpdates 200 lines, ~1,000
HuggingFace ``Batches:`` progress frames -- and there was no rotation, so
``.run/logs`` grows unbounded across multi-day operation and the signal
is buried for forensics.

``configure_logging`` (drop-in for ``logging.basicConfig``):
  * keeps the existing console handler / format,
  * adds a size-bounded ``RotatingFileHandler`` (default 20 MB x 5),
  * raises chatty third-party loggers (httpx / httpcore / urllib3 /
    yfinance) to WARNING -- their genuine problems still show,
  * installs ``RegimeShadowThrottleFilter`` which collapses the
    per-symbol ``regime_shadow`` INFO stream into one aggregated line per
    window, unless ``TALONX_LOG_VERBOSE=1``.

ERROR / WARNING records are NEVER filtered. Lifecycle / EOD /
reconciliation lines are ordinary INFO on their own loggers and pass
through untouched.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import time
from pathlib import Path

_DEFAULT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_NOISY_THIRD_PARTY = ("httpx", "httpcore", "urllib3", "yfinance", "sentence_transformers")

_REGIME_SHADOW_PREFIX = "regime_shadow symbol="


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


class RegimeShadowThrottleFilter(logging.Filter):
    """Suppress the high-volume per-symbol ``regime_shadow symbol=...``
    INFO lines, emitting one aggregated summary per ``window_seconds``
    instead. Any record at WARNING+ is always allowed. Set
    ``TALONX_LOG_VERBOSE=1`` to disable the throttle entirely."""

    def __init__(self, window_seconds: float = 60.0) -> None:
        super().__init__()
        self.window_seconds = window_seconds
        self._verbose = os.environ.get("TALONX_LOG_VERBOSE", "").strip().lower() in ("1", "true", "yes", "on")
        self._count = 0
        self._disagreements = 0
        self._window_start = time.monotonic()
        self._logger = logging.getLogger("talonx_quant.regime_shadow_summary")

    def filter(self, record: logging.LogRecord) -> bool:
        if self._verbose or record.levelno >= logging.WARNING:
            return True
        msg = record.getMessage()
        if not msg.startswith(_REGIME_SHADOW_PREFIX):
            return True
        self._count += 1
        if "disagreement=" in msg and "disagreement=BOTH_PASS" not in msg and "disagreement=BOTH_FAIL" not in msg:
            self._disagreements += 1
        now = time.monotonic()
        if now - self._window_start >= self.window_seconds and self._count:
            self._logger.info(
                "regime_shadow: %d symbol evaluation(s) in the last %.0fs (%d disagreement(s)) "
                "-- per-symbol lines suppressed; set TALONX_LOG_VERBOSE=1 to see them",
                self._count, now - self._window_start, self._disagreements,
            )
            self._count = 0
            self._disagreements = 0
            self._window_start = now
        return False  # drop the individual per-symbol line


def configure_logging(
    *,
    level: int = logging.INFO,
    log_dir: str | os.PathLike | None = None,
    max_bytes: int | None = None,
    backup_count: int | None = None,
    add_file_handler: bool = True,
) -> logging.handlers.RotatingFileHandler | None:
    """Idempotent-ish central setup. Returns the RotatingFileHandler (or
    None if file logging was disabled)."""
    root = logging.getLogger()
    root.setLevel(level)

    # Handler-level filter: applied to EVERY record a handler processes,
    # including ones propagated up from child loggers (a logger-level
    # filter would not see those).
    shadow_filter = RegimeShadowThrottleFilter(
        window_seconds=float(os.environ.get("TALONX_LOG_REGIME_SHADOW_WINDOW_SECONDS", "60"))
    )

    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
               for h in root.handlers):
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter(_DEFAULT_FORMAT))
        console.addFilter(shadow_filter)
        root.addHandler(console)
    else:
        for h in root.handlers:
            if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
                if not any(isinstance(f, RegimeShadowThrottleFilter) for f in h.filters):
                    h.addFilter(shadow_filter)

    file_handler = None
    _file_disabled = (
        os.environ.get("TALONX_LOG_NO_FILE", "").strip().lower() in ("1", "true", "yes")
        # never scribble a rotating log file into the repo during a test run
        # unless a test explicitly asked for one (it passes an explicit log_dir).
        or ("pytest" in sys.modules and log_dir is None)
    )
    if add_file_handler and not _file_disabled:
        d = Path(log_dir or os.environ.get("TALONX_LOG_DIR", ".run/logs"))
        try:
            d.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                d / "talonx.log",
                maxBytes=max_bytes if max_bytes is not None else _env_int("TALONX_LOG_MAX_BYTES", 20 * 1024 * 1024),
                backupCount=backup_count if backup_count is not None else _env_int("TALONX_LOG_BACKUP_COUNT", 5),
                encoding="utf-8",
            )
            file_handler.setFormatter(logging.Formatter(_DEFAULT_FORMAT))
            file_handler.addFilter(shadow_filter)
            if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers):
                root.addHandler(file_handler)
        except OSError:
            file_handler = None

    # chatty third-party loggers -> WARNING (their real errors still show)
    for name in _NOISY_THIRD_PARTY:
        logging.getLogger(name).setLevel(logging.WARNING)

    return file_handler
