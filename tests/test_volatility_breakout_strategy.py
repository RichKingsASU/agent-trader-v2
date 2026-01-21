import os
from datetime import datetime, timedelta, timezone

import pytest

import sys
import os as _os

sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), "..", "functions"))

from strategies.volatility_breakout import VolatilityBreakout
from strategies.base_strategy import TradingSignal, SignalType


def _bars_from_closes(closes):
    # Minimal OHLC bars: fixed range around close.
    out = []
    base = datetime(2025, 1, 2, 14, 0, tzinfo=timezone.utc)
    for i, c in enumerate(closes):
        out.append(
            {
                "t": (base + timedelta(minutes=i)).isoformat(),
                "open": float(c),
                "high": float(c) + 0.5,
                "low": float(c) - 0.5,
                "close": float(c),
                "volume": 1000,
            }
        )
    return out


@pytest.fixture(autouse=True)
def _paper_guard_env(monkeypatch):
    # Ensure execution guard passes in tests.
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("EXECUTION_HALTED", "")
    monkeypatch.setenv("ENABLE_DANGEROUS_FUNCTIONS", "true")
    monkeypatch.setenv("EXEC_GUARD_UNLOCK", "1")


def test_returns_trading_signal_only():
    strat = VolatilityBreakout(config={"lookback": 5})
    sig = strat.evaluate({"symbol": "SPY", "bars": []}, {"buying_power": "10000", "positions": []})
    assert isinstance(sig, TradingSignal)


def test_hold_when_insufficient_history():
    strat = VolatilityBreakout(config={"lookback": 10})
    md = {"symbol": "SPY", "timestamp": datetime.now(timezone.utc).isoformat(), "bars": _bars_from_closes([100, 101, 102])}
    sig = strat.evaluate(md, {"buying_power": "10000", "positions": []})
    assert sig.signal_type == SignalType.HOLD


def test_long_breakout_buy_signal():
    # Build a channel then jump above prior highs.
    closes = [100, 100.1, 99.9, 100.2, 100.0, 100.1, 102.0]
    bars = _bars_from_closes(closes)
    md = {"symbol": "SPY", "timestamp": bars[-1]["t"], "bars": bars, "iv": 0.25}
    strat = VolatilityBreakout(config={"lookback": 5, "atr_period": 3, "base_allocation_pct": 0.2, "max_notional_per_signal_usd": 1000.0})
    sig = strat.evaluate(md, {"buying_power": "10000", "positions": []})
    assert sig.signal_type == SignalType.BUY
    assert sig.metadata.get("atr") is not None
    assert sig.metadata.get("implied_vol") == 0.25
    assert sig.metadata.get("allocation_usd") <= 1000.0


def test_time_based_exit_sells_before_close_window():
    # Time-based exit default is 15:50 NY; set timestamp at 15:51 NY.
    # 15:51 NY in winter is 20:51 UTC.
    ts = datetime(2025, 1, 2, 20, 51, tzinfo=timezone.utc).isoformat()
    closes = [100, 100.1, 100.0, 100.2, 100.1, 100.3, 100.2]
    bars = _bars_from_closes(closes)
    bars[-1]["t"] = ts
    md = {"symbol": "SPY", "timestamp": ts, "bars": bars}

    strat = VolatilityBreakout(config={"lookback": 5, "time_exit_ny": "15:50", "close_window_start_ny": "15:55"})
    acct = {
        "buying_power": "10000",
        "positions": [
            {"symbol": "SPY", "qty": 10, "entry_price": 100.0, "entry_time": (datetime(2025, 1, 2, 18, 0, tzinfo=timezone.utc)).isoformat()}
        ],
    }
    sig = strat.evaluate(md, acct)
    assert sig.signal_type == SignalType.SELL
    assert sig.metadata.get("guardrail") == "time_exit"


def test_close_window_forces_hold():
    # 15:57 NY in winter is 20:57 UTC.
    ts = datetime(2025, 1, 2, 20, 57, tzinfo=timezone.utc).isoformat()
    closes = [100, 100.1, 99.9, 100.2, 100.0, 100.1, 105.0]
    bars = _bars_from_closes(closes)
    bars[-1]["t"] = ts
    md = {"symbol": "SPY", "timestamp": ts, "bars": bars}
    strat = VolatilityBreakout(config={"lookback": 5, "close_window_start_ny": "15:55", "close_window_end_ny": "16:00"})
    sig = strat.evaluate(md, {"buying_power": "10000", "positions": []})
    assert sig.signal_type == SignalType.HOLD
    assert sig.metadata.get("guardrail") == "market_close_window_hold"

