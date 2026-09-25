"""
Runtime gates for the effective fetch universe. In DRY_RUN (default) every gate is an exact identity and never opens
the operator store -- live fetch batches, discovery input and promotion are untouched.

EFFECTIVE = (BASE + operator-added) - operator-removed - excluded      (excluded wins over everything)
"""
from __future__ import annotations

from talonx_ops.operator_control import ACTIVE, mutation_mode
from talonx_ops.operator_control.store import OperatorStore


def _state(env=None, store=None):
    if mutation_mode(env) != ACTIVE:
        return None
    s = store or OperatorStore(readonly=True)
    return s.added(), s.removed(), s.excluded()


def effective_symbols(base, *, env=None, store=None, include_added: bool = True) -> list[str]:
    """Filter (and in ACTIVE, extend) a provider fetch list BEFORE the batch is built."""
    st = _state(env, store)
    if st is None:
        return list(base)
    added, removed, excluded = st
    out, seen = [], set()
    for s in list(base) + (sorted(added) if include_added else []):
        u = str(s).upper()
        if u in seen or u in excluded or u in removed:
            continue
        seen.add(u)
        out.append(s)
    return out


def effective_members(members: dict, *, env=None, store=None) -> dict:
    """Discovery's eligible-member map: excluded / removed symbols are skipped before scoring and SEC lookups;
    operator-added symbols not in the base universe get a minimal ELIGIBLE member (no CIK -> no SEC lookup)."""
    st = _state(env, store)
    if st is None:
        return members
    added, removed, excluded = st
    out = {k: v for k, v in members.items() if k.upper() not in excluded and k.upper() not in removed}
    for s in sorted(added - excluded):
        out.setdefault(s, {"symbol": s, "name": s, "exchange": "", "cik": None, "status": "ELIGIBLE",
                           "reason": "OPERATOR_ADDED"})
    return out


def is_excluded(symbol: str, *, env=None, store=None) -> bool:
    st = _state(env, store)
    return bool(st) and symbol.upper() in st[2]
