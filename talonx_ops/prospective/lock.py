"""
Atomic single-writer lock for the prospective V2 stack.

A process scan alone cannot protect two ``prospective start`` invocations that
race: both scan, both see nothing, both spawn -> two supervisors + two V2
companions writing one ``v2_lane.db``.

``SingleWriterLock`` uses ``os.open(O_CREAT | O_EXCL)`` -- the OS guarantees
exactly one creator -- keyed on the (Windows-case-normalised) V2 ledger
identity.

Lifecycle (Task 117 final-activation correction): the lock is acquired by the
short-lived ``prospective start`` command, held across spawn, then REBOUND
(``rebind_owner``) to the pid of the actual long-lived ledger writer (the V2
companion) before the ``start`` command exits -- so the lock's liveness
tracks the writer, not the CLI invocation that created it. An ``owner_token``
travels with the lock across that rebind so a later, unrelated process (e.g.
``prospective close``, or a fresh ``SingleWriterLock`` instance) can release
it only if it presents the matching token -- release is an entitlement, not a
pid coincidence.

A lock whose owner is verified alive (matching pid AND process create_time,
so a reused pid is never mistaken for the original owner) is NEVER broken,
not even with ``--force``. A lock whose content is missing, unreadable, or
missing required fields is `` unknown`` and ALSO never broken by ``force`` --
unlike a verified-stale lock, an unknown one fails closed pending an explicit,
narrowly-scoped recovery call (``force_clear_unknown``) that still re-verifies
via the process-tree scan before doing anything. Breaking a verified-stale
lock is itself race-safe: the breaking process atomically claims it via
``os.rename`` (only one racer's rename can succeed against a given source
path) before removing it and creating a fresh one -- so no racer can ever
delete another racer's freshly-created replacement lock.
"""
from __future__ import annotations

import json
import os
import socket
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


class ConcurrentStartError(RuntimeError):
    """Another live stack already owns this V2 ledger."""


class StaleLockError(RuntimeError):
    """The lock file exists but its owner cannot be verified gone."""


class LockStateUnknownError(RuntimeError):
    """The lock file exists but its content is unreadable / incomplete.

    Fails closed -- we do not know if an owner is live, so we refuse rather
    than guess. Not overridable by ``force``; use
    :meth:`SingleWriterLock.force_clear_unknown` for an explicit, re-verified
    recovery."""


_REQUIRED_FIELDS = ("pid", "create_time", "ledger_path", "owner_token")
_PID_REUSE_TOLERANCE_S = 1.0


def _pid_alive(pid: int) -> bool:
    try:
        import psutil

        return psutil.pid_exists(pid) and psutil.Process(pid).is_running()
    except Exception:  # noqa: BLE001
        try:
            os.kill(pid, 0)          # POSIX fallback
            return True
        except (OSError, ProcessLookupError):
            return False
        except Exception:  # noqa: BLE001
            return True              # unknown -> assume alive (fail safe)


def _proc_create_time(pid: int) -> float | None:
    try:
        import psutil

        return psutil.Process(pid).create_time()
    except Exception:  # noqa: BLE001
        return None


def _pid_alive_matching(pid: int, create_time) -> bool:
    """True iff ``pid`` is alive AND is (as far as we can tell) the SAME
    process that was recorded -- guards against PID reuse. If ``psutil`` is
    unavailable or ``create_time`` was never recorded, this degrades to a
    plain liveness check (best effort, still fail-safe toward "alive")."""
    if not _pid_alive(pid):
        return False
    if create_time is None:
        return True
    now_ct = _proc_create_time(pid)
    if now_ct is None:
        return True   # can't verify identity -- don't claim a live owner is gone
    return abs(now_ct - create_time) <= _PID_REUSE_TOLERANCE_S


