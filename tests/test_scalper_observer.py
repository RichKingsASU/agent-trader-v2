from __future__ import annotations

from backend.observer.scalper_observer import (
    _detect_threshold_not_crossed,
    _extract_gex,
    _extract_macro_flag,
    _extract_net_delta,
    _extract_threshold,
    _infer_safety_gates,
)


def test_extracts_net_delta_from_metadata() -> None:
    payload = {"metadata": {"net_delta_before": "12.5"}}
    assert _extract_net_delta(payload) == 12.5


def test_extracts_threshold_from_metadata() -> None:
    payload = {"metadata": {"hedging_threshold": "0.15"}}
    assert _extract_threshold(payload) == 0.15


def test_extracts_gex_and_macro_flag() -> None:
    payload = {"metadata": {"gex_value": "-15000.0", "macro_event_active": "true"}}
    assert _extract_gex(payload) == -15000.0
    assert _extract_macro_flag(payload) is True


def test_threshold_not_crossed_detection() -> None:
    assert _detect_threshold_not_crossed(net_delta=0.10, threshold=0.15) is True
    assert _detect_threshold_not_crossed(net_delta=0.16, threshold=0.15) is False


def test_infer_safety_gates_dedupes_and_sorts() -> None:
    payload = {"error": "kill_switch_enabled"}
    attempt = {"mode": "shadow", "message": "kill_switch_enabled"}
    completed = None

    gates = _infer_safety_gates(
        payload=payload,
        attempt=attempt,
        completed=completed,
        risk_allowed=False,
        threshold_not_crossed=True,
        rate_limited=True,
    )

    # Sorted and unique
    assert gates == [
        "KILL_SWITCH_ACTIVE",
        "RATE_LIMIT_HIT",
        "RISK_DENIED",
        "SHADOW_MODE",
        "THRESHOLD_NOT_CROSSED",
    ]

