from __future__ import annotations

"""
Stress Replay & Historical Simulation — Interfaces (vNEXT)

This module defines *contracts only* (no implementation):
- ReplayScenario: what to replay (time window + inputs + determinism anchors)
- ReplayConfig: how to replay (strict deterministic controls; no tuning)
- ReplayResult: what the run produced (status + artifacts + metrics)

Design intent:
- Replays must exercise the *same code paths as live* strategies.
- Replays must *not* allow parameter tuning during the run.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Literal, Mapping, Optional, Protocol, Sequence


ReplayStatus = Literal["success", "failed", "cancelled"]


def _freeze_mapping(m: Optional[Mapping[str, Any]]) -> Mapping[str, Any]:
    """
    Ensure mappings stored in frozen dataclasses remain read-only.
    """
    if not m:
        return MappingProxyType({})
    # Copy to avoid outside mutation, then wrap.
    return MappingProxyType(dict(m))


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


@dataclass(frozen=True, slots=True)
class ReplayScenario:
    """
    Defines the replayable historical window and its deterministic anchors.

    Notes:
    - `seed` must be fixed and used for any RNG that the run might touch.
    - `inputs` should point to immutable snapshots (files, object storage URIs,
      DB snapshot IDs) so the run is reproducible.
    """

    scenario_id: str
    start_utc: datetime
    end_utc: datetime

    # Optional scope hints (implementation-defined; empty => strategy decides).
    symbols: tuple[str, ...] = ()

    # Determinism anchor(s)
    seed: int = 0

    # Implementation-defined pointers to the immutable data backing this scenario.
    # Examples: "gs://.../bars.parquet", "file:///.../ticks.ndjson", "snapshot:2026-01-01T00:00Z"
    inputs: Mapping[str, Any] = field(default_factory=dict)

    # Human-facing context
    name: str = ""
    description: str = ""
    tags: tuple[str, ...] = ()

    # Arbitrary metadata (must not affect execution semantics).
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "inputs", _freeze_mapping(self.inputs))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))


@dataclass(frozen=True, slots=True)
class ReplayConfig:
    """
    Execution controls for replay.

    The core policy is **no parameter tuning**:
    - A replay run must NOT mutate strategy parameters mid-run.
    - A replay run must NOT accept config overrides compared to "live" execution,
      other than selecting the scenario inputs + clock source.
    """

    # Determinism / safety rails
    deterministic: bool = True
    fail_on_nondeterminism: bool = True
    strict_event_ordering: bool = True

    # Strong statement of intent: replays cannot override strategy params.
    allow_parameter_tuning: bool = False
    strategy_config_overrides: Mapping[str, Any] | None = None

    # Optional behavior switches (implementation-defined).
    emit_replay_events: bool = True
    record_artifacts: bool = True

    # Guardrails for runaway runs (implementation-defined semantics).
    max_events: int | None = None
    max_runtime_seconds: float | None = None

    # Extra metadata for provenance (must not affect execution semantics).
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))
        if self.strategy_config_overrides is not None:
            object.__setattr__(self, "strategy_config_overrides", _freeze_mapping(self.strategy_config_overrides))


@dataclass(frozen=True, slots=True)
class ReplayResult:
    """
    Output contract for a replay run.
    """

    run_id: str
    strategy_id: str
    scenario_id: str

    status: ReplayStatus
    started_at_utc: datetime = field(default_factory=_utc_now)
    ended_at_utc: datetime | None = None

    # Summary metrics (implementation-defined; keep stable keys if used by UIs).
    metrics: Mapping[str, Any] = field(default_factory=dict)

    # URIs to persisted artifacts (logs, event streams, reports, traces).
    artifacts: Mapping[str, str] = field(default_factory=dict)

    # Failure/validation messages; empty on success.
    errors: tuple[str, ...] = ()

    # Optional provenance / fingerprinting (implementation-defined).
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metrics", _freeze_mapping(self.metrics))
        object.__setattr__(self, "artifacts", MappingProxyType(dict(self.artifacts or {})))
        object.__setattr__(self, "provenance", _freeze_mapping(self.provenance))


class ReplayRunner(Protocol):
    """
    Minimal interface requested by vNEXT Prompt 8.
    """

    def run_replay(self, strategy_id: str, scenario_id: str) -> ReplayResult: ...


class ReplayService(ABC):
    """
    Optional richer interface for implementations.

    Implementations should:
    - Load the `ReplayScenario` by ID.
    - Construct a deterministic runtime using the same live strategy entrypoints.
    - Produce a `ReplayResult` with stable artifact pointers.
    """

    @abstractmethod
    def get_scenario(self, scenario_id: str) -> ReplayScenario: ...

    @abstractmethod
    def run_replay(self, strategy_id: str, scenario_id: str, *, config: ReplayConfig | None = None) -> ReplayResult: ...