class SingleWriterLock:
    def __init__(self, ledger_path: str | os.PathLike):
        self.ledger_path = Path(ledger_path).resolve()
        # Windows filesystems are case-insensitive/case-preserving -- compare
        # ledger identity case-normalised, never with a bare ``==`` on ``str``.
        self._ledger_key = os.path.normcase(str(self.ledger_path))
        # lock lives next to the ledger, keyed on its identity
        self.lock_path = self.ledger_path.with_suffix(self.ledger_path.suffix + ".startlock")
        self._held = False
        self._payload: dict | None = None
        self._owner_token: str | None = None

    # ------------------------------------------------------------------
    def _read_raw(self) -> tuple[str, dict | None]:
        """Returns (status, payload); status in {'absent','ok','corrupt'}.

        'corrupt' covers: file unreadable, not valid JSON, or missing any of
        the fields we rely on for a safe ownership decision (partial writes
        included -- a payload with only some keys is exactly as dangerous to
        trust as one with none)."""
        if not self.lock_path.exists():
            return "absent", None
        try:
            text = self.lock_path.read_text(encoding="utf-8")
            payload = json.loads(text)
        except Exception:  # noqa: BLE001
            return "corrupt", None
        if not isinstance(payload, dict) or not all(k in payload for k in _REQUIRED_FIELDS):
            return "corrupt", None
        return "ok", payload

    def read_owner(self) -> dict | None:
        status, payload = self._read_raw()
        return payload if status == "ok" else None

    def _owner_state(self) -> str:
        """'free' | 'live' | 'stale' | 'unknown'."""
        status, info = self._read_raw()
        if status == "absent":
            return "free"
        if status == "corrupt":
            return "unknown"
        if os.path.normcase(str(info.get("ledger_path", ""))) != self._ledger_key:
            return "stale"                      # a lock for a different ledger
        pid = info.get("pid")
        ct = info.get("create_time")
        if isinstance(pid, int) and _pid_alive_matching(pid, ct):
            return "live"
        return "stale"

    # ------------------------------------------------------------------
    def _claim_stale_for_removal(self) -> bool:
        """Atomically claim the CURRENT on-disk file for removal via
        ``os.rename`` (only one concurrent renamer of a given source path can
        succeed -- on both POSIX and Windows/NTFS). Returns True iff this
        call both won the claim race AND the claimed content was verified
        (after the rename put it exclusively in our hands) to still be
        stale. Returns False if this call lost the claim race outright (the
        caller must re-evaluate ``_owner_state()`` from scratch).

        Critically: the rename alone is NOT enough. Between our earlier
        ``_owner_state() == 'stale'`` read and this claim, another racer may
        have ALREADY broken the same stale lock and replaced it with its own
        fresh, LIVE one -- a rename-by-path has no idea what it is moving. So
        after winning the rename we re-inspect the claimed content; if it
        turns out to belong to a live owner after all, we restore it
        (best-effort, itself collision-safe via O_CREAT|O_EXCL so a third
        racer's lock is never clobbered) and raise ConcurrentStartError
        instead of silently discarding a live owner's lock."""
        claim_path = self.lock_path.with_name(
            self.lock_path.name + f".break.{os.getpid()}.{uuid.uuid4().hex[:8]}")
        try:
            os.rename(self.lock_path, claim_path)
        except (FileNotFoundError, OSError):
            return False

        live_owner_payload: dict | None = None
        try:
            payload = json.loads(claim_path.read_text(encoding="utf-8"))
            if (isinstance(payload, dict) and all(k in payload for k in _REQUIRED_FIELDS)
                    and isinstance(payload.get("pid"), int)
                    and _pid_alive_matching(payload["pid"], payload.get("create_time"))):
                live_owner_payload = payload
        except Exception:  # noqa: BLE001
            pass   # unreadable claimed content is safe to discard -- never a live owner

        if live_owner_payload is not None:
            # We grabbed someone else's live, freshly-created lock mid-flight.
            # Restore it (never clobbering a third racer's own fresh lock)
            # and refuse -- do not silently proceed as if it were free.
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(live_owner_payload, fh, indent=2)
            except FileExistsError:
                pass   # a third racer's fresh lock already occupies the path -- fine
            finally:
                try:
                    claim_path.unlink()
                except FileNotFoundError:
                    pass
            raise ConcurrentStartError(
                f"lock race: the lock claimed for stale-removal turned out to "
                f"belong to a live owner (pid {live_owner_payload.get('pid')}) -- "
                f"restored; refusing to proceed as if it were free"
            )

        try:
            claim_path.unlink()
        except FileNotFoundError:
            pass
        return True

    def acquire(self, *, force: bool = False, break_stale: bool = True) -> "SingleWriterLock":
        for _attempt in range(8):
            state = self._owner_state()
            if state == "live":
                info = self.read_owner() or {}
                raise ConcurrentStartError(
                    f"a live stack (pid {info.get('pid')}, since {info.get('started_utc')}) "
                    f"already owns {self.ledger_path.name}. --force does NOT override an "
                    f"active ledger writer -- run 'prospective close' first."
                )
            if state == "unknown":
                raise LockStateUnknownError(
                    f"{self.lock_path} exists but its content is unreadable/incomplete -- "
                    f"refusing to guess whether an owner is live. --force does NOT override "
                    f"this. Use SingleWriterLock.force_clear_unknown() after independently "
                    f"confirming no TalonX stack is running."
                )
            if state == "stale":
                if not (break_stale or force):
                    raise StaleLockError(
                        f"stale lock at {self.lock_path} (owner gone); pass force/break_stale"
                    )
                if not self._claim_stale_for_removal():
                    continue   # lost the claim race -- re-evaluate from the top
            # state is now 'free' (originally, or just after a stale claim)
            token = uuid.uuid4().hex
            payload = {
                "pid": os.getpid(),
                "create_time": _proc_create_time(os.getpid()),
                "host": socket.gethostname(),
                "started_utc": datetime.now(timezone.utc).isoformat(),
                "ledger_path": str(self.ledger_path),
                "owner_token": token,
            }
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                continue   # someone else created it between our check and here -- re-evaluate
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
            self._held = True
            self._payload = payload
            self._owner_token = token
            return self
        raise ConcurrentStartError(
            f"lock contention on {self.ledger_path.name} exceeded the retry budget"
        )

    def rebind_owner(self, *, pid: int, create_time: float | None = None) -> None:
        """Update the recorded owning pid (e.g. from the short-lived ``start``
        CLI to the long-lived V2-companion process that actually writes the
        ledger) WITHOUT losing the owner token -- the token, not the pid, is
        what makes a later release() legitimate. Only the current
        token-holder may rebind; the on-disk write is a same-owner atomic
        replace (``os.replace``), never a delete-then-create window."""
        if not self._held or not self._owner_token or self._payload is None:
            raise RuntimeError("cannot rebind a lock this instance does not hold")
        if create_time is None:
            create_time = _proc_create_time(pid)
        payload = dict(self._payload)
        payload.update(pid=pid, create_time=create_time,
                       rebound_utc=datetime.now(timezone.utc).isoformat())
        tmp = self.lock_path.with_suffix(self.lock_path.suffix + f".tmp{os.getpid()}")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, self.lock_path)
        self._payload = payload

    def release(self) -> None:
        """Release only if the on-disk lock's ``owner_token`` still matches
        the token this instance was issued -- entitlement, not pid-equality
        (pid may have been rebound since acquire())."""
        if not self._held:
            return
        status, info = self._read_raw()
        if status == "ok" and info.get("owner_token") == self._owner_token:
            try:
                self.lock_path.unlink()
            except FileNotFoundError:
                pass
        self._held = False

    @classmethod
    def release_by_token(cls, ledger_path: str | os.PathLike, owner_token: str | None) -> bool:
        """Release from a FRESH instance that knows the token but never
        called acquire() in this process (e.g. ``prospective close`` reading
        the token back out of ``session.pids.json``). Never touches a lock
        whose token does not match -- a process is only ever entitled to
        release the lock it (or its own session) actually created."""
        if not owner_token:
            return False
        lk = cls(ledger_path)
        status, info = lk._read_raw()
        if status == "ok" and info.get("owner_token") == owner_token:
            try:
                lk.lock_path.unlink()
            except FileNotFoundError:
                pass
            return True
        return False

    def force_clear_unknown(self, *, confirmed_no_live_stack: bool) -> None:
        """Explicit, narrow recovery for an 'unknown' (corrupt/incomplete)
        lock. Requires the caller to affirmatively pass
        ``confirmed_no_live_stack=True`` -- this method does not itself
        decide that; callers (e.g. the CLI) must have independently verified
        (process scan) that nothing TalonX-owned is running before calling
        it. Archives the unreadable file next to itself instead of silently
        discarding it, then removes it."""
        if self._owner_state() != "unknown":
            return
        if not confirmed_no_live_stack:
            raise LockStateUnknownError(
                "refusing to clear an unknown-state lock without "
                "confirmed_no_live_stack=True from an independent process check"
            )
        archive = self.lock_path.with_name(
            self.lock_path.name + f".unknown.{int(time.time())}.bak")
        try:
            os.rename(self.lock_path, archive)
        except FileNotFoundError:
            pass

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()
        return False
