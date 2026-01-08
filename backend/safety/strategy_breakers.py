from __future__ import annotations

"""
Per-strategy circuit breakers (safety only).

Design goals:
- Do not modify strategy alpha logic; only provide safety gating.
- Avoid market assumptions by making thresholds explicitly configurable.
- Keep checks deterministic and best-effort (never crash callers).

Breakers implemented here:
- missing_market_data
- abnormal_volatility (relative volatility ratio; threshold is operator-configured)
- consecutive_losses (realized, computed from ledger fills; threshold is operator-configured)
"""

import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from backend.ledger.pnl import compute_pnl_fifo


@dataclass(frozen=True)
class CircuitBreakerDecision:
    triggered: bool
    reason_code: str
    message: str
    details: dict[str, Any]


def _safe_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def check_missing_market_data(*, bars: Iterable[Any] | None, source: str) -> CircuitBreakerDecision:
    """
    Trigger if market data is missing/empty.

    This is objective (no thresholds / market assumptions).
    """
    try:
        seq = list(bars or [])
    except Exception:
        seq = []
    if not seq:
        return CircuitBreakerDecision(
            triggered=True,
            reason_code="missing_market_data",
            message=f"Missing market data ({source} returned empty).",
            details={"source": source, "bars_count": 0},
        )
    return CircuitBreakerDecision(
        triggered=False,
        reason_code="ok",
        message="ok",
        details={"source": source, "bars_count": len(seq)},
    )


def check_abnormal_volatility(
    *,
    bars: Iterable[Any] | None,
    source: str,
    recent_n: int,
    baseline_n: int,
    ratio_threshold: float,
) -> CircuitBreakerDecision:
    """
    Trigger if short-term volatility is abnormally high vs a baseline window.

    This uses a *ratio* (recent_vol / baseline_vol) so it is scale-free. The
    threshold is explicitly operator-configured (no baked-in market assumptions).
    """
    try:
        seq = list(bars or [])
    except Exception:
        seq = []

    closes: list[float] = []
    for b in reversed(seq):  # oldest -> newest
        px = _safe_float(getattr(b, "close", None))
        if px is None or px <= 0:
            continue
        closes.append(px)

    # Need at least baseline_n+1 points to compute baseline_n returns.
    need = max(2, int(baseline_n) + 1)
    if len(closes) < need:
        return CircuitBreakerDecision(
            triggered=False,
            reason_code="volatility_insufficient_data",
            message="Not enough data to compute volatility.",
            details={"source": source, "closes_count": len(closes), "required": need},
        )

    rets: list[float] = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        cur = closes[i]
        if prev <= 0 or cur <= 0:
            continue
        rets.append(math.log(cur / prev))

    if len(rets) < int(baseline_n):
        return CircuitBreakerDecision(
            triggered=False,
            reason_code="volatility_insufficient_returns",
            message="Not enough returns to compute volatility.",
            details={"source": source, "returns_count": len(rets), "required": int(baseline_n)},
        )

    recent_n = max(2, min(int(recent_n), len(rets)))
    baseline_n = max(recent_n, min(int(baseline_n), len(rets)))

    recent = rets[-recent_n:]
    baseline = rets[-baseline_n:]

    try:
        vol_recent = float(statistics.pstdev(recent))
        vol_base = float(statistics.pstdev(baseline))
    except Exception:
        vol_recent = 0.0
        vol_base = 0.0

    eps = 1e-12
    ratio = vol_recent / max(vol_base, eps)

    triggered = bool(ratio_threshold > 0 and ratio > float(ratio_threshold))
    return CircuitBreakerDecision(
        triggered=triggered,
        reason_code="abnormal_volatility" if triggered else "ok",
        message=(
            f"Abnormal volatility: recent/baseline ratio {ratio:.3f} > {ratio_threshold:.3f}"
            if triggered
            else "ok"
        ),
        details={
            "source": source,
            "recent_n": int(recent_n),
            "baseline_n": int(baseline_n),
            "vol_recent": vol_recent,
            "vol_baseline": vol_base,
            "ratio": ratio,
            "ratio_threshold": float(ratio_threshold),
        },
    )


