import pytest

from backend.strategy_runner.protocol import PROTOCOL_VERSION, ProtocolError, parse_order_intent


def test_parse_order_intent_valid():
    msg = {
        "protocol": PROTOCOL_VERSION,
        "type": "order_intent",
        "intent_id": "intent_1",
        "event_id": "evt_1",
        "ts": "2025-01-01T00:00:00Z",
        "symbol": "SPY",
        "side": "buy",
        "qty": 1,
        "order_type": "market",
    }
    intent = parse_order_intent(msg)
    assert intent.intent_id == "intent_1"
    assert intent.symbol == "SPY"
    assert intent.qty == 1.0


@pytest.mark.parametrize(
    "bad",
    [
        {},  # missing all
        {"protocol": PROTOCOL_VERSION, "type": "order_intent"},  # missing required
        {
            "protocol": "v0",
            "type": "order_intent",
            "intent_id": "intent_1",
            "event_id": "evt_1",
            "ts": "x",
            "symbol": "SPY",
            "side": "buy",
            "qty": 1,
            "order_type": "market",
        },  # bad protocol
        {
            "protocol": PROTOCOL_VERSION,
            "type": "order_intent",
            "intent_id": "intent_1",
            "event_id": "evt_1",
            "ts": "x",
            "symbol": "SPY",
            "side": "hold",
            "qty": 1,
            "order_type": "market",
        },  # bad side
        {
            "protocol": PROTOCOL_VERSION,
            "type": "order_intent",
            "intent_id": "intent_1",
            "event_id": "evt_1",
            "ts": "x",
            "symbol": "SPY",
            "side": "buy",
            "qty": 0,
            "order_type": "market",
        },  # qty <= 0
    ],
)
def test_parse_order_intent_invalid(bad):
    with pytest.raises(ProtocolError):
        parse_order_intent(bad)

