from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping, Optional

from backend.ledger.models import LedgerTrade
from backend.ledger.strategy_performance import compute_strategy_pnl_for_period
from backend.marketplace.performance import month_period_utc
from backend.marketplace.schema import TenantPaths, monthly_perf_id


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _to_firestore_ts(dt: datetime) -> datetime:
    # firebase-admin / google-cloud-firestore accept python datetime objects.
    # Enforce UTC to keep ids + comparisons deterministic.
    return _as_utc(dt)

def _server_timestamp_fallback() -> Any:
    """
    Returns Firestore SERVER_TIMESTAMP sentinel when available; otherwise a UTC datetime.

    The repo's unit tests may run without google-cloud-firestore installed.
    """
    try:
        from google.cloud import firestore  # type: ignore

        return firestore.SERVER_TIMESTAMP
    except Exception:
        return datetime.now(timezone.utc)


def ledger_trade_from_firestore_doc(*, tenant_id: str, doc: Mapping[str, Any]) -> Optional[LedgerTrade]:
    """
    Best-effort coercion from Firestore dict -> LedgerTrade.

    Returns None for docs that don't match the fill-level ledger shape.
    """
    uid = (doc.get("uid") or doc.get("user_id") or doc.get("userId") or "").strip()
    strategy_id = (doc.get("strategy_id") or doc.get("strategyId") or "").strip()
    run_id = (doc.get("run_id") or doc.get("runId") or "legacy").strip()
    symbol = (doc.get("symbol") or "").strip()
    side = doc.get("side")
    qty = doc.get("qty")
    price = doc.get("price")
    ts = doc.get("ts")

    if not (uid and strategy_id and symbol and side and qty and price and ts):
        return None
    if not isinstance(ts, datetime):
        return None

    return LedgerTrade(
        tenant_id=tenant_id,
        uid=uid,
        strategy_id=strategy_id,
        run_id=run_id,
        symbol=symbol,
        side=str(side),
        qty=float(qty),
        price=float(price),
        ts=ts,
        order_id=doc.get("order_id"),
        broker_fill_id=doc.get("broker_fill_id"),
        fees=float(doc.get("fees") or 0.0),
        slippage=float(doc.get("slippage") or 0.0),
        account_id=doc.get("account_id"),
    )


@dataclass(frozen=True, slots=True)
class StrategyPerformanceSnapshot:
    """
    Firestore doc payload for:
      tenants/{tid}/strategy_performance/{perf_id}
    """

    tenant_id: str
    uid: str
    strategy_id: str
    period_start: datetime
    period_end: datetime
    realized_pnl: float
    unrealized_pnl: float

    def to_firestore_doc(self) -> Dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "uid": self.uid,
            "strategy_id": self.strategy_id,
            "period_start": _to_firestore_ts(self.period_start),
            "period_end": _to_firestore_ts(self.period_end),
            "realized_pnl": float(self.realized_pnl),
            "unrealized_pnl": float(self.unrealized_pnl),
            "computed_at": _server_timestamp_fallback(),
            "source": "ledger_trades_fifo",
        }


def build_monthly_strategy_performance_snapshots(
    ledger_trades: Iterable[LedgerTrade],
    *,
    year: int,
    month: int,
    mark_prices: Mapping[str, float],
) -> Dict[str, StrategyPerformanceSnapshot]:
    """
    Build monthly per-user per-strategy performance docs keyed by perf_id.

    NOTE: This assumes `ledger_trades` includes all fills with ts < period_end for correctness.
    """
    period_start, period_end = month_period_utc(year=year, month=month)
    pnl_by_key = compute_strategy_pnl_for_period(
        ledger_trades,
        period_start=period_start,
        period_end=period_end,
        mark_prices=mark_prices,
    )

    out: Dict[str, StrategyPerformanceSnapshot] = {}
    for (tenant_id, uid, strategy_id), pnl in pnl_by_key.items():
        perf_id = monthly_perf_id(uid=uid, strategy_id=strategy_id, year=year, month=month)
        out[perf_id] = StrategyPerformanceSnapshot(
            tenant_id=tenant_id,
            uid=uid,
            strategy_id=strategy_id,
            period_start=period_start,
            period_end=period_end,
            realized_pnl=float(pnl.realized_pnl),
            unrealized_pnl=float(pnl.unrealized_pnl),
        )
    return out


def compute_monthly_strategy_performance_from_firestore(
    *,
    db: Any,
    tenant_id: str,
    year: int,
    month: int,
    uid: Optional[str] = None,
    strategy_id: Optional[str] = None,
    mark_prices: Optional[Mapping[str, float]] = None,
) -> Dict[str, StrategyPerformanceSnapshot]:
    """
    Query Firestore `ledger_trades` and compute monthly snapshots per (uid, strategy_id).
    """
    mark_prices = dict(mark_prices or {})
    period_start, period_end = month_period_utc(year=year, month=month)

    paths = TenantPaths(tenant_id=tenant_id)
    ledger_ref = db.collection(paths.ledger_trades)

    # We need all trades up to period_end for correct realized attribution.
    q = ledger_ref.where("ts", "<", _to_firestore_ts(period_end)).order_by("ts")
    if uid:
        q = q.where("uid", "==", uid)
    if strategy_id:
        q = q.where("strategy_id", "==", strategy_id)

    parsed: list[LedgerTrade] = []
    for snap in q.stream():
        d = snap.to_dict()
        t = ledger_trade_from_firestore_doc(tenant_id=tenant_id, doc=d)
        if t is None:
            continue
        parsed.append(t)

    snapshots_by_perf_id = build_monthly_strategy_performance_snapshots(
        parsed,
        year=year,
        month=month,
        mark_prices=mark_prices,
    )

    # Filter down to this tenant (defensive: compute_strategy_pnl groups by tenant_id too).
    return {pid: s for pid, s in snapshots_by_perf_id.items() if s.tenant_id == tenant_id}


def write_strategy_performance_snapshots(
    *,
    db: Any,
    tenant_id: str,
    snapshots_by_perf_id: Mapping[str, StrategyPerformanceSnapshot],
    merge: bool = True,
) -> int:
    """
    Write snapshots to:
      tenants/{tid}/strategy_performance/{perf_id}
    """
    paths = TenantPaths(tenant_id=tenant_id)
    wrote = 0
    for perf_id, snap in snapshots_by_perf_id.items():
        perf_path = f"{paths.strategy_performance}/{perf_id}"
        db.document(perf_path).set(snap.to_firestore_doc(), merge=merge)
        wrote += 1
    return wrote