def check_consecutive_losses_from_ledger_trades(
    *,
    trades: Iterable[Any],
    max_consecutive_losses: int,
) -> CircuitBreakerDecision:
    """
    Trigger if the most recent realized (closing) events contain N consecutive losses.

    Input `trades` should be ledger-like objects/dicts with at least:
    - symbol, side, qty, price, ts, fees
    """
    max_consecutive_losses = int(max_consecutive_losses)
    if max_consecutive_losses <= 0:
        return CircuitBreakerDecision(
            triggered=False,
            reason_code="disabled",
            message="consecutive_losses breaker disabled (threshold <= 0)",
            details={"max_consecutive_losses": max_consecutive_losses},
        )

    # Normalize to dicts expected by compute_pnl_fifo().
    normalized: list[dict[str, Any]] = []
    for i, t in enumerate(list(trades or [])):
        try:
            if isinstance(t, dict):
                sym = t.get("symbol")
                side = t.get("side")
                qty = t.get("qty")
                price = t.get("price")
                ts = t.get("ts")
                fees = t.get("fees", 0.0)
                trade_id = t.get("trade_id") or t.get("id") or f"t_{i}"
            else:
                sym = getattr(t, "symbol", None)
                side = getattr(t, "side", None)
                qty = getattr(t, "qty", None)
                price = getattr(t, "price", None)
                ts = getattr(t, "ts", None)
                fees = getattr(t, "fees", 0.0)
                slippage = getattr(t, "slippage", 0.0)
                fees = float(fees or 0.0) + float(slippage or 0.0)
                trade_id = getattr(t, "trade_id", None) or getattr(t, "id", None) or f"t_{i}"

            if not isinstance(ts, datetime):
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            d = {
                "trade_id": str(trade_id),
                "symbol": str(sym or ""),
                "side": str(side or ""),
                "qty": float(qty or 0.0),
                "price": float(price or 0.0),
                "ts": ts.astimezone(timezone.utc),
                "fees": float(fees or 0.0),
            }
            if d["symbol"] and d["side"] and d["qty"] > 0 and d["price"] > 0:
                normalized.append(d)
        except Exception:
            continue

    if not normalized:
        return CircuitBreakerDecision(
            triggered=False,
            reason_code="no_trades",
            message="No ledger trades available for consecutive loss evaluation.",
            details={"max_consecutive_losses": max_consecutive_losses, "trades_count": 0},
        )

    res = compute_pnl_fifo(normalized, trade_id_field="trade_id", sort_by_ts=True)
    # Only consider trades that realize PnL (closing activity) OR realize fees (flat close).
    realized = [t for t in res.trades if (abs(float(t.realized_pnl_gross)) > 0.0) or (float(t.realized_fees) > 0.0)]
    if not realized:
        return CircuitBreakerDecision(
            triggered=False,
            reason_code="no_realized_events",
            message="No realized events yet (no closes), consecutive loss breaker not applicable.",
            details={"max_consecutive_losses": max_consecutive_losses, "realized_events": 0},
        )

    consec = 0
    last_events: list[dict[str, Any]] = []
    for t in reversed(realized):
        pnl = float(t.realized_pnl_net)
        last_events.append({"trade_id": t.trade_id, "ts": t.ts, "realized_pnl_net": pnl})
        if pnl < 0:
            consec += 1
        else:
            break
        if consec >= max_consecutive_losses:
            break

    triggered = consec >= max_consecutive_losses
    return CircuitBreakerDecision(
        triggered=triggered,
        reason_code="consecutive_losses" if triggered else "ok",
        message=(
            f"Consecutive losses triggered: {consec} >= {max_consecutive_losses}"
            if triggered
            else "ok"
        ),
        details={
            "max_consecutive_losses": max_consecutive_losses,
            "consecutive_losses": consec,
            "realized_events_considered": len(last_events),
        },
    )

