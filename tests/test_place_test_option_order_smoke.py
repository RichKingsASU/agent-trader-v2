import unittest
import os
import sys
from unittest.mock import patch, MagicMock
from pathlib import Path

# Add the project root to the Python path to allow imports from scripts and backend
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

# Import the script to be tested
from scripts.place_test_option_order import main as main_option_order

class TestPlaceTestOptionOrderSmoke(unittest.TestCase):

    @patch('scripts.place_test_option_order.exec_guard.enforce_execution_policy')
    @patch('scripts.place_test_option_order.require_live_mode')
    @patch('scripts.place_test_option_order.validate_and_correct_alpaca_base_url')
    @patch('scripts.place_test_option_order.require_execution_enabled')
    @patch('scripts.place_test_option_order.TradingClient')
    @patch('scripts.place_test_option_order.MarketOrderRequest')
    @patch('scripts.place_test_option_order.options_guard.get_nearest_expiration')
    @patch('scripts.place_test_option_order.options_guard.get_atm_strike')
    @patch('scripts.place_test_option_order.OptionSymbol')
    @patch('scripts.place_test_option_order.logging')
    def test_refuses_without_execution_enabled(
        self, mock_logging, mock_option_symbol, mock_get_atm_strike,
        mock_get_nearest_expiration, mock_market_order_request, mock_trading_client,
        mock_require_execution_enabled, mock_validate_url, mock_require_live_mode,
        mock_exec_guard
    ):
        # Mock os.environ to control environment variables
        with patch.dict(os.environ, {
            'TRADING_MODE': 'paper',
            'EXECUTION_HALTED': '0',
            'EXECUTION_ENABLED': '0', # Intentionally disable execution
            'EXEC_GUARD_UNLOCK': '1', # Assume guard is unlocked
            'APCA_API_KEY_ID': 'fake_key',
            'APCA_API_SECRET_KEY': 'fake_secret',
            'APCA_API_BASE_URL': 'https://paper-api.alpaca.markets'
        }, clear=True):
            # Mock the specific behavior of require_execution_enabled to raise SystemExit
            mock_require_execution_enabled.side_effect = SystemExit("ERROR: Execution not enabled.")

            with self.assertRaises(SystemExit) as cm:
                main_option_order()

            self.assertEqual(str(cm.exception), "ERROR: Execution not enabled.")
            mock_require_execution_enabled.assert_called_once()
            mock_trading_client.assert_not_called() # Ensure no client is created

    @patch('scripts.place_test_option_order.exec_guard.enforce_execution_policy')
    @patch('scripts.place_test_option_order.require_live_mode')
    @patch('scripts.place_test_option_order.validate_and_correct_alpaca_base_url')
    @patch('scripts.place_test_option_order.require_execution_enabled')
    @patch('scripts.place_test_option_order.TradingClient')
    @patch('scripts.place_test_option_order.MarketOrderRequest')
    @patch('scripts.place_test_option_order.options_guard.get_nearest_expiration')
    @patch('scripts.place_test_option_order.options_guard.get_atm_strike')
    @patch('scripts.place_test_option_order.OptionSymbol')
    @patch('scripts.place_test_option_order.logging')
    def test_refuses_without_exec_guard_unlock(
        self, mock_logging, mock_option_symbol, mock_get_atm_strike,
        mock_get_nearest_expiration, mock_market_order_request, mock_trading_client,
        mock_require_execution_enabled, mock_validate_url, mock_require_live_mode,
        mock_exec_guard
    ):
        # Mock os.environ to control environment variables
        with patch.dict(os.environ, {
            'TRADING_MODE': 'paper',
            'EXECUTION_HALTED': '0',
            'EXECUTION_ENABLED': '1',
            'EXEC_GUARD_UNLOCK': '0', # Intentionally disable guard unlock
            'APCA_API_KEY_ID': 'fake_key',
            'APCA_API_SECRET_KEY': 'fake_secret',
            'APCA_API_BASE_URL': 'https://paper-api.alpaca.markets'
        }, clear=True):
            # exec_guard.enforce_execution_policy itself checks for EXEC_GUARD_UNLOCK
            # when the script's risk policy is MUST_LOCK.
            # We need to mock exec_guard.enforce_execution_policy to simulate the refusal.
            mock_exec_guard.side_effect = SystemExit("ERROR: EXEC_GUARD_UNLOCK must be set.")

            with self.assertRaises(SystemExit) as cm:
                main_option_order()

            self.assertEqual(str(cm.exception), "ERROR: EXEC_GUARD_UNLOCK must be set.")
            mock_exec_guard.assert_called_once()
            mock_trading_client.assert_not_called() # Ensure no client is created

    @patch('scripts.place_test_option_order.exec_guard.enforce_execution_policy')
    @patch('scripts.place_test_option_order.require_live_mode')
    @patch('scripts.place_test_option_order.validate_and_correct_alpaca_base_url')
    @patch('scripts.place_test_option_order.require_execution_enabled')
    @patch('scripts.place_test_option_order.TradingClient')
    @patch('scripts.place_test_option_order.MarketOrderRequest')
    @patch('scripts.place_test_option_order.options_guard.get_nearest_expiration')
    @patch('scripts.place_test_option_order.options_guard.get_atm_strike')
    @patch('scripts.place_test_option_order.OptionSymbol')
    @patch('scripts.place_test_option_order.logging')
    def test_refuses_if_trading_mode_not_paper(
        self, mock_logging, mock_option_symbol, mock_get_atm_strike,
        mock_get_nearest_expiration, mock_market_order_request, mock_trading_client,
        mock_require_execution_enabled, mock_validate_url, mock_require_live_mode,
        mock_exec_guard
    ):
        # Mock os.environ to control environment variables
        with patch.dict(os.environ, {
            'TRADING_MODE': 'live', # Intentionally not 'paper'
            'EXECUTION_HALTED': '0',
            'EXECUTION_ENABLED': '1',
            'EXEC_GUARD_UNLOCK': '1',
            'APCA_API_KEY_ID': 'fake_key',
            'APCA_API_SECRET_KEY': 'fake_secret',
            'APCA_API_BASE_URL': 'https://paper-api.alpaca.markets'
        }, clear=True):
            # require_live_mode should check TRADING_MODE and fail if not 'paper'
            mock_require_live_mode.side_effect = SystemExit("ERROR: TRADING_MODE must be 'paper' for this operation.")

            with self.assertRaises(SystemExit) as cm:
                main_option_order()

            self.assertEqual(str(cm.exception), "ERROR: TRADING_MODE must be 'paper' for this operation.")
            mock_require_live_mode.assert_called_once()
            mock_trading_client.assert_not_called() # Ensure no client is created

    @patch('scripts.place_test_option_order.exec_guard.enforce_execution_policy')
    @patch('scripts.place_test_option_order.require_live_mode')
    @patch('scripts.place_test_option_order.validate_and_correct_alpaca_base_url')
    @patch('scripts.place_test_option_order.require_execution_enabled')
    @patch('scripts.place_test_option_order.TradingClient')
    @patch('scripts.place_test_option_order.MarketOrderRequest')
    @patch('scripts.place_test_option_order.options_guard.get_nearest_expiration')
    @patch('scripts.place_test_option_order.options_guard.get_atm_strike')
    @patch('scripts.place_test_option_order.OptionSymbol')
    @patch('scripts.place_test_option_order.logging')
    def test_does_not_attempt_live_url(
        self, mock_logging, mock_option_symbol, mock_get_atm_strike,
        mock_get_nearest_expiration, mock_market_order_request, mock_trading_client,
        mock_require_execution_enabled, mock_validate_url, mock_require_live_mode,
        mock_exec_guard
    ):
        # Mock os.environ to control environment variables
        with patch.dict(os.environ, {
            'TRADING_MODE': 'paper',
            'EXECUTION_HALTED': '0',
            'EXECUTION_ENABLED': '1',
            'EXEC_GUARD_UNLOCK': '1',
            'APCA_API_KEY_ID': 'fake_key',
            'APCA_API_SECRET_KEY': 'fake_secret',
            'APCA_API_BASE_URL': 'https://paper-api.alpaca.markets/v2' # Include /v2 to test correction
        }, clear=True):
            # Mock helper functions to return valid dummy data
            mock_get_nearest_expiration.return_value = date.today() + timedelta(days=10)
            mock_get_atm_strike.return_value = 100.0
            mock_option_symbol.return_value.symbol = "SPY20241220C100" # Dummy symbol
            mock_market_order_request.return_value = MagicMock()
            mock_trading_client.return_value = MagicMock()
            mock_trading_client.return_value.submit_order.return_value = MagicMock(
                id="dummy_order_id", symbol="SPY20241220C100", qty=1, status="accepted"
            )

            main_option_order()

            # Verify that validate_and_correct_alpaca_base_url was called and enforced paper URL
            mock_validate_url.assert_called_once()
            # Check the TradingClient was initialized with paper=True
            mock_trading_client.assert_called_once_with('fake_key', 'fake_secret', paper=True)
            
            # The key check here is that validate_and_correct_alpaca_base_url is called early
            # and it enforces the paper URL. The TradingClient initialization with paper=True
            # is another layer of safety.
            # We can also assert that the validated URL in os.environ is correct if needed,
            # but the direct call to validate_and_correct_alpaca_base_url and paper=True is strong evidence.

    # More tests can be added here for successful order submission (mocked) etc.

if __name__ == '__main__':
    unittest.main()
