from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable, Optional


_USD = Decimal("0.01")
_PCT = Decimal("0.01")
_QTY = Decimal("0.000001")


def _as_decimal(v: Any, *, default: str = "0") -> Decimal:
    if v is None:
        return Decimal(default)
    if isinstance(v, Decimal):
        return v
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    s = str(v).strip()
    if not s:
        return Decimal(default)
    try:
        return Decimal(s)
    except InvalidOperation:
        return Decimal(default)


def _q_usd(x: Decimal) -> Decimal:
    return x.quantize(_USD, rounding=ROUND_HALF_UP)


def _q_pct(x: Decimal) -> Decimal:
    return x.quantize(_PCT, rounding=ROUND_HALF_UP)


def _q_qty(x: Decimal) -> Decimal:
    return x.quantize(_QTY, rounding=ROUND_HALF_UP)


def compute_trade_pnl(
    *,
    entry_price: Any,
    current_price: Any,
    quantity: Any,
    side: str,
) -> tuple[Decimal, Decimal]:
    """
    Compute P&L for a single shadow trade using Decimal math.

    Returns:
      (pnl_usd, pnl_percent) where:
        - pnl_usd is quantized to cents
        - pnl_percent is quantized to 0.01%

    Notes:
      - side accepts BUY/SELL (case-insensitive). SELL is treated as "short" for P&L.
      - pnl_percent uses cost basis = abs(entry_price * quantity). If cost basis is 0, percent=0.
    """
    ep = _as_decimal(entry_price)
    cp = _as_decimal(current_price)
    qty = _as_decimal(quantity)

    side_norm = (side or "").strip().upper()
    if side_norm == "SELL":
        pnl = (ep - cp) * qty
    else:
        pnl = (cp - ep) * qty

    pnl = _q_usd(pnl)
    cost_basis = abs(ep * qty)
    if cost_basis <= 0:
        return pnl, Decimal("0.00")

    pct = (pnl / cost_basis) * Decimal("100")
    return pnl, _q_pct(pct)


def parse_iso8601_best_effort(v: Any) -> Optional[datetime]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    s = str(v).strip()
    if not s:
        return None
    try:
        # Handles "Z" suffix and offset-aware strings.
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


@dataclass(frozen=True, slots=True)
class ShadowMetrics:
    realized_pnl_usd: Decimal
    unrealized_pnl_usd: Decimal
    net_pnl_usd: Decimal
    win_rate_percent: Decimal
    closed_trades: int
    open_trades: int
    max_drawdown_usd: Decimal
    max_drawdown_percent: Decimal

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "realized_pnl": str(_q_usd(self.realized_pnl_usd)),
            "unrealized_pnl": str(_q_usd(self.unrealized_pnl_usd)),
            "net_pnl": str(_q_usd(self.net_pnl_usd)),
            "win_rate": str(_q_pct(self.win_rate_percent)),
            "closed_trades": int(self.closed_trades),
            "open_trades": int(self.open_trades),
            "max_drawdown_usd": str(_q_usd(self.max_drawdown_usd)),
            "max_drawdown_percent": str(_q_pct(self.max_drawdown_percent)),
        }


def compute_max_drawdown_from_realized_pnls(
    series: Iterable[tuple[Optional[datetime], Decimal]],
) -> tuple[Decimal, Decimal]:
    """
    Compute max drawdown on a cumulative realized-P&L curve that starts at 0.

    Returns:
      (max_drawdown_usd, max_drawdown_percent)
    where drawdowns are <= 0 (0 means no drawdown).

    Percent definition:
      - If peak equity is <= 0, percent drawdown is 0 (avoid division by 0 / nonsensical base).
      - Else: (equity - peak) / peak * 100 (negative).
    """
    pts = list(series)
    pts.sort(key=lambda t: (t[0] is None, t[0] or datetime.min))

    equity = Decimal("0")
    peak = Decimal("0")
    max_dd_usd = Decimal("0")
    max_dd_pct = Decimal("0")

    for _, pnl in pts:
        equity += _as_decimal(pnl)
        if equity > peak:
            peak = equity
        dd_usd = equity - peak  # <= 0
        if dd_usd < max_dd_usd:
            max_dd_usd = dd_usd
            if peak > 0:
                max_dd_pct = _q_pct((dd_usd / peak) * Decimal("100"))
            else:
                max_dd_pct = Decimal("0.00")

    return _q_usd(max_dd_usd), _q_pct(max_dd_pct)


def compute_shadow_metrics(
    *,
    open_trades: Iterable[dict[str, Any]],
    closed_trades: Iterable[dict[str, Any]],
    live_prices_by_symbol: dict[str, Any] | None = None,
) -> ShadowMetrics:
    """
    Compute user-level shadow (paper) trading metrics.

    Inputs:
      - open_trades: Firestore docs (dicts) with at least symbol/side/entry_price/quantity.
      - closed_trades: Firestore docs with final_pnl OR realized_pnl.
      - live_prices_by_symbol: Optional {SYMBOL: price} to compute up-to-date unrealized P&L.
        If omitted, uses trade['current_pnl'] for open trades.
    """
    realized = Decimal("0")
    wins = 0
    closed_n = 0
    realized_series: list[tuple[Optional[datetime], Decimal]] = []

    for t in closed_trades:
        closed_n += 1
        pnl = _as_decimal(t.get("realized_pnl", t.get("final_pnl", t.get("current_pnl", "0"))))
        realized += pnl
        if pnl > 0:
            wins += 1
        ts = parse_iso8601_best_effort(t.get("closed_at_iso")) or parse_iso8601_best_effort(t.get("created_at_iso"))
        realized_series.append((ts, pnl))

    unreal = Decimal("0")
    open_n = 0
    for t in open_trades:
        open_n += 1
        sym = str(t.get("symbol", "")).strip().upper()
        if live_prices_by_symbol and sym in live_prices_by_symbol:
            pnl, _pct = compute_trade_pnl(
                entry_price=t.get("entry_price"),
                current_price=live_prices_by_symbol[sym],
                quantity=t.get("quantity"),
                side=str(t.get("side") or t.get("action") or "BUY"),
            )
            unreal += pnl
        else:
            unreal += _as_decimal(t.get("current_pnl", "0"))

    win_rate = (Decimal(wins) / Decimal(closed_n) * Decimal("100")) if closed_n > 0 else Decimal("0.00")
    max_dd_usd, max_dd_pct = compute_max_drawdown_from_realized_pnls(realized_series)

    return ShadowMetrics(
        realized_pnl_usd=_q_usd(realized),
        unrealized_pnl_usd=_q_usd(unreal),
        net_pnl_usd=_q_usd(realized + unreal),
        win_rate_percent=_q_pct(win_rate),
        closed_trades=int(closed_n),
        open_trades=int(open_n),
        max_drawdown_usd=_q_usd(max_dd_usd),
        max_drawdown_percent=_q_pct(max_dd_pct),
    )

