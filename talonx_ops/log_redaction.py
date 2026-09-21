"""Central secret redaction for every log record in the process.

Root cause this closes (partial-day RC1 canary): ``httpx`` logs every request URL at INFO, and the Telegram Bot API
puts the bot token IN the URL path (``https://api.telegram.org/bot<token>/sendMessage``); the V2 companion configured
raw ``logging.basicConfig(level=INFO)``, so the token was written in clear to ``results/.../v2_companion.log``.

Lowering one logger's level is not enough (a WARNING/exception path can still carry the URL), so redaction is applied at
the LOG-RECORD level for the whole process, independent of which logger/handler/format is used:

  * a ``logging.setLogRecordFactory`` wrapper redacts the fully formatted message (msg % args) at record creation,
  * ``logging.Formatter.formatException`` / ``formatStack`` are wrapped so exception text and stack text are redacted,
  * ``httpx`` / ``httpcore`` are also raised to WARNING (defence in depth, not the mechanism).

What is redacted: Telegram bot tokens in URLs, ``Authorization`` / ``Bearer`` values, Alpaca key headers, ``token`` /
``secret`` / ``api_key`` / ``password`` / ``chat_id`` query or key=value pairs, and -- exactly -- the VALUE of every
secret-looking environment variable (so a secret embedded in an unusual place is still removed).  Idempotent; import it
(or call ``install()``) from every entry point that performs credentialed HTTP.
"""
from __future__ import annotations

import logging
import os
import re
import threading

REDACTED = "[REDACTED]"

_PATTERNS: tuple[tuple[re.Pattern, str], ...] = (
    # Telegram: /bot<id>:<token>/method  (also bare "<id>:<token>" shaped strings preceded by bot)
    (re.compile(r"bot\d{5,}:[A-Za-z0-9_\-]{20,}"), "bot" + REDACTED),
    # HTTP auth headers (dict repr or "Header: value")
    (re.compile(r"(?i)(authorization['\"]?\s*[:=]\s*['\"]?)(?:bearer|basic|token)?\s*[A-Za-z0-9._~+/=\-]{8,}"), r"\1" + REDACTED),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=\-]{8,}"), "Bearer " + REDACTED),
    (re.compile(r"(?i)(apca-api-(?:key-id|secret-key)['\"]?\s*[:=]\s*['\"]?)[A-Za-z0-9]{6,}"), r"\1" + REDACTED),
    # key=value / "key": "value" for secret-looking names (URL query strings, dict reprs, env dumps)
    (re.compile(r"(?i)((?:api[_-]?key|api[_-]?secret|secret[_-]?key|secret|token|password|passwd|chat[_-]?id|bot[_-]?token)"
                r"['\"]?\s*[=:]\s*['\"]?)[^\s&'\",}\]]{4,}"), r"\1" + REDACTED),
)

_SECRET_NAME = re.compile(r"(TOKEN|SECRET|API_?KEY|PASSWORD|PASSWD|CHAT_ID|KEY_ID)", re.I)
_MIN_SECRET_LEN = 6

_lock = threading.Lock()
_installed = False
_env_cache: tuple[tuple[str, ...], tuple[str, ...]] = ((), ())


def _secret_values() -> tuple[str, ...]:
    """Exact secret values currently in the environment (cached per environment snapshot)."""
    global _env_cache
    snap = tuple(sorted(f"{k}={v}" for k, v in os.environ.items() if _SECRET_NAME.search(k) and len(v.strip()) >= _MIN_SECRET_LEN))
    if snap != _env_cache[0]:
        vals = sorted({v.strip().strip("\"'") for k, v in os.environ.items()
                       if _SECRET_NAME.search(k) and len(v.strip().strip("\"'")) >= _MIN_SECRET_LEN}, key=len, reverse=True)
        _env_cache = (snap, tuple(vals))
    return _env_cache[1]


def redact(text: object, *, extra_secrets: tuple[str, ...] = ()) -> str:
    """Return ``text`` (stringified) with every known secret shape and exact secret value replaced."""
    s = text if isinstance(text, str) else str(text)
    for v in (*extra_secrets, *_secret_values()):
        if v and v in s:
            s = s.replace(v, REDACTED)
    for pat, repl in _PATTERNS:
        s = pat.sub(repl, s)
    return s


def secret_fingerprint(value: str, n: int = 12) -> str:
    """One-way, non-reversible identifier for a secret (safe to log/commit)."""
    import hashlib
    return hashlib.sha256(value.strip().strip("\"'").encode("utf-8")).hexdigest()[:n]


def install() -> None:
    """Install process-wide redaction (idempotent)."""
    global _installed
    with _lock:
        if _installed:
            return
        prev_factory = logging.getLogRecordFactory()

        def factory(*args, **kwargs):
            rec = prev_factory(*args, **kwargs)
            try:
                rec.msg = redact(rec.getMessage())
                rec.args = None
                if rec.exc_text:
                    rec.exc_text = redact(rec.exc_text)
                if rec.stack_info:
                    rec.stack_info = redact(rec.stack_info)
            except Exception:  # noqa: BLE001 -- logging must never raise; fail toward redaction
                rec.msg = REDACTED
                rec.args = None
            return rec

        logging.setLogRecordFactory(factory)

        _orig_exc = logging.Formatter.formatException
        _orig_stack = logging.Formatter.formatStack

        def _safe_exc(self, ei):
            return redact(_orig_exc(self, ei))

        def _safe_stack(self, stack_info):
            return redact(_orig_stack(self, stack_info))

        logging.Formatter.formatException = _safe_exc          # type: ignore[assignment]
        logging.Formatter.formatStack = _safe_stack            # type: ignore[assignment]
        for noisy in ("httpx", "httpcore"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
        _installed = True


install()
