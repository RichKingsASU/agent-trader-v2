from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from backend.options.selector import (
    ContractSelectionError,
    MarketSnapshot,
    OptionSelectorConfig,
    SyntheticOptionQuote,
    resolve_option_contract,
)


def _dt_utc(y: int, m: int, d: int, hh: int, mm: int = 0, ss: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, ss, tzinfo=timezone.utc)


def test_before_230pm_et_prefers_0dte_and_nearest_otm_call_strike():
    # 2026-01-23 14:00 ET == 19:00 UTC (EST)
    now_utc = _dt_utc(2026, 1, 23, 19, 0, 0)
    today = date(2026, 1, 23)

    snap = MarketSnapshot(
        now_utc=now_utc,
        underlying_symbol="SPY",
        spot=479.90,
        chain=[
            SyntheticOptionQuote(expiry=today, strike=479.0, option_type="call", bid=2.10, ask=2.20),
            SyntheticOptionQuote(expiry=today, strike=480.0, option_type="call", bid=1.90, ask=2.00, theoretical_delta=0.51),
            # include future expiry too; before 2:30 ET we should still take 0DTE
            SyntheticOptionQuote(expiry=date(2026, 1, 26), strike=480.0, option_type="call", bid=3.00, ask=3.05),
        ],
    )

    intent = {"symbol": "SPY", "right": "call"}
    cfg = OptionSelectorConfig(max_bid_ask_spread=0.25)

    resolved = resolve_option_contract(intent, snap, config=cfg)
    assert resolved.symbol == "SPY_012326C480"
    assert resolved.expiry == today
    assert resolved.strike == 480.0
    assert resolved.option_type == "call"
    assert resolved.theoretical_delta == pytest.approx(0.51)
    assert resolved.multiplier == 100


def test_after_230pm_et_prefers_next_expiry_over_0dte_when_available():
    # 2026-01-23 15:00 ET == 20:00 UTC (EST)
    now_utc = _dt_utc(2026, 1, 23, 20, 0, 0)
    today = date(2026, 1, 23)
    next_exp = date(2026, 1, 26)

    snap = MarketSnapshot(
        now_utc=now_utc,
        underlying_symbol="SPY",
        spot=479.90,
        chain=[
            SyntheticOptionQuote(expiry=today, strike=480.0, option_type="call", bid=1.90, ask=2.00),
            SyntheticOptionQuote(expiry=next_exp, strike=480.0, option_type="call", bid=3.00, ask=3.05),
        ],
    )
    intent = {"symbol": "SPY", "right": "call"}
    cfg = OptionSelectorConfig(max_bid_ask_spread=0.25)

    resolved = resolve_option_contract(intent, snap, config=cfg)
    assert resolved.expiry == next_exp
    assert resolved.symbol == "SPY_012626C480"


def test_after_330pm_et_no_new_positions_time_guard():
    # 2026-01-23 15:31 ET == 20:31 UTC (EST)
    now_utc = _dt_utc(2026, 1, 23, 20, 31, 0)
    snap = MarketSnapshot(
        now_utc=now_utc,
        underlying_symbol="SPY",
        spot=480.0,
        chain=[SyntheticOptionQuote(expiry=date(2026, 1, 23), strike=481.0, option_type="call", bid=1.0, ask=1.1)],
    )

    with pytest.raises(ContractSelectionError) as e:
        resolve_option_contract({"symbol": "SPY", "right": "call"}, snap, config=OptionSelectorConfig())
    assert e.value.reason == "TIME_GUARD_NO_NEW_POSITIONS"


def test_liquidity_guard_rejects_nearest_otm_even_if_next_strike_is_liquid():
    # 2026-01-23 14:00 ET == 19:00 UTC (EST)
    now_utc = _dt_utc(2026, 1, 23, 19, 0, 0)
    today = date(2026, 1, 23)

    snap = MarketSnapshot(
        now_utc=now_utc,
        underlying_symbol="SPY",
        spot=479.90,
        chain=[
            # Nearest OTM is 480, but it's too wide -> must fail (not "skip to 481")
            SyntheticOptionQuote(expiry=today, strike=480.0, option_type="call", bid=1.00, ask=1.50),
            SyntheticOptionQuote(expiry=today, strike=481.0, option_type="call", bid=0.90, ask=0.95),
        ],
    )

    with pytest.raises(ContractSelectionError) as e:
        resolve_option_contract({"symbol": "SPY", "right": "call"}, snap, config=OptionSelectorConfig(max_bid_ask_spread=0.20))
    assert e.value.reason == "LIQUIDITY_GUARD"


def test_no_otm_call_strike_raises_fail_closed():
    now_utc = _dt_utc(2026, 1, 23, 19, 0, 0)
    today = date(2026, 1, 23)
    snap = MarketSnapshot(
        now_utc=now_utc,
        underlying_symbol="SPY",
        spot=500.00,
        chain=[
            SyntheticOptionQuote(expiry=today, strike=499.0, option_type="call", bid=1.0, ask=1.1),
            SyntheticOptionQuote(expiry=today, strike=500.0, option_type="call", bid=0.9, ask=1.0),
        ],
    )

    with pytest.raises(ContractSelectionError) as e:
        resolve_option_contract({"symbol": "SPY", "right": "call"}, snap, config=OptionSelectorConfig(max_bid_ask_spread=0.25))
    assert e.value.reason == "NO_OTM_STRIKE"


def test_put_selects_nearest_otm_below_spot():
    now_utc = _dt_utc(2026, 1, 23, 19, 0, 0)
    today = date(2026, 1, 23)
    snap = MarketSnapshot(
        now_utc=now_utc,
        underlying_symbol="SPY",
        spot=480.10,
        chain=[
            SyntheticOptionQuote(expiry=today, strike=480.0, option_type="put", bid=1.0, ask=1.1),
            SyntheticOptionQuote(expiry=today, strike=479.0, option_type="put", bid=1.2, ask=1.25, theoretical_delta=-0.48),
        ],
    )

    resolved = resolve_option_contract({"symbol": "SPY", "right": "put"}, snap, config=OptionSelectorConfig(max_bid_ask_spread=0.25))
    assert resolved.expiry == today
    assert resolved.strike == 480.0 - 0.0  # nearest below 480.10 is 480.0
    assert resolved.symbol == "SPY_012326P480"

