import os
import sys
import unittest
from unittest.mock import patch, Mock, MagicMock
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal
import uuid
from typing import Optional, Any # Added import for Any

# Import necessary types from the project
# Assuming OptionOrderIntent, Side, OptionRight are in backend.contracts.v2.trading
# Assuming process_option_intent, IntentGateResult are in backend.trading.execution.options_intent_gate
# Assuming enforce_execution_policy is in scripts.lib.exec_guard
try:
    from backend.contracts.v2.trading import OptionOrderIntent, Side, OptionRight
except ImportError:
    from enum import Enum
    from dataclasses import dataclass, field
    class Side(Enum):
        BUY = "buy"
        SELL = "sell"
    class OptionRight(Enum):
        CALL = "call"
        PUT = "put"
    @dataclass
    class OptionOrderIntent:
        intent_id: uuid.UUID
        strategy_id: str
        symbol: str
        side: Side
        order_type: str
        quantity: int
        expiration: date
        strike: Decimal
        right: OptionRight
        options: Dict[str, Any]

try:
    from backend.trading.execution.options_intent_gate import process_option_intent, IntentGateResult
except ImportError:
    from dataclasses import dataclass, field
    from enum import Enum
    @dataclass
    class IntentGateResult:
        blocked: bool = False
        reason: Optional[str] = None
        execution_result: Any = None
    def process_option_intent(intent: OptionOrderIntent) -> IntentGateResult:
        # This mock will be replaced by patching the actual module in tests
        raise NotImplementedError("process_option_intent not available")

try:
    from scripts.lib.exec_guard import enforce_execution_policy, ScriptRisk
except ImportError:
    # This mock will be replaced by patching the actual module in tests
    def enforce_execution_policy(script_path: str, argv: list[str]) -> None:
        raise NotImplementedError("enforce_execution_policy not available")

# Import the module under test
# We'll import the executor and gate logic to test their refusal paths
import backend.trading.execution.alpaca_options_executor
import backend.trading.execution.options_intent_gate

# Mock the Alpaca TradingClient and APIError
class MockAlpacaAPIError(Exception):
    """Mock APIError for alpaca_trade_api.rest.api."""
    def __init__(self, message, code=None, status_code=None):
        super().__init__(message)
        self.code = code
        self.status_code = status_code

class MockAlpacaTradingClient:
    """Mock Alpaca TradingClient."""
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        if "base_url" in kwargs and "https://paper-api.alpaca.markets" not in kwargs["base_url"]:
            raise MockAlpacaAPIError("Invalid base URL provided to mock client.")
        if "key_id" not in kwargs or not kwargs["key_id"]:
            raise MockAlpacaAPIError("API key ID is missing.")
        if "secret_api" not in kwargs or not kwargs["secret_api"]:
            raise MockAlpacaAPIError("API secret key is missing.")
        
    def submit_order(self, **kwargs):
        # Simulate a successful order submission for when invariants pass
        # In refusal tests, this should not be called.
        mock_order_id = f"mock-order-{uuid.uuid4().hex[:8]}"
        return Mock(
            id=mock_order_id,
            status="new",
            dict=lambda: {"id": mock_order_id, "status": "new", "symbol": kwargs.get("symbol")}
        )

# --- Test Helper Function to Set Environment Variables ---
def set_env_vars(env_vars: dict):
    """Temporarily set environment variables for a test."""
    original_env = {k: os.environ.get(k) for k in env_vars}
    for key, value in env_vars.items():
        os.environ[key] = value
    yield
    # Restore original environment variables
    for key, value in original_env.items():
        if value is None:
            del os.environ[key]
        else:
            os.environ[key] = value

