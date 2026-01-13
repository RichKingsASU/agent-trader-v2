import sys
from decimal import Decimal


# Allow imports like `functions.strategies.backtester` (namespace package)
sys.path.insert(0, "/workspace")


from functions.strategies.backtester import BacktestConfig, Backtester  # noqa: E402


def _mk_backtester(cfg: BacktestConfig) -> Backtester:
    """
    Create a Backtester instance without running __init__ (no Alpaca deps in unit tests).
    """
    bt = Backtester.__new__(Backtester)
    bt.config = cfg
    return bt


def test_options_fill_worst_side_plus_spread_buy():
    bt = _mk_backtester(
        BacktestConfig(
            fill_model="worst_side_plus_spread",
            spread_penalty_mult=Decimal("0.25"),
        )
    )
    fill, slip = bt._compute_fill_price(
        action="BUY",
        reference_price=Decimal("1.00"),
        asset_class="OPTIONS",
        metadata={"bid": 0.90, "ask": 1.10},
    )
    # spread = 0.20; BUY fill = ask + 0.25*spread = 1.10 + 0.05 = 1.15
    assert fill == Decimal("1.15")
    assert slip == Decimal("0.15")


def test_options_fill_worst_side_plus_spread_sell():
    bt = _mk_backtester(
        BacktestConfig(
            fill_model="worst_side_plus_spread",
            spread_penalty_mult=Decimal("0.25"),
        )
    )
    fill, slip = bt._compute_fill_price(
        action="SELL",
        reference_price=Decimal("1.00"),
        asset_class="OPTIONS",
        metadata={"bid": 0.90, "ask": 1.10},
    )
    # spread = 0.20; SELL fill = bid - 0.25*spread = 0.90 - 0.05 = 0.85
    assert fill == Decimal("0.85")
    assert slip == Decimal("-0.15")


def test_fill_model_bps_back_compat():
    bt = _mk_backtester(BacktestConfig(fill_model="bps", slippage_bps=10))  # 10 bps = 0.10%
    fill, slip = bt._compute_fill_price(
        action="BUY",
        reference_price=Decimal("100.00"),
        asset_class="EQUITY",
        metadata={},
    )
    assert fill == Decimal("100.10")
    assert slip == Decimal("0.10")

