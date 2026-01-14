from backend.execution.order_lifecycle import (
    CanonicalOrderState,
    canonicalize_broker_status,
    compute_delta_fill_qty,
    is_valid_transition,
)


def test_canonicalize_basic_statuses():
    assert canonicalize_broker_status("new", filled_qty=0) == CanonicalOrderState.NEW
    assert canonicalize_broker_status("accepted", filled_qty=0) == CanonicalOrderState.ACCEPTED
    assert canonicalize_broker_status("partially_filled", filled_qty=1) == CanonicalOrderState.PARTIALLY_FILLED
    assert canonicalize_broker_status("filled", filled_qty=1) == CanonicalOrderState.FILLED
    assert canonicalize_broker_status("canceled", filled_qty=0) == CanonicalOrderState.CANCELLED
    assert canonicalize_broker_status("expired", filled_qty=0) == CanonicalOrderState.EXPIRED


def test_canonicalize_unknown_status_with_fills_becomes_partial():
    assert canonicalize_broker_status("pending_cancel", filled_qty=0) == CanonicalOrderState.ACCEPTED
    assert canonicalize_broker_status("unknown_weird", filled_qty=2) == CanonicalOrderState.PARTIALLY_FILLED


def test_transition_validation_expected_path():
    assert is_valid_transition(None, CanonicalOrderState.NEW)
    assert is_valid_transition(CanonicalOrderState.NEW, CanonicalOrderState.ACCEPTED)
    assert is_valid_transition(CanonicalOrderState.ACCEPTED, CanonicalOrderState.FILLED)
    assert is_valid_transition(CanonicalOrderState.ACCEPTED, CanonicalOrderState.CANCELLED)
    assert is_valid_transition(CanonicalOrderState.ACCEPTED, CanonicalOrderState.EXPIRED)


def test_transition_validation_terminal_is_sticky():
    assert is_valid_transition(CanonicalOrderState.FILLED, CanonicalOrderState.FILLED)
    assert not is_valid_transition(CanonicalOrderState.FILLED, CanonicalOrderState.ACCEPTED)


def test_compute_delta_fill_qty():
    assert compute_delta_fill_qty(previous_cum_qty=0, new_cum_qty=0) == 0.0
    assert compute_delta_fill_qty(previous_cum_qty=0, new_cum_qty=1) == 1.0
    assert compute_delta_fill_qty(previous_cum_qty=1, new_cum_qty=1) == 0.0
    assert compute_delta_fill_qty(previous_cum_qty=1, new_cum_qty=1.5) == 0.5

