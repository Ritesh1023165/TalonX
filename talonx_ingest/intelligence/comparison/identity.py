"""
talonx_ingest.intelligence.comparison.identity
==============================================
Deterministic, restart-stable identity for a filing comparison.

``comparison_id = "CMP:{current_accession}:{prior_accession|NONE}:{schema_version}"``

Same filing pair + same engine schema version -> same id (safe upsert). A
schema-version bump changes the id, so an old comparison and a
re-computed one are both addressable and never silently overwrite.
"""
from __future__ import annotations

from talonx_ingest.intelligence.comparison.config import COMPARISON_SCHEMA_VERSION
from talonx_ingest.intelligence.identity import normalize_accession, source_hash

__all__ = ["comparison_id", "content_hash"]


def comparison_id(
    current_accession: str,
    prior_accession: str | None,
    *,
    schema_version: str = COMPARISON_SCHEMA_VERSION,
) -> str:
    cur = normalize_accession(current_accession)
    pri = normalize_accession(prior_accession) if prior_accession else "NONE"
    return f"CMP:{cur}:{pri}:{schema_version}"


def content_hash(*parts: object) -> str:
    """sha256 hex (LF-normalised) of the parts -- reused from Task 96A so
    document/section hashes are consistent across the codebase."""
    return source_hash(*parts)
