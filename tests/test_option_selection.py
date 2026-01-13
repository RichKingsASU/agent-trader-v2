import unittest
from datetime import date

from backend.options.selection import (
    NoEligibleOptionsError,
    OptionCandidate,
    OptionSelectionConfig,
    select_option_contract,
)


class TestOptionSelection(unittest.TestCase):
    def test_selects_nearest_expiration_then_closest_atm_strike(self) -> None:
        underlying = "SPY"
        underlying_price = 480.25

        chain = [
            # Nearest expiration
            OptionCandidate(underlying, date(2026, 1, 16), "CALL", 480.0, 0.52, "SPY260116C00480000"),
            OptionCandidate(underlying, date(2026, 1, 16), "CALL", 481.0, 0.49, "SPY260116C00481000"),
            OptionCandidate(underlying, date(2026, 1, 16), "CALL", 479.0, 0.51, "SPY260116C00479000"),
            # Next expiration
            OptionCandidate(underlying, date(2026, 1, 23), "CALL", 480.0, 0.50, "SPY260123C00480000"),
        ]

        cfg = OptionSelectionConfig(delta_min=0.30, delta_max=0.60, right="CALL")
        chosen = select_option_contract(chain, underlying_price=underlying_price, cfg=cfg)

        self.assertEqual(chosen.contract_symbol, "SPY260116C00480000")

    def test_expiration_rank_skips_to_next_available_expiration(self) -> None:
        underlying = "SPY"
        underlying_price = 480.0

        chain = [
            # Nearest expiry has only out-of-band delta
            OptionCandidate(underlying, date(2026, 1, 16), "CALL", 480.0, 0.75, "SPY260116C00480000"),
            # Next expiry has eligible delta
            OptionCandidate(underlying, date(2026, 1, 23), "CALL", 480.0, 0.50, "SPY260123C00480000"),
        ]

        cfg = OptionSelectionConfig(expiration_rank=0, delta_min=0.30, delta_max=0.60, right="CALL")
        chosen = select_option_contract(chain, underlying_price=underlying_price, cfg=cfg)

        self.assertEqual(chosen.contract_symbol, "SPY260123C00480000")

    def test_raises_when_no_eligible_candidates(self) -> None:
        underlying = "SPY"
        chain = [
            OptionCandidate(underlying, date(2026, 1, 16), "CALL", 480.0, 0.90, "SPY260116C00480000"),
        ]

        cfg = OptionSelectionConfig(delta_min=0.30, delta_max=0.60, right="CALL")
        with self.assertRaises(NoEligibleOptionsError):
            select_option_contract(chain, underlying_price=480.0, cfg=cfg)


if __name__ == "__main__":
    unittest.main()

