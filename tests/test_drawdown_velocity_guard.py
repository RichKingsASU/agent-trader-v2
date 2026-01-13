from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from backend.risk.drawdown_velocity import EquityPoint, compute_drawdown_velocity, DrawdownVelocity as HwmDrawdownVelocity


def test_drawdown_velocity_uses_hwm_within_window_and_is_positive_pp_per_min():
    """
    Confirms High Water Mark (HWM) tracking and velocity definition:
    - HWM is the max equity within the rolling window
    - drawdown_pct is computed vs that HWM
    - velocity is positive-only (pp/min) for increasing drawdown
    """
    now = datetime.now(timezone.utc)
    points = [
        EquityPoint(ts=now - timedelta(minutes=10), equity=110.0),  # start at HWM
        EquityPoint(ts=now - timedelta(minutes=5), equity=110.0),
        EquityPoint(ts=now, equity=100.0),  # drawdown increases
    ]

    m = compute_drawdown_velocity(points, window_seconds=600, now=now, min_points=3)
    assert m is not None
    assert m.hwm_equity == pytest.approx(110.0)
    assert m.current_equity == pytest.approx(100.0)
    assert m.current_drawdown_pct == pytest.approx((110.0 - 100.0) / 110.0 * 100.0, rel=1e-6)

    # dd_start = 0, dd_end = 9.0909..., dt = 10 min => 0.90909... pp/min
    assert m.velocity_pct_per_min == pytest.approx(m.current_drawdown_pct / 10.0, rel=1e-6)


def test_drawdown_velocity_is_zero_when_drawdown_is_improving():
    now = datetime.now(timezone.utc)
    points = [
        EquityPoint(ts=now - timedelta(minutes=10), equity=100.0),  # below later HWM
        EquityPoint(ts=now - timedelta(minutes=5), equity=110.0),  # HWM inside window
        EquityPoint(ts=now, equity=105.0),  # recovery vs start; drawdown decreases
    ]

    m = compute_drawdown_velocity(points, window_seconds=600, now=now, min_points=3)
    assert m is not None
    assert m.hwm_equity == pytest.approx(110.0)
    # drawdown at window end is smaller than at window start -> positive-only velocity => 0
    assert m.velocity_pct_per_min == pytest.approx(0.0)


@pytest.mark.parametrize("action,severity", [("pause", "CRITICAL"), ("throttle", "WARNING")])
def test_execution_risk_manager_emits_explicit_halt_event_on_loss_accel_block(action: str, severity: str, monkeypatch):
    """
    Ensures the drawdown-velocity breaker logs an explicit structured event at the block point.
    """
    from backend.execution import engine as exec_engine
    from backend.risk.loss_acceleration_guard import LossAccelerationConfig, LossAccelerationDecision

    now = datetime.now(timezone.utc)
    metrics = HwmDrawdownVelocity(
        window_seconds=600,
        points_used=5,
        hwm_equity=10000.0,
        current_equity=9700.0,
        current_drawdown_pct=3.0,
        velocity_pct_per_min=0.30,
        window_start=now - timedelta(minutes=10),
        window_end=now,
    )

    class _FakeGuard:
        def __init__(self, *args, **kwargs):
            self._cfg = LossAccelerationConfig(
                enabled=True,
                window_seconds=600,
                min_points=3,
                throttle_velocity_pct_per_min=0.10,
                pause_velocity_pct_per_min=0.25,
                throttle_min_interval_seconds=120,
                pause_cooldown_seconds=1800,
                min_drawdown_to_act_pct=0.50,
            )

        @property
        def config(self) -> LossAccelerationConfig:
            return self._cfg

        def decide(self, *, uid=None):
            return LossAccelerationDecision(
                action=action,
                metrics=metrics,
                retry_after_seconds=120 if action == "throttle" else None,
                pause_until=(now + timedelta(minutes=30)) if action == "pause" else None,
                reason="loss_acceleration_pause" if action == "pause" else "loss_acceleration_throttle",
            )

    mock_log_event = Mock()
    monkeypatch.setattr(exec_engine, "LossAccelerationGuard", _FakeGuard)
    monkeypatch.setattr(exec_engine, "log_event", mock_log_event)

    rm = exec_engine.RiskManager()
    intent = exec_engine.OrderIntent(
        strategy_id="s1",
        broker_account_id="paper-1",
        symbol="SPY",
        side="buy",
        qty=1,
        metadata={"uid": "u1", "correlation_id": "corr-123", "execution_id": "exec-999"},
    )

    decision = rm.validate(intent=intent)
    assert decision.allowed is False
    assert decision.reason in {"loss_acceleration_pause", "loss_acceleration_throttle"}

    assert mock_log_event.call_count == 1
    args, kwargs = mock_log_event.call_args
    assert args[1] == "risk.drawdown_velocity_halt"
    assert kwargs["severity"] == severity
    assert kwargs["action"] == action
    assert kwargs["hwm_equity"] == pytest.approx(10000.0)
    assert kwargs["drawdown_velocity_pct_per_min"] == pytest.approx(0.30)

