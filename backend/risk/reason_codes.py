"""
Risk reason codes used across risk checks.

These are stable, machine-readable identifiers intended for:
- audit logs
- dashboards
- alert routing
- downstream policy decisions

They are deliberately decoupled from any broker/execution semantics.
"""

from __future__ import annotations


class RiskReasonCode:
    """
    Canonical string reason codes for risk decisions.

    Note: keep these values stable; consumers may persist them.
    """

    OK = "OK"

    # Generic / input validation
    INVALID_INPUT = "INVALID_INPUT"

    # Options-specific guards
    MAX_CONTRACTS_PER_TRADE = "MAX_CONTRACTS_PER_TRADE"
    MAX_CONTRACTS_PER_DAY = "MAX_CONTRACTS_PER_DAY"
    MAX_NET_DELTA = "MAX_NET_DELTA"
    MAX_GAMMA_EXPOSURE = "MAX_GAMMA_EXPOSURE"
    TIME_OF_DAY_CUTOFF = "TIME_OF_DAY_CUTOFF"


__all__ = ["RiskReasonCode"]

