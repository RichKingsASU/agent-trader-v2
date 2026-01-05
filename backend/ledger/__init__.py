"""
Trade ledger + P&L attribution (Firestore-first).

This package is intentionally split into:
- models: immutable ledger trade shape used by the calculator
- pnl: pure functions (no Firestore dependency) for deterministic testing
- firestore: path helpers + append-only writer helpers
"""

