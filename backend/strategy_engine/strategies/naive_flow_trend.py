from typing import List, Dict
from ..models import Bar, FlowEvent

def make_decision(bars: List[Bar], flow_events: List[FlowEvent]) -> Dict:
    """
    Makes a trading decision based on recent bars and options flow.
    """
    if not bars:
        return {
            "action": "flat",
            "reason": "No recent bar data.",
            "signal_payload": {}
        }

    # Calculate simple moving average
    closes = [bar.close for bar in bars]
    sma = sum(closes) / len(closes)
    last_close = closes[0]

    # Calculate flow imbalance
    call_value = sum(event.total_value for event in flow_events if event.total_value > 0)
    put_value = sum(event.total_value for event in flow_events if event.total_value < 0)
    flow_imbalance = call_value + put_value

    # Decision logic
    if last_close > sma and flow_imbalance > 0:
        action = "buy"
        reason = f"Price ({last_close:.2f}) is above SMA ({sma:.2f}) and flow is bullish ({flow_imbalance:.2f})."
    else:
        action = "flat"
        reason = f"Price ({last_close:.2f}) is not decisively above SMA ({sma:.2f}) or flow is not bullish ({flow_imbalance:.2f})."

    return {
        "action": action,
        "size": 1,
        "reason": reason,
        "signal_payload": {
            "sma": sma,
            "last_close": last_close,
            "flow_imbalance": flow_imbalance,
        },
    }