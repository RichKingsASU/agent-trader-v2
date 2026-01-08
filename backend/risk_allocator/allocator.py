from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from typing import Optional
from uuid import UUID

from backend.trading.agent_intent.models import AgentIntent, IntentKind, IntentSide


@dataclass(frozen=True)
class Allocation:
    """
    Output of the allocator.

    This is the *only* place that should convert intent into capital-bearing
    quantities like qty/notional.
    """

    allowed: bool
    reason: str
    qty: float = 0.0
    notional_usd: float = 0.0


def _default_qty() -> float:
    # Conservative default; preserves existing "size: 1" behavior in strategies.
    try:
        return float(os.getenv("ALLOCATOR_DEFAULT_QTY") or "1")
    except Exception:
        return 1.0


class RiskAllocator:
    """
    Centralized decision point:
    - sizes (qty/notional)
    - applies risk limits that require capital knowledge
    """

    async def allocate_for_strategy_limits(
        self,
        *,
        intent: AgentIntent,
        strategy_id: UUID,
        trading_date: date,
        last_price: float,
        can_place_trade_fn,
    ) -> Allocation:
        """
        Allocation + strategy limits gate (Postgres-backed).

        `can_place_trade_fn` is injected to avoid circular imports in callers.
        """
        if intent.side == IntentSide.FLAT:
            return Allocation(allowed=False, reason="flat_intent", qty=0.0, notional_usd=0.0)

        qty = self._size_intent(intent=intent)
        notional = max(0.0, float(last_price or 0.0) * float(qty))

        allowed = await can_place_trade_fn(strategy_id, trading_date, notional)
        if not allowed:
            return Allocation(allowed=False, reason="strategy_limits_blocked", qty=0.0, notional_usd=0.0)

        return Allocation(allowed=True, reason="ok", qty=qty, notional_usd=notional)

    def allocate_without_gates(self, *, intent: AgentIntent, last_price: float) -> Allocation:
        """
        Allocation without external stateful gates.

        This is still useful for proposal generation flows where execution is
        human-approved and/or risk checks are performed downstream.
        """
        if intent.side == IntentSide.FLAT:
            return Allocation(allowed=False, reason="flat_intent", qty=0.0, notional_usd=0.0)
        qty = self._size_intent(intent=intent)
        notional = max(0.0, float(last_price or 0.0) * float(qty))
        return Allocation(allowed=True, reason="ok", qty=qty, notional_usd=notional)

    def _size_intent(self, *, intent: AgentIntent) -> float:
        """
        Convert intent → quantity (units), without changing strategy logic.

        - DIRECTIONAL intents default to 1 unit (preserves existing drivers).
        - DELTA_HEDGE derives qty from delta_to_hedge (round-to-share behavior).
        """
        if intent.kind == IntentKind.DELTA_HEDGE:
            d = float(intent.constraints.delta_to_hedge or 0.0)
            if d == 0.0:
                return 0.0
            # Preserve existing hedge behavior: hedge_qty = -net_delta, rounded to whole share.
            return float(int(abs(round(d, 0))))

        # Default for DIRECTIONAL / EXIT: 1 unit (or env override).
        return float(max(0.0, _default_qty()))

