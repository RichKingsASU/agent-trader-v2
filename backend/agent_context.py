"""
Agent governance scaffolding.

Goal: make agent identity explicit, scoped, and auditable.

This module introduces:
- AgentIdentity schema (agent_id, agent_type, permissions)
- AgentContext object that must be passed explicitly to governed operations
- Permission enforcement helper for fail-closed behavior

No runtime behavior changes are intended beyond permission checks at explicit
enforcement points wired elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, FrozenSet, Mapping


class AgentType(str, Enum):
    STRATEGY = "strategy"
    EXECUTION = "execution"
    RISK = "risk"
    OBSERVER = "observer"


class Permission(str, Enum):
    """
    Governance permissions.

    Keep this list small and composable; it is an allowlist.
    """

    READ_CAPITAL = "read_capital"
    ALLOCATE_RISK = "allocate_risk"
    RESERVE_CAPITAL = "reserve_capital"
    PLACE_ORDERS = "place_orders"
    MODIFY_RISK = "modify_risk"


@dataclass(frozen=True)
class AgentIdentity:
    """
    Minimal agent identity schema.

    Required fields:
    - agent_id: stable identifier for the runtime/agent instance
    - agent_type: strategy|execution|risk|observer
    - permissions: explicit allowlist of actions this agent may perform
    """

    agent_id: str
    agent_type: AgentType
    permissions: FrozenSet[Permission] = field(default_factory=frozenset)

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type.value,
            "permissions": sorted(p.value for p in self.permissions),
        }


@dataclass(frozen=True)
class AgentContext:
    """
    Execution context for governed operations.

    This is passed explicitly (no globals) to make actions attributable and auditable.
    """

    identity: AgentIdentity
    trace_id: str | None = None
    tenant_id: str | None = None
    user_id: str | None = None
    strategy_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity.to_audit_dict(),
            "trace_id": self.trace_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "strategy_id": self.strategy_id,
            "metadata": dict(self.metadata or {}),
        }


class PermissionDeniedError(RuntimeError):
    """
    Raised when an agent attempts an operation without the required permission.
    """

    def __init__(
        self,
        *,
        agent: AgentIdentity,
        required: Permission,
        action: str,
        details: Mapping[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> None:
        have = sorted(p.value for p in (agent.permissions or frozenset()))
        msg = (
            f"Permission denied for action={action!r}: "
            f"agent_id={agent.agent_id!r} agent_type={agent.agent_type.value!r} "
            f"required={required.value!r} have={have!r}"
        )
        if trace_id:
            msg += f" trace_id={trace_id!r}"
        if details:
            msg += f" details={dict(details)!r}"
        super().__init__(msg)
        self.agent = agent
        self.required = required
        self.action = action
        self.details = dict(details or {})
        self.trace_id = trace_id


def require_permission(
    ctx: AgentContext,
    required: Permission,
    *,
    action: str,
    details: Mapping[str, Any] | None = None,
) -> None:
    """
    Fail-closed permission enforcement for governed operations.
    """

    if required in (ctx.identity.permissions or frozenset()):
        return
    raise PermissionDeniedError(
        agent=ctx.identity,
        required=required,
        action=action,
        details=details,
        trace_id=ctx.trace_id,
    )

