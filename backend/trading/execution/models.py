from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4


DecisionType = Literal["APPROVE", "REJECT"]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SafetySnapshot:
    """
    Minimal safety inputs captured at decision time.
    """

    kill_switch: bool
    marketdata_fresh: bool
    marketdata_last_ts: str | None
    agent_mode: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExecutionDecision:
    """
    Execution decision record.

    This is an audit artifact only. It MUST NOT imply an order has been placed.
    """

    proposal_id: str
    correlation_id: str | None

    agent_name: str
    agent_role: str

    decision: DecisionType
    reject_reason_codes: list[str] = field(default_factory=list)
    notes: str = ""
    recommended_order: dict[str, Any] = field(default_factory=dict)
    safety_snapshot: SafetySnapshot = field(
        default_factory=lambda: SafetySnapshot(
            kill_switch=True,
            marketdata_fresh=False,
            marketdata_last_ts=None,
            agent_mode="UNKNOWN",
        )
    )

    # System fields
    decision_id: str = field(default_factory=lambda: str(uuid4()))
    decided_at_utc: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Ensure stable keys (explicitly include nested dicts).
        d["safety_snapshot"] = self.safety_snapshot.to_dict()
        return d

