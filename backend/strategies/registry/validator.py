from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Optional

from backend.common.agent_mode import AgentMode, get_agent_mode

from .models import StrategyConfig, StrategyMode


def _truthy_env(name: str) -> bool:
    v = os.getenv(name)
    if v is None:
        return False
    return str(v).strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def is_execution_allowed_stub() -> bool:
    """
    Stub "allow execution" flag.

    This intentionally defaults to False and must be explicitly enabled by the
    runtime environment. It is NOT a replacement for execution-engine gating.
    """
    return _truthy_env("ALLOW_STRATEGY_EXECUTION")


def _is_json_serializable(v: Any) -> bool:
    try:
        json.dumps(v, ensure_ascii=False, sort_keys=True)
        return True
    except Exception:
        return False


@dataclass(frozen=True)
class ValidationContext:
    symbol_allowlist: Optional[set[str]] = None
    allow_execution: bool = False


def validate_strategy_config(cfg: StrategyConfig, *, ctx: ValidationContext) -> StrategyConfig:
    """
    Validate a StrategyConfig with fail-safe rules.

    Raises ValueError on invalid configs.
    """
    sid = (cfg.strategy_id or "").strip()
    if not sid:
        raise ValueError("strategy_id is required")
    if sid != cfg.strategy_id:
        cfg.strategy_id = sid  # normalize

    if not _is_json_serializable(cfg.parameters):
        raise ValueError("parameters must be JSON-serializable")

    # Fail-safe execution gating:
    # - It's OK to declare EXECUTE in Git as long as it's not enabled.
    # - If enabled+EXECUTE, the runtime must explicitly allow execution.
    if cfg.enabled and cfg.mode == StrategyMode.EXECUTE and not ctx.allow_execution:
        raise ValueError(
            "mode=EXECUTE requires ALLOW_STRATEGY_EXECUTION=true when enabled=true"
        )

    # Optional symbol allowlist enforcement.
    if ctx.symbol_allowlist is not None:
        bad = [s for s in cfg.symbols if s not in ctx.symbol_allowlist]
        if bad:
            raise ValueError(f"symbols not allowlisted: {bad}")

    return cfg


def compute_effective_mode(cfg: StrategyConfig) -> StrategyMode:
    """
    Compute effective mode based on global authority (AGENT_MODE) and local safety.

    Safety policy:
    - If strategy is disabled => EVAL_ONLY
    - If AGENT_MODE != LIVE (or HALTED) => EVAL_ONLY
    - If requested EXECUTE but allow flag missing => PROPOSE_ONLY
    """
    if not cfg.enabled:
        return StrategyMode.EVAL_ONLY

    agent_mode = get_agent_mode()
    if agent_mode in {AgentMode.DISABLED, AgentMode.WARMUP, AgentMode.HALTED}:
        return StrategyMode.EVAL_ONLY

    # agent_mode == LIVE
    if cfg.mode == StrategyMode.EXECUTE and not is_execution_allowed_stub():
        return StrategyMode.PROPOSE_ONLY

    return cfg.mode

