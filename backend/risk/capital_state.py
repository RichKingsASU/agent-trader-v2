"""
Canonical Capital State (single authoritative source).

This module centralizes all capital / buying power derived values and exposes:
- available_capital (USD)
- reserved_capital (USD)
- max_risk_per_trade (USD)

It also provides safety guards to prevent:
- negative available capital
- double reservation
- exceeding the daily risk cap

Notes:
- This is an in-process authority. Cross-process coordination is out of scope for this refactor.
- The "base capital" source is the broker-reported buying power from the Firestore warm-cache snapshot.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from backend.persistence.firebase_client import get_firestore_client
from backend.persistence.firestore_retry import with_firestore_retry

logger = logging.getLogger(__name__)


class CapitalStateError(RuntimeError):
    pass


class DoubleReservationError(CapitalStateError):
    pass


class NegativeAvailableCapitalError(CapitalStateError):
    pass


class DailyRiskCapExceededError(CapitalStateError):
    pass


class WarmCacheError(CapitalStateError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_float(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            return 0.0
        return float(s)
    raise TypeError(f"Expected number-like value, got {type(v).__name__}")


def _env_float(name: str, default: str) -> float:
    try:
        return float(str(os.getenv(name, default)).strip())
    except Exception:
        return float(default)


def _read_alpaca_snapshot_doc(
    *,
    db=None,
    user_id: str | None = None,
    require_exists: bool = True,
) -> Dict[str, Any]:
    """
    Warm-cache read for broker-reported capital fields.

    Multi-tenant path: users/{user_id}/alpacaAccounts/snapshot
    Legacy fallback: alpacaAccounts/snapshot
    """
    client = db or get_firestore_client()

    def _get():
        if user_id:
            return (
                client.collection("users")
                .document(user_id)
                .collection("alpacaAccounts")
                .document("snapshot")
                .get()
            )
        return client.collection("alpacaAccounts").document("snapshot").get()

    snap = with_firestore_retry(_get)
    if require_exists and not snap.exists:
        path = f"users/{user_id}/alpacaAccounts/snapshot" if user_id else "alpacaAccounts/snapshot"
        raise WarmCacheError(f"Missing warm-cache snapshot at Firestore doc {path}")
    return snap.to_dict() or {}


def _is_snapshot_stale(snap: Dict[str, Any], *, max_age_s: float) -> bool:
    updated_at_iso = (snap.get("updated_at_iso") or "").strip() if isinstance(snap.get("updated_at_iso"), str) else ""
    if not updated_at_iso:
        # If the producer doesn't write a timestamp, accept (back-compat).
        return False
    try:
        updated_at = datetime.fromisoformat(updated_at_iso.replace("Z", "+00:00"))
        age_s = max(0.0, (_utc_now() - updated_at).total_seconds())
        return age_s > max_age_s
    except Exception:
        # If parsing fails, be conservative.
        return True


@dataclass(frozen=True)
class CapitalSnapshot:
    available_capital: float
    reserved_capital: float
    max_risk_per_trade: float
    daily_risk_cap: float
    daily_risk_used: float
    as_of: datetime
    source: str


class _CapitalState:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._base_capital_usd: float = 0.0  # broker-reported buying power (USD)
        self._reserved_by_id: dict[str, float] = {}
        self._daily_risk_used_by_id: dict[str, float] = {}
        self._daily_risk_used_usd: float = 0.0
        self._daily_risk_cap_usd: float = float("inf")
        self._max_risk_per_trade_usd: float = 0.0
        self._risk_day_utc: str = _utc_now().date().isoformat()
        self._last_refresh_mono: float = 0.0
        self._last_refresh_as_of: datetime = datetime.fromtimestamp(0, tz=timezone.utc)
        self._last_source: str = "uninitialized"

    def _roll_day_if_needed(self) -> None:
        today = _utc_now().date().isoformat()
        if today != self._risk_day_utc:
            self._risk_day_utc = today
            self._daily_risk_used_by_id.clear()
            self._daily_risk_used_usd = 0.0

    def refresh_from_warm_cache(
        self,
        *,
        db=None,
        user_id: str | None = None,
        max_age_s: float | None = None,
        min_refresh_interval_s: float | None = None,
    ) -> CapitalSnapshot:
        """
        Refresh base capital from Firestore warm-cache (buying_power).

        This keeps existing behavior: if the snapshot is missing/stale/invalid, base capital is forced to 0.
        """
        if max_age_s is None:
            max_age_s = _env_float("CAPITAL_STATE_SNAPSHOT_MAX_AGE_S", "300")
        if min_refresh_interval_s is None:
            min_refresh_interval_s = _env_float("CAPITAL_STATE_MIN_REFRESH_INTERVAL_S", "2")

        with self._lock:
            self._roll_day_if_needed()
            now_mono = time.monotonic()
            if self._last_refresh_mono and (now_mono - self._last_refresh_mono) < float(min_refresh_interval_s):
                return self.snapshot()

            try:
                snap = _read_alpaca_snapshot_doc(db=db, user_id=user_id, require_exists=True)
            except Exception as e:  # noqa: BLE001
                logger.warning("capital_state.warm_cache_read_failed; forcing base_capital=0: %s", e)
                self._set_base_capital_usd(0.0, source="warm-cache:read_failed")
                self._last_refresh_mono = now_mono
                self._last_refresh_as_of = _utc_now()
                return self.snapshot()

            if _is_snapshot_stale(snap, max_age_s=float(max_age_s)):
                logger.warning("capital_state.warm_cache_stale; forcing base_capital=0")
                self._set_base_capital_usd(0.0, source="warm-cache:stale")
                self._last_refresh_mono = now_mono
                self._last_refresh_as_of = _utc_now()
                return self.snapshot()

            buying_power = _as_float(snap.get("buying_power"))
            if buying_power <= 0:
                logger.warning(
                    "capital_state.warm_cache_buying_power_nonpositive; forcing base_capital=0 (buying_power=%s)",
                    buying_power,
                )
                self._set_base_capital_usd(0.0, source="warm-cache:buying_power<=0")
                self._last_refresh_mono = now_mono
                self._last_refresh_as_of = _utc_now()
                return self.snapshot()

            equity = _as_float(snap.get("equity"))
            self._set_base_capital_usd(float(buying_power), source="warm-cache:buying_power")
            self._recompute_risk_limits(equity_usd=equity if equity > 0 else float(buying_power))
            self._last_refresh_mono = now_mono
            self._last_refresh_as_of = _utc_now()
            return self.snapshot()

    def _set_base_capital_usd(self, new_base: float, *, source: str) -> None:
        reserved = sum(self._reserved_by_id.values())
        if new_base < 0:
            # Do not allow negative base; treat as zero.
            new_base = 0.0

        if new_base < reserved:
            # Prevent negative available capital while preserving existing reservations.
            logger.error(
                "capital_state.base_capital_below_reserved; clamping base_capital to reserved "
                "(new_base=%s reserved=%s source=%s)",
                new_base,
                reserved,
                source,
            )
            new_base = reserved

        self._base_capital_usd = float(new_base)
        self._last_source = source

    def _recompute_risk_limits(self, *, equity_usd: float) -> None:
        """
        Risk budgets are derived from capital/equity unless explicitly overridden.

        - max_risk_per_trade: default 5% of base capital (matches existing risk_manager behavior)
        - daily_risk_cap: default 2% of equity (matches circuit breaker daily loss threshold)
        """
        # Max risk per trade
        override_trade_usd = _env_float("CAPITAL_MAX_RISK_PER_TRADE_USD", "0")
        if override_trade_usd > 0:
            self._max_risk_per_trade_usd = float(override_trade_usd)
        else:
            pct = _env_float("CAPITAL_MAX_RISK_PER_TRADE_PCT", "0.05")
            self._max_risk_per_trade_usd = max(0.0, self._base_capital_usd * float(pct))

        # Daily risk cap
        override_daily_usd = _env_float("CAPITAL_DAILY_RISK_CAP_USD", "0")
        if override_daily_usd > 0:
            self._daily_risk_cap_usd = float(override_daily_usd)
        else:
            pct = _env_float("CAPITAL_DAILY_RISK_CAP_PCT", "0.02")
            self._daily_risk_cap_usd = max(0.0, float(equity_usd) * float(pct))

        # If the cap was lowered below already-used risk, clamp used to cap (prevents negative "remaining").
        if self._daily_risk_used_usd > self._daily_risk_cap_usd:
            logger.error(
                "capital_state.daily_risk_used_exceeds_cap; clamping used to cap (used=%s cap=%s)",
                self._daily_risk_used_usd,
                self._daily_risk_cap_usd,
            )
            self._daily_risk_used_usd = self._daily_risk_cap_usd

    def snapshot(self) -> CapitalSnapshot:
        with self._lock:
            self._roll_day_if_needed()
            reserved = sum(self._reserved_by_id.values())
            available = self._base_capital_usd - reserved
            if available < -1e-9:
                # Should never happen due to clamping, but keep it as a hard guard.
                raise NegativeAvailableCapitalError(
                    f"available_capital would be negative (base={self._base_capital_usd} reserved={reserved})"
                )
            return CapitalSnapshot(
                available_capital=max(0.0, float(available)),
                reserved_capital=float(reserved),
                max_risk_per_trade=float(self._max_risk_per_trade_usd),
                daily_risk_cap=float(self._daily_risk_cap_usd),
                daily_risk_used=float(self._daily_risk_used_usd),
                as_of=self._last_refresh_as_of,
                source=self._last_source,
            )

    def reserve_capital(self, *, reservation_id: str, amount_usd: float) -> None:
        """
        Reserve capital for an in-flight decision/execution path.
        """
        rid = str(reservation_id or "").strip()
        if not rid:
            raise ValueError("reservation_id must be non-empty")
        amt = float(amount_usd)
        if amt <= 0:
            raise ValueError("reserve amount_usd must be positive")

        with self._lock:
            self._roll_day_if_needed()
            if rid in self._reserved_by_id:
                raise DoubleReservationError(f"reservation_id {rid!r} is already reserved")
            snap = self.snapshot()
            if amt > snap.available_capital + 1e-9:
                raise NegativeAvailableCapitalError(
                    f"insufficient available_capital for reservation (requested={amt} available={snap.available_capital})"
                )
            self._reserved_by_id[rid] = amt

    def release_capital(self, *, reservation_id: str) -> None:
        rid = str(reservation_id or "").strip()
        if not rid:
            return
        with self._lock:
            self._reserved_by_id.pop(rid, None)

    def record_daily_risk(self, *, risk_id: str, amount_usd: float) -> None:
        """
        Record risk usage against the daily cap. Intended to be called once per executed trade.
        """
        rid = str(risk_id or "").strip()
        if not rid:
            raise ValueError("risk_id must be non-empty")
        amt = float(amount_usd)
        if amt <= 0:
            raise ValueError("amount_usd must be positive")

        with self._lock:
            self._roll_day_if_needed()
            if rid in self._daily_risk_used_by_id:
                # Double-counting risk is an existential bug; refuse loudly.
                raise DoubleReservationError(f"risk_id {rid!r} was already recorded")
            projected = self._daily_risk_used_usd + amt
            if projected > self._daily_risk_cap_usd + 1e-9:
                raise DailyRiskCapExceededError(
                    f"daily risk cap exceeded (projected={projected} cap={self._daily_risk_cap_usd})"
                )
            self._daily_risk_used_by_id[rid] = amt
            self._daily_risk_used_usd = projected


_STATE = _CapitalState()


# ---- Public (read-only) getters ----
def get_capital_snapshot() -> CapitalSnapshot:
    return _STATE.snapshot()


def get_available_capital_usd() -> float:
    return _STATE.snapshot().available_capital


def get_reserved_capital_usd() -> float:
    return _STATE.snapshot().reserved_capital


def get_max_risk_per_trade_usd() -> float:
    return _STATE.snapshot().max_risk_per_trade


# ---- Public refresh + guard APIs ----
def refresh_capital_state_from_warm_cache(
    *,
    db=None,
    user_id: str | None = None,
    max_age_s: float | None = None,
    min_refresh_interval_s: float | None = None,
) -> CapitalSnapshot:
    return _STATE.refresh_from_warm_cache(
        db=db,
        user_id=user_id,
        max_age_s=max_age_s,
        min_refresh_interval_s=min_refresh_interval_s,
    )


def get_warm_cache_available_capital_usd(
    *,
    db=None,
    user_id: str | None = None,
    max_age_s: float | None = None,
) -> Tuple[float, Dict[str, Any]]:
    """
    Convenience: one-shot fetch of available capital from warm-cache (does not mutate reservations).
    """
    if max_age_s is None:
        max_age_s = _env_float("CAPITAL_STATE_SNAPSHOT_MAX_AGE_S", "300")
    try:
        snap = _read_alpaca_snapshot_doc(db=db, user_id=user_id, require_exists=True)
    except Exception as e:  # noqa: BLE001
        logger.warning("capital_state.get_warm_cache_available_capital_usd_failed; forcing 0: %s", e)
        return 0.0, {}

    if _is_snapshot_stale(snap, max_age_s=float(max_age_s)):
        logger.warning("capital_state.get_warm_cache_available_capital_usd_stale; forcing 0")
        return 0.0, snap

    buying_power = _as_float(snap.get("buying_power"))
    if buying_power <= 0:
        logger.warning(
            "capital_state.get_warm_cache_available_capital_usd_nonpositive; forcing 0 (buying_power=%s)",
            buying_power,
        )
        return 0.0, snap

    return float(buying_power), snap


def reserve_capital(*, reservation_id: str, amount_usd: float) -> None:
    _STATE.reserve_capital(reservation_id=reservation_id, amount_usd=amount_usd)


def release_capital(*, reservation_id: str) -> None:
    _STATE.release_capital(reservation_id=reservation_id)


def record_daily_risk(*, risk_id: str, amount_usd: float) -> None:
    _STATE.record_daily_risk(risk_id=risk_id, amount_usd=amount_usd)

