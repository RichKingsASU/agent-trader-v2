"""
AgentTrader v2 canonical domain contracts (design-only).

These are broker-agnostic, immutable (frozen) schemas intended to be shared across
enterprise-scale agents and services.
"""

from __future__ import annotations

from backend.contracts.v2.execution import ExecutionAttempt, ExecutionFill, ExecutionResult
from backend.contracts.v2.explainability import StrategyExplanation
from backend.contracts.v2.risk import RiskDecision
from backend.contracts.v2.shadow import ShadowTrade
from backend.contracts.v2.trading import OrderIntent, TradingSignal

__all__ = [
    "ExecutionAttempt",
    "ExecutionFill",
    "ExecutionResult",
    "OrderIntent",
    "RiskDecision",
    "ShadowTrade",
    "StrategyExplanation",
    "TradingSignal",
]

