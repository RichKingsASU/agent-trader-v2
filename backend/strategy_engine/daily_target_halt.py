from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

DAILY_TARGET_RETURN_PCT: float = 0.04


@dataclass(frozen=True, slots=True)
class DailyTargetMetrics:
    starting_equity_usd: float
    current_equity_usd: float
    daily_return_pct: float
    updated_at_iso: str | None = None


def _as_float(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, bool):
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return 0.0
        try:
            return float(s)
        except Exception:
            return 0.0
    return 0.0


def compute_daily_return_pct(*, current_equity_usd: float, starting_equity_usd: float) -> float:
    start = float(starting_equity_usd or 0.0)
    if start <= 0.0:
        return 0.0
    return (float(current_equity_usd or 0.0) - start) / start


def _read_user_account_snapshot(*, db: Any, uid: str) -> dict[str, Any]:
    # Lazy imports: keep this module unit-testable without firebase/firestore deps.
    from backend.persistence.firestore_retry import with_firestore_retry
    from backend.risk.daily_capital_snapshot import DailyCapitalSnapshotError

    snap = with_firestore_retry(
        lambda: db.collection("users").document(uid).collection("alpacaAccounts").document("snapshot").get()
    )
    if not snap.exists:
        raise DailyCapitalSnapshotError(
            f"Missing account snapshot: users/{uid}/alpacaAccounts/snapshot (cannot compute daily_return_pct)"
        )
    return snap.to_dict() or {}


def load_daily_target_metrics_from_firestore(*, db: Any, tenant_id: str, uid: str) -> DailyTargetMetrics | None:
    """
    Best-effort:
    - Reads current equity from the warm-cache account snapshot.
    - Materializes the immutable DailyCapitalSnapshot to get starting equity.

    Returns None if inputs/state are missing.
    """
    uid_s = str(uid or "").strip()
    tenant_s = str(tenant_id or "").strip()
    if not uid_s or not tenant_s:
        return None

    # Lazy imports: keep this module unit-testable without firebase/firestore deps.
    from backend.risk.daily_capital_snapshot import DailyCapitalSnapshotStore
    from backend.time.nyse_time import to_nyse

    now = datetime.now(timezone.utc)
    acct = _read_user_account_snapshot(db=db, uid=uid_s)

    # NYSE day anchor.
    trading_date_ny = to_nyse(now).date()
    store = DailyCapitalSnapshotStore(db=db)
    snap = store.get_or_create_once(
        tenant_id=tenant_s,
        uid=uid_s,
        trading_date_ny=trading_date_ny,
        account_snapshot=acct,
        now_utc=now,
        source="strategy_engine.daily_target_halt",
    )
    snap.assert_date_match(trading_date_ny=trading_date_ny)

    current_equity = _as_float(acct.get("equity"))
    starting_equity = float(snap.starting_equity_usd or 0.0)
    daily_return_pct = compute_daily_return_pct(
        current_equity_usd=current_equity,
        starting_equity_usd=starting_equity,
    )

    updated_at_iso = acct.get("updated_at_iso") if isinstance(acct.get("updated_at_iso"), str) else None
    return DailyTargetMetrics(
        starting_equity_usd=starting_equity,
        current_equity_usd=current_equity,
        daily_return_pct=float(daily_return_pct),
        updated_at_iso=updated_at_iso,
    )


def _default_check_interval_s() -> float:
    raw = (os.getenv("STRATEGY_DAILY_TARGET_CHECK_INTERVAL_S") or "").strip()
    if not raw:
        return 10.0
    try:
        return max(0.5, float(raw))
    except Exception:
        return 10.0


class DailyTargetHaltController:
    """
    Process-local, strategy-local halt condition:
    - Once daily_return_pct >= DAILY_TARGET_RETURN_PCT, stop emitting new intents/proposals.
    - Emit exactly one structured log line: strategy.halted.daily_target
    """

    def __init__(
        self,
        *,
        strategy_name: str,
        tenant_id: str,
        uid: str,
        log_fn: Callable[..., None],
        threshold: float = DAILY_TARGET_RETURN_PCT,
        metrics_provider: Callable[[], DailyTargetMetrics | None] | None = None,
        check_interval_s: float | None = None,
        now_mono_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._strategy_name = str(strategy_name or "").strip() or "unknown"
        self._tenant_id = str(tenant_id or "").strip()
        self._uid = str(uid or "").strip()
        self._log_fn = log_fn
        self._threshold = float(threshold)
        self._check_interval_s = float(check_interval_s if check_interval_s is not None else _default_check_interval_s())
        self._now_mono = now_mono_fn

        if metrics_provider is None:
            # Lazy import: keep module importable without firebase_admin for unit tests.
            from backend.persistence.firebase_client import get_firestore_client

            db = get_firestore_client()
            self._metrics_provider = lambda: load_daily_target_metrics_from_firestore(
                db=db, tenant_id=self._tenant_id, uid=self._uid
            )
        else:
            self._metrics_provider = metrics_provider

        self._halted = False
        self._halt_log_emitted = False
        self._last_check_mono: float | None = None
        self._last_metrics: DailyTargetMetrics | None = None

    @property
    def halted(self) -> bool:
        return bool(self._halted)

    @property
    def last_metrics(self) -> DailyTargetMetrics | None:
        return self._last_metrics

    def should_halt(self, *, symbol: str | None = None, iteration_id: str | None = None) -> bool:
        if self._halted:
            return True

        # If we can't identify the account, we can't compute the daily return. Fail open.
        if not self._tenant_id or not self._uid:
            return False

        now = float(self._now_mono())
        if self._last_check_mono is not None and (now - self._last_check_mono) < self._check_interval_s:
            m = self._last_metrics
            if m is not None and float(m.daily_return_pct) >= self._threshold:
                self._halted = True
                self._emit_once(metrics=m, symbol=symbol, iteration_id=iteration_id)
                return True
            return False

        self._last_check_mono = now
        try:
            m = self._metrics_provider()
        except Exception:
            # Fail open on telemetry errors.
            m = None
        self._last_metrics = m

        if m is None:
            return False
        if float(m.daily_return_pct) >= self._threshold:
            self._halted = True
            self._emit_once(metrics=m, symbol=symbol, iteration_id=iteration_id)
            return True
        return False

    def _emit_once(self, *, metrics: DailyTargetMetrics, symbol: str | None, iteration_id: str | None) -> None:
        if self._halt_log_emitted:
            return
        self._halt_log_emitted = True
        try:
            self._log_fn(
                intent_type="strategy.halted.daily_target",
                severity="WARNING",
                strategy=self._strategy_name,
                tenant_id=self._tenant_id,
                uid=self._uid,
                symbol=(str(symbol).strip().upper() if symbol else None),
                iteration_id=(str(iteration_id).strip() if iteration_id else None),
                daily_return_pct=float(metrics.daily_return_pct),
                daily_target_pct=float(self._threshold),
                current_equity_usd=float(metrics.current_equity_usd),
                starting_equity_usd=float(metrics.starting_equity_usd),
                account_snapshot_updated_at_iso=metrics.updated_at_iso,
            )
        except Exception:
            # Never crash strategy logic due to logging.
            return

