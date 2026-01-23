from __future__ import annotations

from datetime import date

from backend.options.adapter import translate_equity_hedge_to_option_intent
from backend.options.option_intent import OptionType, Side


def test_positive_delta_hedge_defaults_to_sell_calls() -> None:
    # Gamma scalper: positive net delta -> sells shares to hedge (side="sell", qty is absolute).
    equity_intent = {
        "protocol": "v1",
        "type": "order_intent",
        "symbol": "SPY",
        "side": "sell",
        "qty": 250.0,  # 250 shares -> 2 contracts (floor)
        "client_tag": "0dte_gamma_scalper_hedge",
        "metadata": {"reason": "delta_hedge"},
    }
    snap = {"expiry": date(2026, 1, 22), "atm_strike": 480.0}

    opt = translate_equity_hedge_to_option_intent(equity_intent, snap)
    assert opt is not None
    assert opt.underlying == "SPY"
    assert opt.option_type == OptionType.CALL
    assert opt.side == Side.SELL
    assert opt.contracts == 2
    assert opt.expiry == date(2026, 1, 22)
    assert opt.strike == 480.0


def test_positive_delta_hedge_can_be_configured_to_buy_puts() -> None:
    equity_intent = {"symbol": "SPY", "side": "sell", "qty": 100.0, "metadata": {"reason": "delta_hedge"}}
    snap = {
        "expiry": "2026-01-22",
        "strike": 481.0,
        "delta_hedge_policy": {"positive_delta": "buy_puts", "negative_delta": "buy_calls"},
    }

    opt = translate_equity_hedge_to_option_intent(equity_intent, snap)
    assert opt is not None
    assert opt.option_type == OptionType.PUT
    assert opt.side == Side.BUY
    assert opt.contracts == 1


def test_negative_delta_hedge_defaults_to_sell_puts() -> None:
    # Negative net delta -> buys shares to hedge (side="buy").
    equity_intent = {"symbol": "SPY", "side": "buy", "qty": 199.0, "metadata": {"reason": "delta_hedge"}}
    snap = {"expiry": "2026-01-22", "strike": 482.0}

    opt = translate_equity_hedge_to_option_intent(equity_intent, snap)
    assert opt is not None
    assert opt.option_type == OptionType.PUT
    assert opt.side == Side.SELL
    assert opt.contracts == 1  # floor(199/100)=1


def test_contracts_round_down_and_return_none_if_lt_1() -> None:
    snap = {"expiry": "2026-01-22", "strike": 480.0}

    # 99 shares -> 0 contracts -> None
    opt0 = translate_equity_hedge_to_option_intent({"symbol": "SPY", "side": "sell", "qty": 99}, snap)
    assert opt0 is None

    # 100 shares -> 1 contract
    opt1 = translate_equity_hedge_to_option_intent({"symbol": "SPY", "side": "sell", "qty": 100}, snap)
    assert opt1 is not None
    assert opt1.contracts == 1


def test_fail_closed_never_raises_on_bad_inputs() -> None:
    # Missing strike/expiry -> None (HOLD semantics)
    assert translate_equity_hedge_to_option_intent({"symbol": "SPY", "side": "sell", "qty": 100}, {}) is None

    # Invalid side -> None
    assert translate_equity_hedge_to_option_intent({"symbol": "SPY", "side": "hold", "qty": 100}, {"expiry": "2026-01-22", "strike": 480}) is None

    # Non-numeric qty -> None
    assert translate_equity_hedge_to_option_intent({"symbol": "SPY", "side": "sell", "qty": "NaN"}, {"expiry": "2026-01-22", "strike": 480}) is None

