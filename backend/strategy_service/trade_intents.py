from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, model_validator


class TradeRequest(BaseModel):
    # Correlation across signal -> allocation -> execution
    correlation_id: str | None = None
    signal_id: str | None = None
    allocation_id: str | None = None
    execution_id: str | None = None
    broker_account_id: UUID
    strategy_id: UUID
    symbol: str
    instrument_type: str
    side: str
    order_type: str
    time_in_force: str = "day"
    notional: float
    quantity: float = None
    idempotency_key: str | None = None

    # Options (shadow-only for now): SPY single-leg only.
    contract_symbol: str | None = None
    expiration: str | None = None  # ISO date (YYYY-MM-DD)
    strike: float | None = None
    right: str | None = None  # "call" | "put"

    @model_validator(mode="after")
    def _validate_option_fields(self) -> "TradeRequest":
        inst = str(self.instrument_type or "").strip().lower()
        if inst != "option":
            return self

        # SPY single-leg only (no spreads/multi-leg payloads supported here).
        if str(self.symbol or "").strip().upper() != "SPY":
            raise ValueError("options are restricted to SPY single-leg only (symbol must be SPY)")

        if not (self.contract_symbol and str(self.contract_symbol).strip()):
            raise ValueError("contract_symbol is required for instrument_type=option")
        if not (self.expiration and str(self.expiration).strip()):
            raise ValueError("expiration is required for instrument_type=option (YYYY-MM-DD)")
        if self.strike is None:
            raise ValueError("strike is required for instrument_type=option")
        if self.right is None or str(self.right).strip().lower() not in {"call", "put"}:
            raise ValueError("right is required for instrument_type=option and must be 'call' or 'put'")

        return self


def shadow_option_fill_price(*, notional: float, quantity: float | None) -> Decimal:
    """
    Derive a per-contract option premium from request fields (shadow-only):

    - `notional` is treated as total premium in USD for the trade
    - `quantity` is contracts
    - premium per contract = notional / (quantity * 100)
    """
    try:
        if quantity is None:
            return Decimal("0")
        q = Decimal(str(quantity))
        if q <= 0:
            return Decimal("0")
        n = Decimal(str(notional))
        if n <= 0:
            return Decimal("0")
        return (n / (q * Decimal("100"))).quantize(Decimal("0.0001"))
    except Exception:
        return Decimal("0")

