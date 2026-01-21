from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.types import AwareDatetime

from backend.contracts.v2.types import CONTRACT_VERSION_V2, Environment


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ContractFragment(BaseModel):
    """
    Base for nested contract fragments (no envelope fields).
    """

    model_config = ConfigDict(
        extra="allow",
        frozen=True,
        populate_by_name=True,
    )


class ContractBase(BaseModel):
    """
    Base for AgentTrader v2 domain contracts.

    Design goals:
    - Immutable instances (frozen) to discourage in-place mutation across boundaries.
    - Forward-compatible parsing (extra="allow") so MINOR schema additions do not break
      older consumers that safely ignore unknown fields.
    """

    model_config = ConfigDict(
        extra="allow",
        frozen=True,
        populate_by_name=True,
    )

    # Canonical identity of the contract type and its SemVer.
    schema_name: str = Field(
        ...,
        alias="schema",
        description="Stable contract identifier, e.g. 'agenttrader.v2.trading_signal'.",
    )
    schema_version: Literal["2.0.0"] = Field(
        ...,
        description="SemVer contract version for this schema.",
        examples=[CONTRACT_VERSION_V2],
    )

    # Universal envelope fields (required).
    tenant_id: str = Field(..., min_length=1, description="Tenant / org identifier.")
    created_at: AwareDatetime = Field(..., description="UTC timestamp when created.")

    # Optional, stable cross-system correlation.
    correlation_id: Optional[str] = Field(
        default=None,
        description="Optional correlation id for end-to-end tracing across services.",
        max_length=128,
    )
    environment: Optional[Environment] = Field(
        default=None,
        description="Optional environment hint (prod/staging/dev/local).",
    )

    # Optional, non-broker-specific metadata. Keep this small and stable.
    meta: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional, producer-provided metadata (non-sensitive, non-broker-specific).",
    )

