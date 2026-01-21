from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.scalper_observer import evaluate_scalper_observer


def _dt(iso_utc: str) -> datetime:
    # Helper for readable fixed times
    if iso_utc.endswith("Z"):
        iso_utc = iso_utc[:-1] + "+00:00"
    return datetime.fromisoformat(iso_utc).astimezone(timezone.utc)


def test_no_signal_emitted_net_delta_within_threshold() -> None:
    r = evaluate_scalper_observer(
        signal={"net_delta": 0.10, "threshold": 0.15},
        now_utc=_dt("2026-01-21T17:00:00Z"),
    )
    assert r.overall_verdict == "NO_SIGNAL"
    assert r.reason_codes == ["net_delta_within_threshold"]


def test_rate_limited_blocks() -> None:
    r = evaluate_scalper_observer(
        signal={"net_delta": 0.50, "threshold": 0.15},
        rate_limited=True,
        now_utc=_dt("2026-01-21T17:00:00Z"),
    )
    assert r.overall_verdict == "BLOCKED"
    assert "rate_limited" in r.reason_codes


def test_market_close_imminent_blocks_at_1545_et() -> None:
    # 15:45 ET on 2026-01-21 is 20:45 UTC (standard time).
    r = evaluate_scalper_observer(
        signal={"net_delta": 0.50, "threshold": 0.15},
        now_utc=_dt("2026-01-21T20:45:00Z"),
    )
    assert r.overall_verdict == "BLOCKED"
    assert "market_close_imminent" in r.reason_codes


def test_execution_blocked_kill_switch() -> None:
    r = evaluate_scalper_observer(
        signal={"net_delta": 0.50, "threshold": 0.15},
        kill_switch=True,
        now_utc=_dt("2026-01-21T17:00:00Z"),
    )
    assert r.overall_verdict == "BLOCKED"
    assert "kill_switch_enabled" in r.reason_codes


def test_execution_blocked_execution_enabled_false() -> None:
    r = evaluate_scalper_observer(
        signal={"net_delta": 0.50, "threshold": 0.15},
        execution_enabled=False,
        now_utc=_dt("2026-01-21T17:00:00Z"),
    )
    assert r.overall_verdict == "BLOCKED"
    assert "execution_disabled" in r.reason_codes


def test_risk_denied_blocks() -> None:
    r = evaluate_scalper_observer(
        signal={"net_delta": 0.50, "threshold": 0.15},
        risk_allowed=False,
        now_utc=_dt("2026-01-21T17:00:00Z"),
    )
    assert r.overall_verdict == "BLOCKED"
    assert "risk_denied" in r.reason_codes


def test_shadow_execution_completed() -> None:
    r = evaluate_scalper_observer(
        signal={"net_delta": 0.50, "threshold": 0.15},
        shadow_execution_completed=True,
        now_utc=_dt("2026-01-21T17:00:00Z"),
    )
    assert r.overall_verdict == "SHADOW_EXECUTION_COMPLETED"
    assert "shadow_execution_completed" in r.reason_codes

