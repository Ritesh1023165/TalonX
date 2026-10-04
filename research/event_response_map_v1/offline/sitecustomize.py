"""EVENT_RESPONSE_MAP_V1 scoring-only OFFLINE guard (runner-supplied via PYTHONPATH; NOT part of the design lock).

Loaded automatically at interpreter start when this directory is on PYTHONPATH (the venv has no sitecustomize of its
own). Every network path fails LOUDLY: socket connect / connect_ex / create_connection and DNS resolution raise
RuntimeError("NETWORK_REFUSED_SCORING_ONLY ..."). Child processes (the parallel evaluate workers) inherit PYTHONPATH,
so they are guarded too. Windows multiprocessing uses named pipes, not sockets, so local IPC is unaffected.
"""
import socket as _socket
import sys as _sys


def _refuse(*args, **kwargs):
    raise RuntimeError(f"NETWORK_REFUSED_SCORING_ONLY: a network call was attempted ({args[:2]!r})")


_socket.socket.connect = _refuse
_socket.socket.connect_ex = _refuse
_socket.create_connection = _refuse
_socket.getaddrinfo = _refuse
_socket.gethostbyname = _refuse
_socket.gethostbyname_ex = _refuse
print("OFFLINE_GUARD_ACTIVE (EVENT_RESPONSE_MAP_V1 scoring-only)", file=_sys.stderr, flush=True)
