"""
talonx_ingest.intelligence.insider.roles
========================================
Deterministic insider-role normalisation from the SEC relationship flags
(``isDirector`` / ``isOfficer`` / ``isTenPercentOwner`` / ``isOther``) plus
the free-text ``officerTitle``.

A role is only assigned where the filing's flags support it. An officer
with an unmatched or missing title keeps role ``OFFICER`` and the raw
title is preserved. Nothing is inferred beyond the flags.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from talonx_ingest.intelligence.insider.config import (
    ROLE_PRECEDENCE,
    ROLE_TITLE_PATTERNS,
)
from talonx_ingest.intelligence.insider.domain import InsiderQualityFlag, InsiderRole

__all__ = ["normalize_role", "RoleResult"]


@dataclass(frozen=True)
class RoleResult:
    primary_role: InsiderRole
    roles: tuple[InsiderRole, ...]
    raw_title: str | None
    flags: tuple[str, ...] = field(default_factory=tuple)


def _title_role(title: str) -> InsiderRole | None:
    for pattern, role in ROLE_TITLE_PATTERNS:
        if pattern.search(title):
            return role
    return None


def normalize_role(
    *,
    is_director: bool,
    is_officer: bool,
    is_ten_percent_owner: bool,
    is_other: bool,
    officer_title: str | None,
) -> RoleResult:
    roles: set[InsiderRole] = set()
    flags: list[str] = []
    raw_title = (officer_title or "").strip() or None

    if is_officer:
        matched = _title_role(raw_title) if raw_title else None
        roles.add(matched or InsiderRole.OFFICER)
        if matched is None and not raw_title:
            flags.append(InsiderQualityFlag.ROLE_UNRESOLVED.value)
    if is_director:
        roles.add(InsiderRole.DIRECTOR)
    if is_ten_percent_owner:
        roles.add(InsiderRole.TEN_PERCENT_OWNER)
    if is_other:
        roles.add(InsiderRole.OTHER)
    if not roles:
        roles.add(InsiderRole.OTHER)
        flags.append(InsiderQualityFlag.ROLE_UNRESOLVED.value)

    ordered = tuple(r for r in ROLE_PRECEDENCE if r in roles)
    return RoleResult(
        primary_role=ordered[0],
        roles=ordered,
        raw_title=raw_title,
        flags=tuple(flags),
    )
