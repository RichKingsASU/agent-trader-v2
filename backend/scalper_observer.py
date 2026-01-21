from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from typing import Any, Mapping, Sequence

try:  # Python 3.9+
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]


NY_TZ = ZoneInfo("America/New_York") if ZoneInfo is not None else None
MARKET_CLOSE_GUARD_ET = time(15, 45, 0)  # 15:45 ET


@dataclass(frozen=True)
class ObserverResult:
    overall_verdict: str
    reason_codes: list[str] = field(default_factory=list)


def _is_market_close_imminent(*, now_utc: datetime) -> bool:
    """
    Return True at/after 15:45 ET.

    If tz database is unavailable, fail open (treat as not imminent) to avoid
    false positives in minimal runtimes.
    """
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    if NY_TZ is None:  # pragma: no cover
        return False
    ny = now_utc.astimezone(NY_TZ)
    return ny.time() >= MARKET_CLOSE_GUARD_ET


def evaluate_scalper_observer(
    *,
    signal: Mapping[str, Any] | None,
    market_regime: Mapping[str, Any] | None = None,
    shadow_trade_history: Sequence[Mapping[str, Any]] = (),
    structured_events: Sequence[Mapping[str, Any]] = (),
    now_utc: datetime | None = None,
    rate_limited: bool = False,
    kill_switch: bool = False,
    execution_enabled: bool = True,
    risk_allowed: bool = True,
    shadow_execution_completed: bool = False,
) -> ObserverResult:
    """
    Pure, Firestore-free observer truth table for scalper decisions.

    Inputs are intentionally generic JSON-like shapes so tests can supply
    simple dicts without external dependencies.
    """
    _ = market_regime
    _ = shadow_trade_history
    _ = structured_events

    now = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)

    # Terminal success: if a shadow execution already completed, surface it.
    if shadow_execution_completed:
        return ObserverResult(
            overall_verdict="SHADOW_EXECUTION_COMPLETED",
            reason_codes=["shadow_execution_completed"],
        )

    # Hard execution gates.
    if kill_switch:
        return ObserverResult(overall_verdict="BLOCKED", reason_codes=["kill_switch_enabled"])

    if not execution_enabled:
        return ObserverResult(overall_verdict="BLOCKED", reason_codes=["execution_disabled"])

    # Market close guard.
    if _is_market_close_imminent(now_utc=now):
        return ObserverResult(overall_verdict="BLOCKED", reason_codes=["market_close_imminent"])

    # Rate limiting (anti-overtrading).
    if rate_limited:
        return ObserverResult(overall_verdict="BLOCKED", reason_codes=["rate_limited"])

    # No signal / no-op (delta within threshold).
    if not signal:
        return ObserverResult(overall_verdict="NO_SIGNAL", reason_codes=["no_signal"])

    try:
        net_delta = float(signal.get("net_delta"))  # type: ignore[arg-type]
        threshold = float(signal.get("threshold"))  # type: ignore[arg-type]
    except Exception:
        net_delta = None
        threshold = None

    if net_delta is not None and threshold is not None:
        if abs(net_delta) <= abs(threshold):
            return ObserverResult(overall_verdict="NO_SIGNAL", reason_codes=["net_delta_within_threshold"])

    # Risk gate.
    if not risk_allowed:
        return ObserverResult(overall_verdict="BLOCKED", reason_codes=["risk_denied"])

    # Otherwise: signal is actionable.
    return ObserverResult(overall_verdict="ALLOW", reason_codes=["signal_emitted"])

