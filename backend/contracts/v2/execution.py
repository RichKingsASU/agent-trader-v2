from __future__ import annotations

from typing import Any, Dict, Optional, Literal
from uuid import UUID

from pydantic import Field
from pydantic.types import AwareDatetime

from backend.contracts.v2.base import ContractBase, ContractFragment
from backend.contracts.v2.types import DecimalString, ExecutionMode, ExecutionStatus, Side


class ExecutionFill(ContractFragment):
    """
    Broker-agnostic fill representation.
    """

    fill_id: UUID = Field(..., description="Stable fill id assigned by our system.")
    filled_at: AwareDatetime = Field(...)
    side: Side
    quantity: DecimalString
    price: DecimalString

    fee: Optional[DecimalString] = Field(default=None, description="Optional fee in quote currency.")
    fee_currency: Optional[str] = Field(default=None, min_length=3, max_length=3)


class ExecutionAttempt(ContractBase):
    """
    An attempt to execute an OrderIntent (may be retried).
    """

    schema_name: Literal["agenttrader.v2.execution_attempt"] = Field(..., alias="schema")

    attempt_id: UUID = Field(...)
    intent_id: UUID = Field(description="The OrderIntent being executed.")

    attempt_number: int = Field(ge=1, description="1 for first attempt, increments on retries.")
    requested_at: AwareDatetime = Field(..., description="UTC timestamp when attempt started.")

    execution_mode: ExecutionMode

    idempotency_key: Optional[str] = Field(
        default=None,
        max_length=128,
        description="Optional idempotency key to dedupe retries across services.",
    )

    # IMPORTANT: `options` is intentionally OPTIONAL (per requirements).
    options: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional non-broker-specific execution settings (e.g., internal routing hints).",
    )


class ExecutionResult(ContractBase):
    """
    Result of an ExecutionAttempt.
    """

    schema_name: Literal["agenttrader.v2.execution_result"] = Field(..., alias="schema")

    result_id: UUID = Field(...)
    attempt_id: UUID
    intent_id: UUID

    recorded_at: AwareDatetime = Field(..., description="UTC timestamp when recorded.")
    status: ExecutionStatus

    filled_quantity: Optional[DecimalString] = Field(default=None)
    remaining_quantity: Optional[DecimalString] = Field(default=None)
    average_fill_price: Optional[DecimalString] = Field(default=None)

    fills: Optional[tuple[ExecutionFill, ...]] = Field(
        default=None,
        description="Optional fill breakdown (broker-agnostic).",
    )

    # Generic external references (intentionally unstructured to avoid broker leakage).
    # Example keys: "omsOrderId", "externalExecutionId"
    external_ids: Optional[Dict[str, str]] = Field(
        default=None,
        description="Optional external system references (no broker-specific fields in core contract).",
    )

    error_code: Optional[str] = Field(default=None, max_length=64)
    error_message: Optional[str] = Field(default=None, max_length=2048)

    # IMPORTANT: `options` is intentionally OPTIONAL (per requirements).
    options: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional non-broker-specific diagnostics (safe to share across services).",
    )

