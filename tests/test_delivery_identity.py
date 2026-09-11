"""
tests/test_delivery_identity.py
-------------------------------
Task 96F -- deterministic delivery identity.
"""
from __future__ import annotations

from talonx_ingest.intelligence.delivery.identity import content_hash, delivery_id


def test_delivery_id_shape():
    did = delivery_id("card:SEC:0000320193-26-000101:EARNINGS_RESULTS")
    assert did == "telegram:card:SEC:0000320193-26-000101:EARNINGS_RESULTS:telegram-intel-v1"


def test_delivery_id_changes_with_render_version_and_channel():
    base = delivery_id("card:x")
    assert delivery_id("card:x", render_version="telegram-intel-v2") != base
    assert delivery_id("card:x", channel="digest") != base


def test_content_hash_is_deterministic_and_sensitive():
    a = content_hash("hello world")
    assert a == content_hash("hello world")
    assert a != content_hash("hello  world")
    assert len(a) == 64
