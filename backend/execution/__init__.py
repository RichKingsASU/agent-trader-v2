"""
Execution engine package.

Strategies must emit order *intents* only. This package owns:
- risk validation
- broker routing (paper/live)
- ledger writes for fills
"""

from .engine import (  # noqa: F401
    AlpacaBroker,
    Broker,
    DryRunBroker,
    ExecutionEngine,
    OrderIntent,
    RiskConfig,
    RiskDecision,
)

