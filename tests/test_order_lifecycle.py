from backend.execution.order_lifecycle import (
    InMemoryOrderLifecycle,
    OrderLifecycleState,
    OrderLifecycleTransitionError,
    broker_status_to_lifecycle_state,
)


def test_broker_status_mapping_basic():
    assert broker_status_to_lifecycle_state("new") == OrderLifecycleState.NEW
    assert broker_status_to_lifecycle_state("accepted") == OrderLifecycleState.ACCEPTED
    assert broker_status_to_lifecycle_state("partially_filled") == OrderLifecycleState.ACCEPTED
    assert broker_status_to_lifecycle_state("filled") == OrderLifecycleState.FILLED
    assert broker_status_to_lifecycle_state("canceled") == OrderLifecycleState.CANCELLED
    assert broker_status_to_lifecycle_state("expired") == OrderLifecycleState.EXPIRED


def test_lifecycle_new_to_accepted_to_filled():
    sm = InMemoryOrderLifecycle()
    oid = "order_1"
    t1 = sm.observe(broker_order_id=oid, broker_status="new")
    t2 = sm.observe(broker_order_id=oid, broker_status="accepted")
    t3 = sm.observe(broker_order_id=oid, broker_status="filled")
    assert [t.to_state for t in (t1 + t2 + t3)] == [
        OrderLifecycleState.NEW,
        OrderLifecycleState.ACCEPTED,
        OrderLifecycleState.FILLED,
    ]
    assert sm.state(broker_order_id=oid) == OrderLifecycleState.FILLED


def test_lifecycle_inserts_synthetic_accepted_when_broker_skips():
    sm = InMemoryOrderLifecycle()
    oid = "order_2"
    sm.observe(broker_order_id=oid, broker_status="new")
    transitions = sm.observe(broker_order_id=oid, broker_status="filled")
    assert len(transitions) == 2
    assert transitions[0].to_state == OrderLifecycleState.ACCEPTED
    assert transitions[0].synthetic is True
    assert transitions[1].to_state == OrderLifecycleState.FILLED
    assert transitions[1].synthetic is False


def test_lifecycle_rejects_backward_transition():
    sm = InMemoryOrderLifecycle()
    oid = "order_3"
    sm.observe(broker_order_id=oid, broker_status="new")
    sm.observe(broker_order_id=oid, broker_status="filled")
    try:
        sm.observe(broker_order_id=oid, broker_status="accepted")
        assert False, "expected OrderLifecycleTransitionError"
    except OrderLifecycleTransitionError:
        pass

