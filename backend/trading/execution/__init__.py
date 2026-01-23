"""
Execution decisioning contracts (NO broker side-effects).

This package is intentionally safe to import in any runtime: it must not
perform network I/O or place orders.
"""

from backend.trading.execution.shadow_options_executor import (  # noqa: F401
    InMemoryShadowTradeHistoryStore,
    ShadowOptionsExecutionResult,
    ShadowOptionsExecutor,
    ShadowTradeHistoryStore,
)


