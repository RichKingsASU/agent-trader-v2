"""
DEPRECATED: import from `backend.contracts.risk` instead.

This file remains as a compatibility shim so router imports don't break.
"""

from backend.contracts.risk import RiskCheckResult, TradeCheckRequest

__all__ = ["TradeCheckRequest", "RiskCheckResult"]
