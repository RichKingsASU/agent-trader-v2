"""
Deterministic backtest interfaces (contracts only).

Governance invariants (see `backend/vnext/GOVERNANCE.md`):
- OBSERVE-only: backtests produce data artifacts; they do not execute trades.
- No live dependencies by default: backtests must be reproducible offline.

Important constraint for determinism:
- Backtests must be *pure functions of* (strategy_id, config, data_snapshot).
  Any randomness must be fully controlled by `BacktestConfig.random_seed`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


class BacktestRunStatus(str, Enum):
    """
    Lifecycle status for a backtest run.
    """

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BacktestArtifactKind(str, Enum):
    """
    Standardized artifact kinds produced by a backtest.
    """

    RUN_METADATA_JSON = "run_metadata_json"
    CONFIG_JSON = "config_json"
    SUMMARY_JSON = "summary_json"
    TRADES_CSV = "trades_csv"
    ORDERS_CSV = "orders_csv"
    EQUITY_CURVE_CSV = "equity_curve_csv"
    POSITIONS_CSV = "positions_csv"
    LOG_TEXT = "log_text"
    NOTEBOOK_HTML = "notebook_html"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    """
    Deterministic configuration for a single backtest.

    Notes:
    - This config is intended to be stable/serializable for audit and replay.
    - Parameter tuning/optimization must not happen inside a backtest run.

    Required determinism inputs:
    - `data_snapshot_id`: identifies the exact dataset snapshot used.
    - `engine_version`: identifies the exact backtest/observe engine version.
    - `random_seed`: controls any randomness (must be treated as the only
      randomness source, if any randomness is used at all).
    """

    start_time: datetime
    end_time: datetime

    # Data determinism anchor (e.g., "alpaca-bars@2026-01-01T00:00Z#sha256:...").
    data_snapshot_id: str

    # Code determinism anchor (e.g., git SHA, build fingerprint, semver).
    engine_version: str

    # Strategy parameters must be fixed for the run (no tuning).
    strategy_params: Mapping[str, Any] = field(default_factory=dict)

    # Portfolio / execution simulation assumptions.
    initial_cash: float = 100_000.0
    base_currency: str = "USD"

    # Universe selection for the run (symbol identifiers are strategy-defined).
    universe: tuple[str, ...] = ()

    # Optional bar/tick resolution label (e.g., "1Min", "5Min", "1Day").
    timeframe: str | None = None

    # Optional controls for simulated costs (kept generic for portability).
    fees_model_id: str | None = None
    slippage_model_id: str | None = None

    # Randomness control for determinism (if randomness is used).
    random_seed: int = 0

    # Free-form deterministic toggles (must be included in the audit trail).
    flags: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BacktestArtifact:
    """
    One immutable artifact produced by a backtest run.

    Artifacts are referenced by URI to avoid embedding large payloads in the
    contract. Implementations may store artifacts locally, in object storage,
    or in an artifact registry.
    """

    artifact_id: str
    kind: BacktestArtifactKind
    uri: str

    # Integrity / content typing for auditability.
    sha256: str | None = None
    content_type: str | None = None
    size_bytes: int | None = None

    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BacktestRun:
    """
    Immutable record of a single backtest execution.

    This is a *result contract*: it contains only data, suitable for persistence
    and audit/replay. It must not contain runtime objects (clients, file handles).
    """

    run_id: str
    strategy_id: str
    config: BacktestConfig

    status: BacktestRunStatus
    created_at: datetime

    started_at: datetime | None = None
    completed_at: datetime | None = None

    # Deterministic outputs (optional, implementation-defined).
    metrics: Mapping[str, float] = field(default_factory=dict)

    # Human-readable failure reason / error classification (if status != SUCCEEDED).
    error_code: str | None = None
    error_message: str | None = None

    artifacts: tuple[BacktestArtifact, ...] = ()

    metadata: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class BacktestRunner(Protocol):
    """
    Boundary interface for running backtests.

    Implementations must:
    - be deterministic given (strategy_id, config)
    - not perform parameter tuning/optimization
    - reuse the same OBSERVE path as live (no "backtest-only" strategy logic)
    """

    def run_backtest(self, strategy_id: str, config: BacktestConfig) -> BacktestRun:
        """
        Execute a backtest and return a fully populated `BacktestRun`.
        """


def run_backtest(strategy_id: str, config: BacktestConfig) -> BacktestRun:
    """
    Interface function for running a backtest.

    This module is contracts-only. Concrete implementations should provide
    an injected `BacktestRunner` or bind this function at the application edge.
    """

    raise NotImplementedError("Interface-only: provide a BacktestRunner implementation.")

