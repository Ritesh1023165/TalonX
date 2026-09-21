"""
Task 117 output-closure -- D2: the Windows venv shim + worker are ONE logical
Telegram get_updates owner, not two.

``count_telegram_get_updates_owners()`` greps process command lines for
``run_talonx.py``. On Windows the ``.venv`` launcher (``python.exe run_talonx.py``)
spawns a worker child under a different interpreter that ALSO matches. That pair
is one poller; a match whose ancestor is also a match is a shim child.
"""
from __future__ import annotations

import pytest

import talonx_ops.supervisor as sup


class _FakeProc:
    def __init__(self, pid, cmdline, parent_pid, table):
        self.pid = pid
        self.info = {"cmdline": cmdline, "pid": pid, "name": "python.exe"}
        self._parent_pid = parent_pid
        self._table = table

    def parent(self):
        return self._table.get(self._parent_pid)


def _install(monkeypatch, procs):
    table = {}
    objs = []
    for pid, cmd, ppid in procs:
        p = _FakeProc(pid, cmd, ppid, table)
        table[pid] = p
        objs.append(p)

    class _PS:
        @staticmethod
        def process_iter(attrs=None):
            return list(objs)

    monkeypatch.setattr(sup, "psutil", _PS, raising=False)
    # count_telegram_get_updates_owners does ``import psutil`` locally
    import sys
    monkeypatch.setitem(sys.modules, "psutil", _PS)


VENV = [r"C:\workspace\TalonX\.venv\Scripts\python.exe", "run_talonx.py"]
WORKER = [r"C:\Users\x\AppData\Local\Python\pythoncore-3.12-64\python.exe", "run_talonx.py"]


def test_shim_plus_worker_counts_as_one(monkeypatch):
    _install(monkeypatch, [
        (100, VENV, 1),        # the venv launcher shim
        (101, WORKER, 100),    # its worker child -- same script, parent is a match
    ])
    assert sup.count_telegram_get_updates_owners() == 1


def test_two_independent_launchers_count_as_two(monkeypatch):
    _install(monkeypatch, [
        (100, VENV, 1), (101, WORKER, 100),      # launcher A + child
        (200, VENV, 1), (201, WORKER, 200),      # launcher B + child  -> genuine 2nd owner
    ])
    assert sup.count_telegram_get_updates_owners() == 2


def test_none_running_is_zero(monkeypatch):
    _install(monkeypatch, [
        (1, [r"C:\Program Files\Git\bin\bash.exe", "-c", "echo run_talonx.py mentioned"], 0),
    ])
    assert sup.count_telegram_get_updates_owners() == 0   # substring mention is not a launch


def test_skip_dispatch_is_excluded(monkeypatch):
    _install(monkeypatch, [
        (100, VENV + ["--skip-dispatch"], 1),
    ])
    assert sup.count_telegram_get_updates_owners() == 0
