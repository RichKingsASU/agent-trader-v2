from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Mapping, Optional


class KillSwitchState(Enum):
    """
    Global trading kill switch state.

    This is intended to be a **human authority override** that gates trading
    regardless of any automated strategy decisioning.
    """

    TRADING_ALLOWED = "trading_allowed"
    TRADING_HALTED = "trading_halted"


class GovernanceAction(Enum):
    """
    Discrete governance actions that must be audit-logged.

    Note: This enum is intentionally small and can be extended as additional
    human overrides are added.
    """

    HALT_TRADING = "halt_trading"
    RESUME_TRADING = "resume_trading"


@dataclass(frozen=True)
class GovernanceAuditRecord:
    """
    Immutable audit record for governance actions.

    This is a type contract only; storage and emission are implementation-defined.
    """

    action: GovernanceAction
    actor: str
    occurred_at_utc: datetime
    reason: str
    metadata: Optional[Mapping[str, Any]] = None
    correlation_id: Optional[str] = None


class RiskGovernance(ABC):
    """
    Risk governance interface for **human authority overrides**.

    Implementations must treat governance as higher priority than automation.
    """

    @abstractmethod
    def is_trading_allowed(self) -> bool:
        """Return True iff global governance allows trading right now."""

    @abstractmethod
    def get_governance_state(self) -> KillSwitchState:
        """Return the current kill switch / governance state."""

