from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class StrategyMode(str, Enum):
    EVAL_ONLY = "EVAL_ONLY"
    PROPOSE_ONLY = "PROPOSE_ONLY"
    EXECUTE = "EXECUTE"


class StrategyVersion(BaseModel):
    config_version: str | int = Field(
        default=1, description="Semver-like string or integer version."
    )
    git_sha: Optional[str] = Field(
        default=None, description="Injected at load-time when available."
    )


class StrategyApprovals(BaseModel):
    requires_human_approval: bool = Field(default=True)
    approved_by: Optional[str] = Field(default=None)
    approved_at_utc: Optional[datetime] = Field(default=None)


class StrategyConfig(BaseModel):
    # Identity
    strategy_id: str = Field(..., description="Stable identifier (unique).")
    strategy_name: str = Field(..., description="Human-friendly name.")
    strategy_type: str = Field(..., description='e.g. "gamma", "whale", "utbot", "rsi".')

    # Safety switches
    enabled: bool = Field(default=False, description="Safe default is disabled.")
    mode: StrategyMode = Field(default=StrategyMode.EVAL_ONLY)

    # Scope + knobs
    symbols: list[str] = Field(default_factory=lambda: ["SPY", "IWM"])
    parameters: dict[str, Any] = Field(default_factory=dict)
    risk: dict[str, Any] = Field(default_factory=dict)
    schedule: Optional[dict[str, Any]] = Field(default=None)

    # Metadata
    created_at_utc: Optional[datetime] = Field(default=None)
    updated_at_utc: Optional[datetime] = Field(default=None)
    version: StrategyVersion = Field(default_factory=StrategyVersion)
    approvals: StrategyApprovals = Field(default_factory=StrategyApprovals)

