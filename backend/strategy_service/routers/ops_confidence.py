from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Request

from backend.persistence.firebase_client import get_firestore_client
from backend.persistence.firestore_retry import with_firestore_retry
from backend.tenancy.auth import get_tenant_context
from backend.tenancy.context import TenantContext
from backend.time.nyse_time import market_open_dt, to_nyse, to_utc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ops", tags=["ops"])


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_float(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return 0.0
        return float(s)
    raise TypeError(f"Expected number-like value, got {type(v).__name__}")


def _read_user_account_snapshot(db: Any, *, uid: str) -> dict[str, Any]:
    """
    Best-effort read of a user's latest broker snapshot.

    Preferred path (SaaS): users/{uid}/data/snapshot
    Fallback path (alt writer): users/{uid}/alpacaAccounts/snapshot
    """
    # Preferred: users/{uid}/data/snapshot
    snap = with_firestore_retry(
        lambda: db.collection("users").document(uid).collection("data").document("snapshot").get()
    )
    if snap.exists:
        return snap.to_dict() or {}

    # Fallback: users/{uid}/alpacaAccounts/snapshot
    snap2 = with_firestore_retry(
        lambda: db.collection("users")
        .document(uid)
        .collection("alpacaAccounts")
        .document("snapshot")
        .get()
    )
    return snap2.to_dict() if snap2.exists else {}


def _read_open_shadow_trades(db: Any, *, uid: str, limit_n: int = 200) -> list[dict[str, Any]]:
    """
    Read OPEN shadow trades for the user.

    Path: users/{uid}/shadowTradeHistory
    """
    col = db.collection("users").document(uid).collection("shadowTradeHistory")
    try:
        q = col.where("status", "==", "OPEN").limit(int(limit_n))
        docs = with_firestore_retry(lambda: list(q.stream()))
        out = []
        for d in docs:
            payload = d.to_dict() or {}
            payload["id"] = payload.get("shadow_id") or d.id
            out.append(payload)
        return out
    except Exception:
        # Some environments may be missing indexes; fall back to a broader query.
        try:
            q = col.limit(int(limit_n))
            docs = with_firestore_retry(lambda: list(q.stream()))
            out = []
            for d in docs:
                payload = d.to_dict() or {}
                if str(payload.get("status") or "").upper() != "OPEN":
                    continue
                payload["id"] = payload.get("shadow_id") or d.id
                out.append(payload)
            return out
        except Exception:
            return []


def _compute_daily_pnl_from_snapshot(snapshot: dict[str, Any]) -> tuple[Optional[float], Optional[str]]:
    """
    Compute a broker-style daily P&L using snapshot fields, when available.

    - equity: snapshot["equity"] or snapshot["account"]["equity"] or snapshot["raw"]["equity"]
    - last_equity: snapshot["account"]["last_equity"] (alpaca) or snapshot["raw"]["last_equity"]
    """
    acct = snapshot.get("account") if isinstance(snapshot.get("account"), dict) else {}
    raw = snapshot.get("raw") if isinstance(snapshot.get("raw"), dict) else {}

    equity = None
    last_equity = None
    try:
        equity = _as_float(snapshot.get("equity") if snapshot.get("equity") is not None else acct.get("equity") or raw.get("equity"))
    except Exception:
        equity = None
    try:
        last_equity = _as_float(acct.get("last_equity") or raw.get("last_equity"))
    except Exception:
        last_equity = None

    if equity is None or last_equity is None or last_equity <= 0:
        return None, None

    return float(equity - last_equity), "equity_minus_last_equity"


def _read_equity_history_points(db: Any, *, uid: str, limit_n: int = 390) -> list[tuple[datetime, float]]:
    """
    Best-effort read of equity time-series points.

    Preferred (user-scoped if available):
      users/{uid}/alpacaAccounts/snapshot/equity_history
    Fallback (legacy single-account):
      alpacaAccounts/snapshot/equity_history
    """
    points: list[tuple[datetime, float]] = []

    def _read_from(query) -> None:
        nonlocal points
        for doc in query.stream():
            d = doc.to_dict() or {}
            ts = d.get("ts")
            eq = d.get("equity")
            if not isinstance(ts, datetime):
                continue
            try:
                equity = float(str(eq))
            except Exception:
                continue
            if equity <= 0:
                continue
            points.append((ts.astimezone(timezone.utc), equity))

    # Try user-scoped first.
    try:
        base = (
            db.collection("users")
            .document(uid)
            .collection("alpacaAccounts")
            .document("snapshot")
            .collection("equity_history")
        )
        q = base.order_by("ts").limit(int(limit_n))
        with_firestore_retry(lambda: _read_from(q))
    except Exception:
        points = []

    # Fallback to legacy global.
    if not points:
        try:
            base = db.collection("alpacaAccounts").document("snapshot").collection("equity_history")
            q = base.order_by("ts").limit(int(limit_n))
            with_firestore_retry(lambda: _read_from(q))
        except Exception:
            points = []

    points.sort(key=lambda x: x[0])
    return points


def _compute_drawdown_pct_today(*, equity_points: list[tuple[datetime, float]]) -> tuple[Optional[float], Optional[str]]:
    """
    Compute drawdown percent for today (NY trading day), based on equity history points.
    """
    if not equity_points:
        return None, None

    now = _utc_now()
    ny = to_nyse(now)
    open_ny = market_open_dt(ny.date())
    open_utc = to_utc(open_ny)

    today_points = [(ts, eq) for (ts, eq) in equity_points if ts >= open_utc and ts <= now]
    if len(today_points) < 2:
        return None, None

    hwm = max(eq for _, eq in today_points)
    cur = today_points[-1][1]
    if hwm <= 0:
        return None, None
    dd = max(0.0, (hwm - cur) / hwm * 100.0)
    return float(dd), "hwm_since_nyse_open"


@router.get("/confidence_snapshot")
def confidence_snapshot(request: Request) -> dict[str, Any]:
    """
    Confidence Snapshot (paper/shadow trading operator clarity).

    Surfaces:
    - open positions (shadow trades)
    - unrealized P&L (shadow trades)
    - daily P&L (broker snapshot, best-effort)
    - drawdown % (equity history, best-effort)
    """
    ctx: TenantContext = get_tenant_context(request)
    db = get_firestore_client()

    acct = _read_user_account_snapshot(db, uid=ctx.uid)
    open_trades = _read_open_shadow_trades(db, uid=ctx.uid, limit_n=200)

    # Open positions summary (group by symbol)
    positions: dict[str, dict[str, Any]] = {}
    unrealized_total = 0.0
    for t in open_trades:
        sym = str(t.get("symbol") or "").upper().strip() or "UNKNOWN"
        side = str(t.get("side") or "").upper().strip()
        qty = 0.0
        try:
            qty = float(str(t.get("quantity") or "0"))
        except Exception:
            qty = 0.0
        signed_qty = qty if side == "BUY" else (-qty if side == "SELL" else qty)

        pnl = 0.0
        try:
            pnl = float(str(t.get("current_pnl") or "0"))
        except Exception:
            pnl = 0.0
        unrealized_total += pnl

        if sym not in positions:
            positions[sym] = {"symbol": sym, "net_qty": 0.0, "open_trades": 0, "unrealized_pnl": 0.0}
        positions[sym]["net_qty"] = float(positions[sym]["net_qty"]) + float(signed_qty)
        positions[sym]["open_trades"] = int(positions[sym]["open_trades"]) + 1
        positions[sym]["unrealized_pnl"] = float(positions[sym]["unrealized_pnl"]) + float(pnl)

    daily_pnl, daily_source = _compute_daily_pnl_from_snapshot(acct)

    equity_points = _read_equity_history_points(db, uid=ctx.uid, limit_n=390)
    dd_pct, dd_source = _compute_drawdown_pct_today(equity_points=equity_points)

    return {
        "as_of": _utc_now().isoformat(),
        "tenant_id": ctx.tenant_id,
        "uid": ctx.uid,
        "data_sources": {
            "open_positions": f"users/{ctx.uid}/shadowTradeHistory (status == OPEN)",
            "account_snapshot": f"users/{ctx.uid}/data/snapshot (fallback: users/{ctx.uid}/alpacaAccounts/snapshot)",
            "equity_history": f"users/{ctx.uid}/alpacaAccounts/snapshot/equity_history (fallback: alpacaAccounts/snapshot/equity_history)",
        },
        "open_positions": {
            "count": len(open_trades),
            "by_symbol": sorted(list(positions.values()), key=lambda x: (str(x.get("symbol")), -abs(float(x.get("unrealized_pnl") or 0.0)))),
        },
        "unrealized_pnl": {
            "total_usd": float(unrealized_total),
            "source": "shadowTradeHistory.current_pnl (OPEN trades)",
        },
        "daily_pnl": {
            "usd": daily_pnl,
            "source": daily_source,
        },
        "drawdown": {
            "pct": dd_pct,
            "source": dd_source,
        },
        "account_snapshot_fields": {
            "equity": acct.get("equity"),
            "buying_power": acct.get("buying_power"),
            "cash": acct.get("cash"),
            "updated_at_iso": acct.get("updated_at_iso") or acct.get("syncedAt"),
        },
    }

