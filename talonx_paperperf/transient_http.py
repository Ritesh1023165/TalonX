"""
Classified, bounded retries for transient transport/provider failures (2026-10-05, V2 forward tracker reliability).

Root cause it addresses: on 2026-10-05 06:00Z the V2 forward ``prices`` stage died on one
``URLError(<urlopen error _ssl.c:993: The handshake operation timed out>)`` -- AlpacaData's default transport retries
only HTTP 429 and lets every transport error escape, so one handshake timeout killed the whole daily cycle.

Classification (``classify``):
  RETRYABLE   TLS handshake timeout, socket/read timeout, connection reset/aborted/refused, remote disconnect,
              incomplete read, temporary DNS failure, HTTP 429 (Retry-After honoured), HTTP 500/502/503/504
  NEVER       certificate verification failures (TLS verification stays ON), other TLS errors, HTTP 400/401/403/404/
              422 and every other 4xx (authentication / invalid request), anything unclassified
Budget (``RetryPolicy``): at most ``max_attempts`` per request, exponential backoff ``base_s * 2**(n-1)`` capped at
``cap_s``, a per-request wall budget ``budget_s`` and an optional absolute ``deadline`` (the caller's stage deadline,
e.g. before the study's day cutoff). A wait that would cross either bound is NOT taken: the call ends with
``TransientExhausted`` (the reason is recorded). A Retry-After longer than ``retry_after_cap_s`` is never shortened:
the request is exhausted instead.

This module REPLACES (does not nest inside) AlpacaData's own 429 loop when used as ``AlpacaData._get``; the caller's
rate limiter is re-acquired before every retry, so retries also respect the provider rate limit.
"""
from __future__ import annotations

import email.utils
import http.client
import json
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

RETRYABLE_HTTP = {429, 500, 502, 503, 504}


class TransientExhausted(RuntimeError):
    """A retryable failure persisted past the attempt / time budget (or a Retry-After the budget cannot honour)."""

    def __init__(self, msg: str, *, error_class: str, attempts: int):
        super().__init__(msg)
        self.error_class, self.attempts = error_class, attempts


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 5
    base_s: float = 2.0
    cap_s: float = 30.0
    budget_s: float = 240.0
    retry_after_cap_s: float = 120.0


DEFAULT_POLICY = RetryPolicy()


def _retry_after(headers) -> float | None:
    v = (headers or {}).get("Retry-After") if headers is not None else None
    if v is None:
        return None
    v = str(v).strip()
    if v.isdigit():
        return float(v)
    try:
        dt = email.utils.parsedate_to_datetime(v)
        return max(0.0, (dt - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        return None


def classify(exc: BaseException) -> tuple[str, bool, float | None]:
    """(error_class, retryable, retry_after_seconds)."""
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code in RETRYABLE_HTTP:
            return (f"HTTP_{exc.code}", True, _retry_after(exc.headers) if exc.code in (429, 503) else None)
        return f"HTTP_{exc.code}", False, None
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(reason, ssl.SSLCertVerificationError):
        return "TLS_CERTIFICATE", False, None
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return "TIMEOUT", True, None
    if isinstance(reason, ssl.SSLError):
        text = str(reason).lower()
        if "timed out" in text or "handshake" in text and "timeout" in text:
            return "TLS_HANDSHAKE_TIMEOUT", True, None
        if "eof occurred in violation of protocol" in text or "unexpected eof" in text:
            return "TLS_EOF", True, None
        return "TLS_ERROR", False, None
    if isinstance(reason, (ConnectionResetError, ConnectionAbortedError, ConnectionRefusedError, BrokenPipeError)):
        return "CONNECTION", True, None
    if isinstance(reason, (http.client.RemoteDisconnected, http.client.IncompleteRead)):
        return "REMOTE_DISCONNECTED", True, None
    if isinstance(reason, socket.gaierror):
        return "DNS", True, None
    if isinstance(reason, str) and "timed out" in reason.lower():
        return "TIMEOUT", True, None
    return type(exc).__name__.upper(), False, None


def _log(event: dict) -> None:
    print(json.dumps({"transient_retry": event}), file=sys.stderr, flush=True)


def call_with_retry(fn, *, policy: RetryPolicy = DEFAULT_POLICY, deadline: float | None = None,
                    before_retry=None, sleep=time.sleep, clock=time.monotonic, what: str = "request"):
    """Run ``fn()``; retry ONLY classified-transient failures within the policy and ``deadline`` (a ``clock()`` value).
    Non-retryable errors propagate unchanged on the first occurrence."""
    start = clock()
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 -- classified below; non-retryable re-raised unchanged
            cls, retryable, ra = classify(exc)
            if not retryable:
                raise
            if attempt == policy.max_attempts:
                _log({"what": what, "class": cls, "attempt": attempt, "outcome": "EXHAUSTED_ATTEMPTS"})
                raise TransientExhausted(f"{what}: {cls} persisted after {attempt} attempts", error_class=cls,
                                         attempts=attempt) from exc
            if ra is not None and ra > policy.retry_after_cap_s:
                _log({"what": what, "class": cls, "attempt": attempt, "retry_after_s": ra,
                      "outcome": "EXHAUSTED_RETRY_AFTER_TOO_LONG"})
                raise TransientExhausted(f"{what}: {cls} Retry-After {ra:.0f}s exceeds the cap", error_class=cls,
                                         attempts=attempt) from exc
            wait = ra if ra is not None else min(policy.cap_s, policy.base_s * 2 ** (attempt - 1))
            now = clock()
            if now - start + wait > policy.budget_s or (deadline is not None and now + wait > deadline):
                _log({"what": what, "class": cls, "attempt": attempt, "wait_s": wait, "outcome": "EXHAUSTED_BUDGET"})
                raise TransientExhausted(f"{what}: {cls}; next wait {wait:.0f}s would exceed the time budget",
                                         error_class=cls, attempts=attempt) from exc
            _log({"what": what, "class": cls, "attempt": attempt, "wait_s": wait, "outcome": "RETRY"})
            sleep(wait)
            if before_retry is not None:
                before_retry()
    raise AssertionError("unreachable")


def resilient_alpaca_get(*, limiter=None, policy: RetryPolicy = DEFAULT_POLICY, deadline: float | None = None,
                         urlopen=urllib.request.urlopen, sleep=time.sleep, clock=time.monotonic, timeout: float = 30.0):
    """Drop-in for ``AlpacaData._get`` (url, params, headers) -> dict. TLS verification uses the default context.
    Non-retryable HTTP errors keep AlpacaData's contract: ``RuntimeError("HTTP <code>: <body>")``."""
    def get(url: str, params: dict, headers: dict) -> dict:
        u = url + "?" + urllib.parse.urlencode(params)

        def once():
            with urlopen(urllib.request.Request(u, headers=headers), timeout=timeout) as r:
                return json.loads(r.read())
        try:
            return call_with_retry(once, policy=policy, deadline=deadline, sleep=sleep, clock=clock,
                                   before_retry=(limiter.acquire if limiter is not None else None),
                                   what=urllib.parse.urlsplit(url).path)
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HTTP {e.code}: {e.read()[:200].decode(errors='replace')}") from None
    return get
