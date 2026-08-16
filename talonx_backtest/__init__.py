"""
talonx_backtest
-------------------
Historical backtesting / quantitative-validation engine for TalonX.

This package deliberately contains NO trading-strategy logic of its own.
Every indicator, threshold, gate, and score in talonx_quant/{strategy,
indicators,config,session,consumer,aggregation}.py is imported and reused
as-is -- see engine.py's module docstring for the full "live vs backtest"
architecture. The strategy itself is FROZEN for this work: this package
only measures it.
"""
from __future__ import annotations

__version__ = "0.1.0"
