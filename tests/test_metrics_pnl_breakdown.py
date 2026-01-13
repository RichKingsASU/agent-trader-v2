import os
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path


def _import_metrics_calculator():
    import sys

    functions_dir = Path(__file__).resolve().parent.parent / "functions"
    sys.path.insert(0, str(functions_dir))
    from strategies.metrics_calculator import MetricsCalculator  # type: ignore

    return MetricsCalculator


def test_metrics_include_realized_and_unrealized_pnl_fields():
    MetricsCalculator = _import_metrics_calculator()
    calc = MetricsCalculator()

    t0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
    equity_curve = [
        (t0, Decimal("100000")),
        (t0 + timedelta(days=1), Decimal("100500")),
    ]

    # Backtester trade dict convention:
    # - BUY total_cost positive (cash out)
    # - SELL total_cost negative (cash in recorded as negative)
    trades = [
        {"symbol": "SPY", "action": "BUY", "total_cost": 1000.0},
        {"symbol": "SPY", "action": "SELL", "total_cost": -1100.0},
    ]

    metrics = calc.calculate_all_metrics(
        equity_curve=equity_curve,
        trades=trades,
        start_capital=Decimal("100000"),
        unrealized_pnl_dollars=25.0,
    )

    assert "realized_pnl_dollars" in metrics
    assert "unrealized_pnl_dollars" in metrics
    assert metrics["realized_pnl_dollars"] == 100.0
    assert metrics["unrealized_pnl_dollars"] == 25.0

