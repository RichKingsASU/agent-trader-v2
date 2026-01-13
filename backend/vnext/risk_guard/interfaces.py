"""
vNEXT Risk Guard (deterministic, workflow-safe)

This module is a deterministic "risk gate" that enforces bankroll/risk constraints
before execution. It is intentionally **strict** at the boundary:
- inputs are explicit and typed
- outputs are explicit and auditable
- no network / broker / DB dependencies

Rules implemented (as requested):
- max daily loss
- max order notional
- max trades/day
- max per-symbol exposure (USD notional, approximated as |position_qty| * price)
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RiskGuardLimits:
    """
    Risk constraints. Any field set to None disables that constraint.
    """

    max_daily_loss_usd: float | None = None
    max_order_notional_usd: float | None = None
    max_trades_per_day: int | None = None
    max_per_symbol_exposure_usd: float | None = None
    # Options-specific constraints (enforced only when enabled by callers).
    # - `max_contracts_per_symbol`: absolute contract count cap for a single option symbol.
    # - `max_gamma_exposure_abs`: absolute gamma exposure cap for a single *order* (incremental).
    max_contracts_per_symbol: int | None = None
    max_gamma_exposure_abs: float | None = None

    def normalized(self) -> "RiskGuardLimits":
        def _f(x: float | None) -> float | None:
            if x is None:
                return None
            try:
                v = float(x)
            except Exception:
                return None
            if v < 0:
                v = 0.0
            return v

        def _i(x: int | None) -> int | None:
            if x is None:
                return None
            try:
                v = int(x)
            except Exception:
                return None
            if v < 0:
                v = 0
            return v

        return RiskGuardLimits(
            max_daily_loss_usd=_f(self.max_daily_loss_usd),
            max_order_notional_usd=_f(self.max_order_notional_usd),
            max_trades_per_day=_i(self.max_trades_per_day),
            max_per_symbol_exposure_usd=_f(self.max_per_symbol_exposure_usd),
            max_contracts_per_symbol=_i(self.max_contracts_per_symbol),
            max_gamma_exposure_abs=_f(self.max_gamma_exposure_abs),
        )


@dataclass(frozen=True, slots=True)
class RiskGuardState:
    """
    Current account/session state needed to evaluate constraints.

    Notes:
    - `daily_pnl_usd` is net P&L for the day (negative means loss).
    - `trades_today` is the number of already-executed trades today.
    - `current_position_qty` is the signed position quantity for `trade.symbol`.
    """

    trading_date: str
    daily_pnl_usd: float | None
    trades_today: int | None
    current_position_qty: float | None
    # Optional audit context (not used for evaluation logic).
    correlation_id: str | None = None
    execution_id: str | None = None
    strategy_id: str | None = None


@dataclass(frozen=True, slots=True)
class RiskGuardTrade:
    """
    Trade candidate being gated.
    """

    symbol: str
    side: str  # "buy" | "sell"
    qty: float
    estimated_price_usd: float
    estimated_notional_usd: float
    asset_class: str = "EQUITY"  # "EQUITY" | "FOREX" | "CRYPTO" | "OPTIONS"
    # For options, contracts typically represent 100 shares (multiplier=100).
    contract_multiplier: float = 1.0
    # Options greeks (optional; required when an options-specific rule is enabled).
    greeks_gamma: float | None = None


@dataclass(frozen=True, slots=True)
class RiskGuardRuleResult:
    rule_id: str
    allowed: bool
    reason_code: str | None = None
    message: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RiskGuardDecision:
    allowed: bool
    reject_reason_codes: tuple[str, ...]
    message: str
    rule_results: tuple[RiskGuardRuleResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": bool(self.allowed),
            "reject_reason_codes": list(self.reject_reason_codes),
            "message": str(self.message),
            "rule_results": [asdict(r) for r in self.rule_results],
        }


def evaluate_risk_guard(
    *,
    trade: RiskGuardTrade,
    state: RiskGuardState,
    limits: RiskGuardLimits,
) -> RiskGuardDecision:
    """
    Deterministic evaluation of the risk guard rules.

    Contract:
    - Never raises (fail closed when inputs are invalid for enabled rules)
    - Logs explicit failures (single structured log line)
    """

    lim = limits.normalized()
    results: list[RiskGuardRuleResult] = []
    rejects: list[str] = []

    symbol = (trade.symbol or "").strip().upper()
    side = (trade.side or "").strip().lower()
    asset_class = (trade.asset_class or "EQUITY").strip().upper()

    # ---- Structural validation (always enforced) ----
    if not symbol:
        results.append(
            RiskGuardRuleResult(
                rule_id="input_validation",
                allowed=False,
                reason_code="symbol_missing",
                message="Trade symbol is missing/blank.",
            )
        )
        rejects.append("symbol_missing")
    if side not in {"buy", "sell"}:
        results.append(
            RiskGuardRuleResult(
                rule_id="input_validation",
                allowed=False,
                reason_code="side_invalid",
                message="Trade side must be 'buy' or 'sell'.",
                metadata={"side": trade.side},
            )
        )
        rejects.append("side_invalid")
    try:
        qty = float(trade.qty)
    except Exception:
        qty = -1.0
    if qty <= 0.0:
        results.append(
            RiskGuardRuleResult(
                rule_id="input_validation",
                allowed=False,
                reason_code="qty_non_positive",
                message="Trade qty must be > 0.",
                metadata={"qty": trade.qty},
            )
        )
        rejects.append("qty_non_positive")

    try:
        px = float(trade.estimated_price_usd)
    except Exception:
        px = -1.0
    if px <= 0.0:
        results.append(
            RiskGuardRuleResult(
                rule_id="input_validation",
                allowed=False,
                reason_code="estimated_price_non_positive",
                message="Estimated price must be > 0.",
                metadata={"estimated_price_usd": trade.estimated_price_usd},
            )
        )
        rejects.append("estimated_price_non_positive")

    try:
        notional = float(trade.estimated_notional_usd)
    except Exception:
        notional = -1.0
    if notional <= 0.0:
        results.append(
            RiskGuardRuleResult(
                rule_id="input_validation",
                allowed=False,
                reason_code="estimated_notional_non_positive",
                message="Estimated notional must be > 0.",
                metadata={"estimated_notional_usd": trade.estimated_notional_usd},
            )
        )
        rejects.append("estimated_notional_non_positive")

    # ---- Rule: max daily loss ----
    if lim.max_daily_loss_usd is not None:
        pnl = state.daily_pnl_usd
        if pnl is None:
            results.append(
                RiskGuardRuleResult(
                    rule_id="max_daily_loss",
                    allowed=False,
                    reason_code="daily_pnl_missing",
                    message="daily_pnl_usd is required to enforce max_daily_loss_usd.",
                )
            )
            rejects.append("daily_pnl_missing")
        else:
            try:
                pnl_f = float(pnl)
            except Exception:
                pnl_f = 0.0
            day_loss = max(0.0, -pnl_f)
            allowed = day_loss <= float(lim.max_daily_loss_usd) + 1e-9
            results.append(
                RiskGuardRuleResult(
                    rule_id="max_daily_loss",
                    allowed=allowed,
                    reason_code=None if allowed else "max_daily_loss_exceeded",
                    message=(
                        "OK"
                        if allowed
                        else "Daily loss exceeds configured max_daily_loss_usd."
                    ),
                    metadata={
                        "daily_pnl_usd": pnl_f,
                        "daily_loss_usd": day_loss,
                        "limit_usd": float(lim.max_daily_loss_usd),
                        "trading_date": state.trading_date,
                    },
                )
            )
            if not allowed:
                rejects.append("max_daily_loss_exceeded")

    # ---- Rule: max order notional ----
    if lim.max_order_notional_usd is not None:
        allowed = notional <= float(lim.max_order_notional_usd) + 1e-9
        results.append(
            RiskGuardRuleResult(
                rule_id="max_order_notional",
                allowed=allowed,
                reason_code=None if allowed else "max_order_notional_exceeded",
                message=("OK" if allowed else "Order notional exceeds configured max_order_notional_usd."),
                metadata={"estimated_notional_usd": notional, "limit_usd": float(lim.max_order_notional_usd)},
            )
        )
        if not allowed:
            rejects.append("max_order_notional_exceeded")

    # ---- Rule: max trades/day ----
    if lim.max_trades_per_day is not None:
        tt = state.trades_today
        if tt is None:
            results.append(
                RiskGuardRuleResult(
                    rule_id="max_trades_per_day",
                    allowed=False,
                    reason_code="trades_today_missing",
                    message="trades_today is required to enforce max_trades_per_day.",
                    metadata={"limit": int(lim.max_trades_per_day)},
                )
            )
            rejects.append("trades_today_missing")
        else:
            try:
                trades_today = int(tt)
            except Exception:
                trades_today = 0
            trades_next = trades_today + 1
            allowed = trades_next <= int(lim.max_trades_per_day)
            results.append(
                RiskGuardRuleResult(
                    rule_id="max_trades_per_day",
                    allowed=allowed,
                    reason_code=None if allowed else "max_trades_per_day_exceeded",
                    message=("OK" if allowed else "Trade count would exceed configured max_trades_per_day."),
                    metadata={
                        "trades_today": trades_today,
                        "trades_next": trades_next,
                        "limit": int(lim.max_trades_per_day),
                        "trading_date": state.trading_date,
                    },
                )
            )
            if not allowed:
                rejects.append("max_trades_per_day_exceeded")

    # ---- Rule: max per-symbol exposure (USD notional) ----
    if lim.max_per_symbol_exposure_usd is not None:
        cq = state.current_position_qty
        if cq is None:
            results.append(
                RiskGuardRuleResult(
                    rule_id="max_per_symbol_exposure",
                    allowed=False,
                    reason_code="current_position_qty_missing",
                    message="current_position_qty is required to enforce max_per_symbol_exposure_usd.",
                    metadata={"symbol": symbol, "limit_usd": float(lim.max_per_symbol_exposure_usd)},
                )
            )
            rejects.append("current_position_qty_missing")
        else:
            try:
                current_qty = float(cq)
            except Exception:
                current_qty = 0.0
            delta = qty if side == "buy" else -qty
            projected_qty = current_qty + delta
            projected_exposure = abs(projected_qty) * max(0.0, px)
            allowed = projected_exposure <= float(lim.max_per_symbol_exposure_usd) + 1e-9
            results.append(
                RiskGuardRuleResult(
                    rule_id="max_per_symbol_exposure",
                    allowed=allowed,
                    reason_code=None if allowed else "max_per_symbol_exposure_exceeded",
                    message=("OK" if allowed else "Per-symbol exposure would exceed configured max_per_symbol_exposure_usd."),
                    metadata={
                        "symbol": symbol,
                        "current_qty": current_qty,
                        "projected_qty": projected_qty,
                        "estimated_price_usd": px,
                        "projected_exposure_usd": projected_exposure,
                        "limit_usd": float(lim.max_per_symbol_exposure_usd),
                    },
                )
            )
            if not allowed:
                rejects.append("max_per_symbol_exposure_exceeded")

    # ---- Rule: max contracts per symbol (OPTIONS) ----
    if lim.max_contracts_per_symbol is not None:
        cq = state.current_position_qty
        if cq is None:
            results.append(
                RiskGuardRuleResult(
                    rule_id="max_contracts_per_symbol",
                    allowed=False,
                    reason_code="current_position_qty_missing",
                    message="current_position_qty is required to enforce max_contracts_per_symbol.",
                    metadata={"symbol": symbol, "limit_contracts": int(lim.max_contracts_per_symbol)},
                )
            )
            rejects.append("current_position_qty_missing")
        else:
            try:
                current_qty = float(cq)
            except Exception:
                current_qty = 0.0
            delta = qty if side == "buy" else -qty
            projected_qty = current_qty + delta
            allowed = abs(projected_qty) <= int(lim.max_contracts_per_symbol)
            results.append(
                RiskGuardRuleResult(
                    rule_id="max_contracts_per_symbol",
                    allowed=allowed,
                    reason_code=None if allowed else "max_contracts_per_symbol_exceeded",
                    message=("OK" if allowed else "Contract count would exceed configured max_contracts_per_symbol."),
                    metadata={
                        "symbol": symbol,
                        "asset_class": asset_class,
                        "current_contracts": current_qty,
                        "projected_contracts": projected_qty,
                        "limit_contracts": int(lim.max_contracts_per_symbol),
                    },
                )
            )
            if not allowed:
                rejects.append("max_contracts_per_symbol_exceeded")

    # ---- Rule: max gamma exposure (OPTIONS) ----
    # Note: enforced as a per-order (incremental) cap to keep the contract deterministic
    # without requiring a full portfolio greeks snapshot.
    if lim.max_gamma_exposure_abs is not None:
        # Fail closed if a caller enables the rule but doesn't supply gamma.
        if trade.greeks_gamma is None:
            results.append(
                RiskGuardRuleResult(
                    rule_id="max_gamma_exposure",
                    allowed=False,
                    reason_code="gamma_missing",
                    message="greeks_gamma is required to enforce max_gamma_exposure_abs.",
                    metadata={"symbol": symbol, "asset_class": asset_class},
                )
            )
            rejects.append("gamma_missing")
        else:
            try:
                gamma = float(trade.greeks_gamma)
            except Exception:
                gamma = 0.0
            try:
                mult = float(trade.contract_multiplier)
            except Exception:
                mult = 1.0
            if mult <= 0:
                mult = 1.0
            signed_qty = qty if side == "buy" else -qty
            incremental_gamma = gamma * signed_qty * mult
            allowed = abs(incremental_gamma) <= float(lim.max_gamma_exposure_abs) + 1e-9
            results.append(
                RiskGuardRuleResult(
                    rule_id="max_gamma_exposure",
                    allowed=allowed,
                    reason_code=None if allowed else "max_gamma_exposure_exceeded",
                    message=("OK" if allowed else "Incremental gamma exposure exceeds configured max_gamma_exposure_abs."),
                    metadata={
                        "symbol": symbol,
                        "asset_class": asset_class,
                        "greeks_gamma": gamma,
                        "contract_multiplier": mult,
                        "signed_qty": signed_qty,
                        "incremental_gamma_exposure": incremental_gamma,
                        "limit_abs": float(lim.max_gamma_exposure_abs),
                    },
                )
            )
            if not allowed:
                rejects.append("max_gamma_exposure_exceeded")

    allowed = len(rejects) == 0
    msg = "ok" if allowed else f"blocked: {', '.join(sorted(set(rejects)))}"
    decision = RiskGuardDecision(
        allowed=allowed,
        reject_reason_codes=tuple(sorted(set(rejects))),
        message=msg,
        rule_results=tuple(results),
    )

    if not allowed:
        # Explicit, deterministic logging for auditing. Keep it single-line.
        try:
            logger.warning(
                "risk_guard.blocked %s",
                {
                    "correlation_id": state.correlation_id,
                    "execution_id": state.execution_id,
                    "strategy_id": state.strategy_id,
                    "risk_decision": "DENY",
                    "trading_date": state.trading_date,
                    "symbol": symbol,
                    "side": side,
                    "qty": qty,
                    "estimated_price_usd": px,
                    "estimated_notional_usd": notional,
                    "reject_reason_codes": list(decision.reject_reason_codes),
                    "limits": asdict(lim),
                },
            )
        except Exception:
            logger.warning("risk_guard.blocked (payload_unserializable)")

    return decision

