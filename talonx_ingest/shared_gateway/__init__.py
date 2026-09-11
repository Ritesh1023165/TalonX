"""
talonx_ingest.shared_gateway
--------------------------------
Task 88 MVP: a single Shared Alpaca Market Data Gateway that owns ONE
Alpaca connection and publishes normalized events onto a durable Redis
Stream, so Original and PIV can each read the same acquisition with
independent offsets instead of maintaining separate market-data paths.

SHADOW_INGESTION_ONLY: this package is pure market-data plumbing. Nothing
here imports talonx_piv.broker, talonx_piv.lifecycle, talonx_paper, or any
other execution/lifecycle module, and nothing here writes to a
signals/alerts/trades channel. See results/task88_shared_gateway/design.md.
"""
from __future__ import annotations
