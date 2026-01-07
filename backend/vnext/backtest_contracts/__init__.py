"""
Deterministic backtest contracts (interfaces only).

This package defines **pure data contracts** and **boundary interfaces** for
running deterministic backtests using the same OBSERVE-only code paths as live.

No implementations live here.
"""

from .interfaces import (  # noqa: F401
    BacktestArtifact,
    BacktestArtifactKind,
    BacktestConfig,
    BacktestRun,
    BacktestRunStatus,
    BacktestRunner,
    run_backtest,
)

