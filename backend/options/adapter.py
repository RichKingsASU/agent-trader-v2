from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any, Dict, Optional, Tuple

from backend.options.option_intent import OptionOrderIntent, OptionType, Side


CONTRACT_MULTIPLIER = 100


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _as_str(x: Any) -> Optional[str]:
    if x is None:
        return None
    try:
        s = str(x).strip()
    except Exception:
        return None
    return s or None


def _as_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x)
    except Exception:
        return None


def _as_date(x: Any) -> Optional[date]:
    if x is None:
        return None
    if isinstance(x, date) and not isinstance(x, datetime):
        return x
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, str):
        try:
            return date.fromisoformat(x.strip())
        except Exception:
            return None
    return None


def _resolve_mapping(*, is_positive_delta_hedge: bool, market_snapshot: Any) -> Tuple[OptionType, Side]:
    """
    Determine which option instrument + side to use for a delta hedge.

    Defaults (conservative, deterministic):
    - Positive delta hedge (sell shares)  -> SELL CALLS
    - Negative delta hedge (buy shares)   -> SELL PUTS

    Config override via market_snapshot:
    - delta_hedge_mode: "sell_premium" | "buy_protection"
    - OR a dict at `delta_hedge_policy` / `option_hedge_policy` with keys:
        - positive_delta: "sell_calls" | "buy_puts"
        - negative_delta: "sell_puts" | "buy_calls"
    """

    # Mode shortcut: maps both legs at once.
    mode = _as_str(_get(market_snapshot, "delta_hedge_mode")) or _as_str(_get(market_snapshot, "option_hedge_mode"))
    mode_norm = (mode or "").strip().lower()
    if mode_norm in {"buy_protection", "buy"}:
        return (OptionType.PUT, Side.BUY) if is_positive_delta_hedge else (OptionType.CALL, Side.BUY)
    if mode_norm in {"sell_premium", "sell"}:
        return (OptionType.CALL, Side.SELL) if is_positive_delta_hedge else (OptionType.PUT, Side.SELL)

    policy = (
        _get(market_snapshot, "delta_hedge_policy")
        or _get(market_snapshot, "option_hedge_policy")
        or _get(market_snapshot, "hedge_policy")
        or {}
    )
    if isinstance(policy, str):
        # Support passing a mode-like string in policy for convenience.
        pnorm = policy.strip().lower()
        if pnorm in {"buy_protection", "buy"}:
            return (OptionType.PUT, Side.BUY) if is_positive_delta_hedge else (OptionType.CALL, Side.BUY)
        if pnorm in {"sell_premium", "sell"}:
            return (OptionType.CALL, Side.SELL) if is_positive_delta_hedge else (OptionType.PUT, Side.SELL)
        # Unknown: fall through to default below.
        policy = {}

    if isinstance(policy, dict):
        key = "positive_delta" if is_positive_delta_hedge else "negative_delta"
        raw = policy.get(key) or policy.get(f"{key}_hedge") or policy.get(f"{key}_policy")
        v = (str(raw).strip().lower() if raw is not None else "")
        if is_positive_delta_hedge:
            if v in {"sell_calls", "sell_call", "calls_sell"}:
                return OptionType.CALL, Side.SELL
            if v in {"buy_puts", "buy_put", "puts_buy"}:
                return OptionType.PUT, Side.BUY
        else:
            if v in {"sell_puts", "sell_put", "puts_sell"}:
                return OptionType.PUT, Side.SELL
            if v in {"buy_calls", "buy_call", "calls_buy"}:
                return OptionType.CALL, Side.BUY

    # Default (fail-closed, deterministic).
    return (OptionType.CALL, Side.SELL) if is_positive_delta_hedge else (OptionType.PUT, Side.SELL)


def translate_equity_hedge_to_option_intent(equity_intent: Any, market_snapshot: Any) -> Optional[OptionOrderIntent]:
    """
    Adapt an equity delta-hedge order intent into an option-based intent.

    Safety properties:
    - Pure + deterministic (no I/O, no time, no randomness).
    - Fail closed: never raises; returns None on invalid/insufficient inputs.

    Sizing:
    - contract_multiplier = 100
    - contracts = floor(abs(hedge_qty_shares) / 100)
    - If contracts < 1 -> return None
    """

    try:
        underlying = _as_str(_get(equity_intent, "symbol"))
        if not underlying:
            return None

        side_raw = _as_str(_get(equity_intent, "side"))
        if not side_raw:
            return None
        side_norm = side_raw.lower()
        if side_norm not in {"buy", "sell"}:
            return None

        qty = _as_float(_get(equity_intent, "qty"))
        if qty is None:
            return None
        qty = float(qty)
        if qty <= 0.0:
            return None

        # Reconstruct signed shares from the v1 intent convention:
        # - side="buy"  => +qty shares
        # - side="sell" => -qty shares
        hedge_qty_shares = qty if side_norm == "buy" else -qty
        if hedge_qty_shares == 0.0:
            return None

        contracts = int(math.floor(abs(hedge_qty_shares) / float(CONTRACT_MULTIPLIER)))
        if contracts < 1:
            return None

        expiry = _as_date(
            _get(market_snapshot, "expiry")
            or _get(market_snapshot, "expiration")
            or _get(market_snapshot, "expiration_date")
        )
        strike = _as_float(_get(market_snapshot, "strike") or _get(market_snapshot, "atm_strike"))
        if expiry is None or strike is None:
            return None
        if strike <= 0.0:
            return None

        # If we are SELLing shares, we were net long delta; this is a positive delta hedge.
        is_positive_delta_hedge = hedge_qty_shares < 0.0
        option_type, option_side = _resolve_mapping(is_positive_delta_hedge=is_positive_delta_hedge, market_snapshot=market_snapshot)

        src_meta = _get(equity_intent, "metadata") or {}
        if not isinstance(src_meta, dict):
            src_meta = {"value": src_meta}

        # Deterministic, minimal traceability context.
        metadata: Dict[str, Any] = {}
        metadata["source"] = "equity_hedge_intent_adapter"
        metadata["source_equity_intent"] = {
            "symbol": underlying,
            "side": side_norm,
            "qty": qty,
            "intent_id": _get(equity_intent, "intent_id"),
            "client_tag": _get(equity_intent, "client_tag"),
            "metadata": src_meta,
        }
        metadata["contract_multiplier"] = CONTRACT_MULTIPLIER
        metadata["hedge_qty_shares_signed"] = hedge_qty_shares

        reason = "delta_hedge_equity_to_option"
        src_reason = _as_str(src_meta.get("reason")) if isinstance(src_meta, dict) else None
        if src_reason:
            reason = f"{reason}:{src_reason}"

        return OptionOrderIntent(
            underlying=underlying,
            option_type=option_type,
            strike=float(strike),
            expiry=expiry,
            contracts=int(contracts),
            side=option_side,
            reason=reason,
            metadata=metadata,
        )
    except Exception:
        return None

