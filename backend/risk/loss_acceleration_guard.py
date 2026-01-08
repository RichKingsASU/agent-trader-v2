from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from backend.persistence.firebase_client import get_firestore_client
from backend.risk.drawdown_velocity import EquityPoint, compute_drawdown_velocity, DrawdownVelocity

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _bool_env(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "on"}


def _float_env(name: str, default: float) -> float:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return float(default)
    return float(v)


def _int_env(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return int(default)
    return int(v)


@dataclass(frozen=True, slots=True)
class LossAccelerationConfig:
    """
    Conservative defaults (fail-safe):
    - throttle at ~1% drawdown added over 10 minutes (0.10 pct/min)
    - pause at ~2.5% drawdown added over 10 minutes (0.25 pct/min)
    """

    enabled: bool = True
    window_seconds: int = 600
    min_points: int = 3

    throttle_velocity_pct_per_min: float = 0.10
    pause_velocity_pct_per_min: float = 0.25

    # Throttle pacing (minimum time between accepted trades while throttled)
    throttle_min_interval_seconds: int = 120

    # Pause duration when triggered
    pause_cooldown_seconds: int = 1800

    # Optional noise gate: require at least this current drawdown to act
    min_drawdown_to_act_pct: float = 0.50

    @staticmethod
    def from_env() -> "LossAccelerationConfig":
        return LossAccelerationConfig(
            enabled=_bool_env("LOSS_ACCEL_ENABLED", True),
            window_seconds=_int_env("LOSS_ACCEL_WINDOW_S", 600),
            min_points=_int_env("LOSS_ACCEL_MIN_POINTS", 3),
            throttle_velocity_pct_per_min=_float_env("LOSS_ACCEL_THROTTLE_DD_VELOCITY_PCT_PER_MIN", 0.10),
            pause_velocity_pct_per_min=_float_env("LOSS_ACCEL_PAUSE_DD_VELOCITY_PCT_PER_MIN", 0.25),
            throttle_min_interval_seconds=_int_env("LOSS_ACCEL_THROTTLE_MIN_INTERVAL_S", 120),
            pause_cooldown_seconds=_int_env("LOSS_ACCEL_PAUSE_COOLDOWN_S", 1800),
            min_drawdown_to_act_pct=_float_env("LOSS_ACCEL_MIN_DRAWDOWN_TO_ACT_PCT", 0.50),
        )


@dataclass(frozen=True, slots=True)
class LossAccelerationDecision:
    action: str  # "ok" | "throttle" | "pause"
    metrics: Optional[DrawdownVelocity] = None
    retry_after_seconds: Optional[int] = None
    pause_until: Optional[datetime] = None
    reason: Optional[str] = None


class LossAccelerationGuard:
    """
    Stateless guard: reads equity history, computes drawdown velocity,
    and emits decisions. Callers can optionally persist enforcement state.
    """

    def __init__(self, *, config: LossAccelerationConfig | None = None):
        self._cfg = config or LossAccelerationConfig.from_env()

    def compute_metrics(self, *, uid: Optional[str] = None) -> Optional[DrawdownVelocity]:
        if not self._cfg.enabled:
            return None
        points = self._fetch_equity_points(uid=uid, limit=50)
        if not points:
            return None
        return compute_drawdown_velocity(
            points,
            window_seconds=self._cfg.window_seconds,
            now=_utc_now(),
            min_points=self._cfg.min_points,
        )

    def decide(self, *, uid: Optional[str] = None) -> LossAccelerationDecision:
        if not self._cfg.enabled:
            return LossAccelerationDecision(action="ok", reason="disabled")

        metrics = self.compute_metrics(uid=uid)
        if metrics is None:
            return LossAccelerationDecision(action="ok", metrics=None, reason="insufficient_equity_history")

        # Noise gate: only act when drawdown is non-trivial.
        if metrics.current_drawdown_pct < self._cfg.min_drawdown_to_act_pct:
            return LossAccelerationDecision(action="ok", metrics=metrics, reason="drawdown_below_min_gate")

        if metrics.velocity_pct_per_min >= self._cfg.pause_velocity_pct_per_min:
            until = _utc_now() + timedelta(seconds=int(self._cfg.pause_cooldown_seconds))
            return LossAccelerationDecision(
                action="pause",
                metrics=metrics,
                pause_until=until,
                reason="loss_acceleration_pause",
            )

        if metrics.velocity_pct_per_min >= self._cfg.throttle_velocity_pct_per_min:
            return LossAccelerationDecision(
                action="throttle",
                metrics=metrics,
                retry_after_seconds=int(self._cfg.throttle_min_interval_seconds),
                reason="loss_acceleration_throttle",
            )

        return LossAccelerationDecision(action="ok", metrics=metrics, reason="ok")

    def _fetch_equity_points(self, *, uid: Optional[str], limit: int = 50) -> list[EquityPoint]:
        """
        Best-effort equity history fetch.

        Preferred path (multi-tenant/user-scoped):
          users/{uid}/alpacaAccounts/snapshot/equity_history
        Fallback path (single-account):
          alpacaAccounts/snapshot/equity_history
        """
        db = get_firestore_client()
        now = _utc_now()
        try:
            from google.cloud import firestore as gc_firestore

            _DESC = gc_firestore.Query.DESCENDING
        except Exception:
            _DESC = None

        def _read_from(query) -> list[EquityPoint]:
            out: list[EquityPoint] = []
            try:
                for doc in query.stream():
                    d = doc.to_dict() or {}
                    ts = d.get("ts")
                    eq = d.get("equity")
                    if ts is None or eq is None:
                        continue
                    if not isinstance(ts, datetime):
                        continue
                    try:
                        equity = float(str(eq))
                    except Exception:
                        continue
                    if equity <= 0:
                        continue
                    out.append(EquityPoint(ts=ts.astimezone(timezone.utc), equity=equity))
            except Exception as e:
                logger.debug("loss_accel: equity_history query failed: %s", e)
            # Clip to [now-window, now] later in compute; keep as-is here.
            return out

        # Query newest first; we’ll sort inside compute.
        # If direction enum is unavailable, fall back to ascending.
        points: list[EquityPoint] = []

        if uid:
            try:
                base = (
                    db.collection("users")
                    .document(str(uid))
                    .collection("alpacaAccounts")
                    .document("snapshot")
                    .collection("equity_history")
                )
                q = base.order_by("ts", direction=_DESC) if _DESC is not None else base.order_by("ts")
                q = q.limit(int(limit))
                points = _read_from(q)
            except Exception:
                points = []

        if not points:
            try:
                base = (
                    db.collection("alpacaAccounts")
                    .document("snapshot")
                    .collection("equity_history")
                )
                q = base.order_by("ts", direction=_DESC) if _DESC is not None else base.order_by("ts")
                q = q.limit(int(limit))
                points = _read_from(q)
            except Exception:
                # Last resort: read without ordering (not ideal but best-effort).
                try:
                    q = (
                        db.collection("alpacaAccounts")
                        .document("snapshot")
                        .collection("equity_history")
                        .limit(int(limit))
                    )
                    points = _read_from(q)
                except Exception:
                    points = []

        # If timestamps are missing/odd, compute() will handle.
        # Also drop any points that are in the future (clock skew).
        points = [p for p in points if p.ts <= now + timedelta(seconds=5)]
        return points

