"""
Options market data helpers (read-only).

This package is intended for *market data only* (contracts, snapshots, quotes) and must
not contain order placement / trading-side effects.
"""

from __future__ import annotations

__all__ = [
    "alpaca_readonly",
    "contract_selection",
    "models",
]

