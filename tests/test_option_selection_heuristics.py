import datetime as dt
import random

from backend.options.selection import SelectionRules, select_option_contract, select_option_symbol


def _c(symbol: str, expiry: str, right: str, strike: float, delta: float | None) -> dict:
    out = {
        "symbol": symbol,
        "expiration_date": expiry,  # YYYY-MM-DD
        "type": right,
        "strike_price": strike,
    }
    if delta is not None:
        out["greeks"] = {"delta": delta}
    return out


def test_selects_nearest_expiration_then_atm_within_delta_band():
    # As-of fixed to ensure determinism across runs.
    as_of = dt.date(2026, 1, 14)
    underlying = 476.20

    contracts = [
        # Further expiry (should be ignored by nearest-expiration rule)
        _c("SPY260124C00475000", "2026-01-24", "call", 475.0, 0.53),
        _c("SPY260124C00480000", "2026-01-24", "call", 480.0, 0.41),
        # Nearest expiry (selected expiry)
        _c("SPY260116C00475000", "2026-01-16", "call", 475.0, 0.52),
        _c("SPY260116C00480000", "2026-01-16", "call", 480.0, 0.40),
        # Outside delta band (should be filtered out)
        _c("SPY260116C00470000", "2026-01-16", "call", 470.0, 0.75),
        # Wrong right
        _c("SPY260116P00475000", "2026-01-16", "put", 475.0, -0.48),
    ]

    sym, dbg = select_option_symbol(
        contracts,
        underlying_price=underlying,
        right="call",
        as_of=as_of,
        rules=SelectionRules(delta_band=(0.30, 0.60)),
    )

    assert dbg["reason"] == "ok"
    assert dbg["selected_expiration"] == "2026-01-16"
    # ATM between 475 and 480 is 475 for 476.20
    assert sym == "SPY260116C00475000"


def test_target_dte_is_configurable_and_deterministic():
    as_of = dt.date(2026, 1, 14)
    underlying = 476.20

    contracts = [
        # 3 DTE
        _c("SPY260117C00475000", "2026-01-17", "call", 475.0, 0.52),
        # 10 DTE
        _c("SPY260124C00475000", "2026-01-24", "call", 475.0, 0.53),
        # same strikes but slightly worse ATM (to avoid ambiguity)
        _c("SPY260117C00480000", "2026-01-17", "call", 480.0, 0.40),
        _c("SPY260124C00480000", "2026-01-24", "call", 480.0, 0.41),
    ]

    # Target ~7DTE => picks 10DTE (|10-7|=3 vs |3-7|=4)
    c, dbg = select_option_contract(
        contracts,
        underlying_price=underlying,
        right="call",
        as_of=as_of,
        rules=SelectionRules(target_dte=7, dte_max=14, delta_band=(0.30, 0.60)),
    )

    assert dbg["reason"] == "ok"
    assert dbg["selected_expiration"] == "2026-01-24"
    assert c is not None
    assert c.symbol == "SPY260124C00475000"


def test_reproducible_with_shuffled_inputs():
    as_of = dt.date(2026, 1, 14)
    underlying = 476.20
    rules = SelectionRules(target_dte=None, dte_max=30, delta_band=(0.30, 0.60))

    base = [
        _c("SPY260116C00475000", "2026-01-16", "call", 475.0, 0.52),
        _c("SPY260116C00480000", "2026-01-16", "call", 480.0, 0.40),
        _c("SPY260116C00485000", "2026-01-16", "call", 485.0, 0.33),
        _c("SPY260124C00475000", "2026-01-24", "call", 475.0, 0.53),
    ]

    expected, _dbg0 = select_option_symbol(base, underlying_price=underlying, right="call", as_of=as_of, rules=rules)
    assert expected == "SPY260116C00475000"

    for seed in range(10):
        xs = list(base)
        random.Random(seed).shuffle(xs)
        got, dbg = select_option_symbol(xs, underlying_price=underlying, right="call", as_of=as_of, rules=rules)
        assert dbg["reason"] == "ok"
        assert got == expected