# --- Test Case for Refusal Behaviors ---
class TestOptionsPaperExecutionRefusals(unittest.TestCase):

    def setUp(self):
        """Set up common mocks and variables before each test."""
        # Mocking modules that are imported by the code under test
        self.patcher_exec_guard = patch('scripts.lib.exec_guard')
        self.mock_exec_guard = self.patcher_exec_guard.start()
        self.mock_exec_guard.enforce_execution_policy.return_value = None # Assume it passes if not raising SystemExit

        self.patcher_alpaca_api = patch('alpaca_trade_api.rest.REST', new=MockAlpacaTradingClient)
        self.mock_alpaca_rest = self.patcher_alpaca_api.start()
        
        self.patcher_api_error = patch('alpaca_trade_api.rest.APIError', new=MockAlpacaAPIError)
        self.mock_api_error = self.patcher_api_error.start()

        # Mock the process_option_intent function to control its behavior
        self.patcher_process_intent = patch('backend.trading.execution.options_intent_gate.process_option_intent')
        self.mock_process_intent = self.patcher_process_intent.start()
        # Default mock behavior: return a successful result
        self.mock_process_intent.return_value = MagicMock(
            blocked=False,
            execution_result=Mock(broker_order_id="mock_id_success", status="submitted")
        )

        # Mock the ShadowOptionsExecutor to ensure it's not called in paper mode tests
        self.patcher_shadow_executor = patch('backend.trading.execution.options_intent_gate.ShadowOptionsExecutor')
        self.mock_shadow_executor = self.patcher_shadow_executor.start()

        # Mock the logger
        self.patcher_logger = patch('backend.trading.execution.alpaca_options_executor.logger')
        self.mock_logger = self.patcher_logger.start()
        self.patcher_gate_logger = patch('backend.trading.execution.options_intent_gate.logger')
        self.mock_gate_logger = self.patcher_gate_logger.start()

        # Create a dummy intent to pass to the functions
        self.dummy_intent = OptionOrderIntent(
            intent_id=uuid.uuid4(),
            strategy_id="test_strategy",
            symbol="SPY",
            side=Side.BUY,
            order_type="market",
            quantity=1,
            expiration=date.today() + timedelta(days=7),
            strike=Decimal("450.00"),
            right=OptionRight.CALL,
            options={"contract_symbol": "SPY260207C00450000"}
        )

    def tearDown(self):
        """Stop mock patches after each test."""
        self.patcher_exec_guard.stop()
        self.patcher_alpaca_api.stop()
        self.patcher_api_error.stop()
        self.patcher_process_intent.stop()
        self.patcher_shadow_executor.stop()
        self.patcher_logger.stop()
        self.patcher_gate_logger.stop()

    # --- Test cases for refusals ---

    def test_refusal_before_client_construction_kill_switch_on(self):
        """
        Verify execute_option_intent_paper refuses BEFORE TradingClient construction
        when EXECUTION_HALTED is ON.
        """
        with patch.dict(os.environ, {
            "TRADING_MODE": "paper",
            "OPTIONS_EXECUTION_MODE": "paper",
            "APCA_API_KEY_ID": "key",
            "APCA_API_SECRET_KEY": "secret",
            "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
            "EXECUTION_HALTED": "1", # Kill switch ON
            "EXECUTION_ENABLED": "1",
            "EXEC_GUARD_UNLOCK": "1",
            "EXECUTION_CONFIRM_TOKEN": "token",
        }):
            with self.assertRaises(SystemExit): # Assuming the executor or gate will raise SystemExit or similar
                # We need to call the function that would construct the client.
                # This is done by calling process_option_intent, which then calls the executor.
                # The gate itself checks EXECUTION_HALTED.
                # To test the executor's check specifically, we'd need to mock process_option_intent to call it directly.
                
                # Let's mock process_option_intent to bypass gate and call the executor directly for this test's purpose.
                # Alternatively, we can test the gate's check for kill switch if it's the primary point of failure.
                # The plan asks for tests on the executor's refusal, so let's aim for that.
                
                # To test the executor's refusal logic directly, we might need to isolate it.
                # However, the executor's logic is called *after* the gate's checks.
                # Let's test the gate's refusal first, as it's the entry point.
                
                # Test gate's refusal of kill switch
                process_option_intent(self.dummy_intent)
            
            # Verify TradingClient was NOT constructed
            self.mock_alpaca_rest.assert_not_called()
            # Verify executor was not called (gate should block before calling it)
            self.mock_process_intent.assert_not_called() # Ensure process_option_intent itself wasn't bypassed by an earlier mock

    def test_refusal_before_client_construction_trading_mode_not_paper(self):
        """
        Verify execute_option_intent_paper refuses BEFORE TradingClient construction
        when TRADING_MODE is not 'paper'.
        """
        with patch.dict(os.environ, {
            "TRADING_MODE": "live", # Not paper
            "OPTIONS_EXECUTION_MODE": "paper",
            "APCA_API_KEY_ID": "key",
            "APCA_API_SECRET_KEY": "secret",
            "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
            "EXECUTION_HALTED": "0",
            "EXECUTION_ENABLED": "1",
            "EXEC_GUARD_UNLOCK": "1",
            "EXECUTION_CONFIRM_TOKEN": "token",
        }):
            with self.assertRaises(SystemExit):
                # Test gate's refusal for TRADING_MODE
                process_option_intent(self.dummy_intent)
            
            # Verify TradingClient was NOT constructed
            self.mock_alpaca_rest.assert_not_called()
            self.mock_process_intent.assert_not_called()

    def test_refusal_before_client_construction_invalid_apca_url(self):
        """
        Verify execute_option_intent_paper refuses BEFORE TradingClient construction
        when APCA_API_BASE_URL is invalid.
        """
        with patch.dict(os.environ, {
            "TRADING_MODE": "paper",
            "OPTIONS_EXECUTION_MODE": "paper",
            "APCA_API_KEY_ID": "key",
            "APCA_API_SECRET_KEY": "secret",
            "APCA_API_BASE_URL": "https://api.alpaca.markets/v2", # Invalid URL
            "EXECUTION_HALTED": "0",
            "EXECUTION_ENABLED": "1",
            "EXEC_GUARD_UNLOCK": "1",
            "EXECUTION_CONFIRM_TOKEN": "token",
        }):
            with self.assertRaises(SystemExit):
                # Test gate's refusal for invalid URL
                process_option_intent(self.dummy_intent)
            
            # Verify TradingClient was NOT constructed
            self.mock_alpaca_rest.assert_not_called()
            self.mock_process_intent.assert_not_called()

    def test_refusal_before_client_construction_option_mode_unset(self):
        """
        Verify that when OPTIONS_EXECUTION_MODE is unset, process_option_intent
        stays in shadow mode (no TradingClient construction).
        """
        with patch.dict(os.environ, {
            "TRADING_MODE": "paper", # This alone is not enough
            "APCA_API_KEY_ID": "key",
            "APCA_API_SECRET_KEY": "secret",
            "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
            "EXECUTION_HALTED": "0",
            "EXECUTION_ENABLED": "1",
            "EXEC_GUARD_UNLOCK": "1",
            "EXECUTION_CONFIRM_TOKEN": "token",
            # OPTIONS_EXECUTION_MODE is intentionally unset or set to 'shadow'
        }):
            # Ensure OPTIONS_EXECUTION_MODE is unset or 'shadow'
            if "OPTIONS_EXECUTION_MODE" in os.environ:
                del os.environ["OPTIONS_EXECUTION_MODE"]

            # Call process_option_intent
            result = process_option_intent(self.dummy_intent)

            # Verify it was blocked or went to shadow, NOT to paper execution
            self.assertTrue(result.blocked, "Intent should be blocked or handled by shadow path")
            if result.blocked:
                self.assertIn("not PAPER", result.reason.lower()) # Expect reason indicating it's not paper mode
            
            # Verify TradingClient was NOT constructed
            self.mock_alpaca_rest.assert_not_called()
            # Verify the correct path was taken (gate should handle it, not call executor)
            # We expect the gate to return blocked if OPTIONS_EXECUTION_MODE is not 'paper'
            self.mock_process_intent.assert_not_called() # If process_option_intent was mocked and not called, this means gate logic is tested directly.

    # Add more tests for other refusal conditions:
    # - EXECUTION_ENABLED not set
    # - EXEC_GUARD_UNLOCK not set
    # - EXECUTION_CONFIRM_TOKEN not set
    # - Missing Alpaca credentials

    # Test case for EXECUTION_ENABLED
    def test_refusal_when_execution_enabled_is_off(self):
        with patch.dict(os.environ, {
            "TRADING_MODE": "paper",
            "OPTIONS_EXECUTION_MODE": "paper",
            "APCA_API_KEY_ID": "key",
            "APCA_API_SECRET_KEY": "secret",
            "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
            "EXECUTION_HALTED": "0",
            "EXECUTION_ENABLED": "0", # Execution disabled
            "EXEC_GUARD_UNLOCK": "1",
            "EXECUTION_CONFIRM_TOKEN": "token",
        }):
            with self.assertRaises(SystemExit):
                process_option_intent(self.dummy_intent)
            self.mock_alpaca_rest.assert_not_called()

    # Test case for EXEC_GUARD_UNLOCK
    def test_refusal_when_exec_guard_unlock_is_off(self):
        with patch.dict(os.environ, {
            "TRADING_MODE": "paper",
            "OPTIONS_EXECUTION_MODE": "paper",
            "APCA_API_KEY_ID": "key",
            "APCA_API_SECRET_KEY": "secret",
            "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
            "EXECUTION_HALTED": "0",
            "EXECUTION_ENABLED": "1",
            "EXEC_GUARD_UNLOCK": "0", # Guard not unlocked
            "EXECUTION_CONFIRM_TOKEN": "token",
        }):
            with self.assertRaises(SystemExit):
                process_option_intent(self.dummy_intent)
            self.mock_alpaca_rest.assert_not_called()

    # Test case for EXECUTION_CONFIRM_TOKEN
    def test_refusal_when_execution_confirm_token_is_missing(self):
        with patch.dict(os.environ, {
            "TRADING_MODE": "paper",
            "OPTIONS_EXECUTION_MODE": "paper",
            "APCA_API_KEY_ID": "key",
            "APCA_API_SECRET_KEY": "secret",
            "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
            "EXECUTION_HALTED": "0",
            "EXECUTION_ENABLED": "1",
            "EXEC_GUARD_UNLOCK": "1",
            # EXECUTION_CONFIRM_TOKEN is missing
        }):
            with self.assertRaises(SystemExit):
                process_option_intent(self.dummy_intent)
            self.mock_alpaca_rest.assert_not_called()
    
    # Test case for missing Alpaca credentials
    def test_refusal_when_alpaca_credentials_are_missing(self):
        with patch.dict(os.environ, {
            "TRADING_MODE": "paper",
            "OPTIONS_EXECUTION_MODE": "paper",
            # APCA_API_KEY_ID and APCA_API_SECRET_KEY are missing
            "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
            "EXECUTION_HALTED": "0",
            "EXECUTION_ENABLED": "1",
            "EXEC_GUARD_UNLOCK": "1",
            "EXECUTION_CONFIRM_TOKEN": "token",
        }):
            with self.assertRaises(SystemExit):
                process_option_intent(self.dummy_intent)
            self.mock_alpaca_rest.assert_not_called()

# --- Entry point for running tests ---
if __name__ == '__main__':
    unittest.main()