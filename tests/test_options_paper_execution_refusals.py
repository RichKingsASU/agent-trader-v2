import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation, getcontext
from typing import Any, Dict, List, Optional
import os
import sys
import uuid

# Mocking or importing necessary components
# These mocks are crucial for tests to run without actual external dependencies.

# --- Mock classes for the structures used in the gate and executor ---
class ExecutionResult:
    """Mock ExecutionResult structure."""
    def __init__(self, broker_order_id: Optional[str] = None, status: str = "failed", error: Optional[str] = None, timestamps: Optional[Dict[str, datetime]] = None):
        selfself.broker_order_id = broker_order_id
        self.status = status
        self.error = error
        self.timestamps = timestamps if timestamps is not None else {}
        self.stored = self.to_dict() # Simulating a 'stored' attribute if needed by caller

    def to_dict(self) -> Dict[str, Any]:
        return {
            "broker_order_id": self.broker_order_id,
            "status": self.status,
            "error": self.error,
            "timestamps": {k: v.isoformat() for k, v in self.timestamps.items()} if self.timestamps else {}
        }

class OptionOrderIntent:
    """Mocking a simplified structure based on expected usage."""
    def __init__(self, intent_id: uuid.UUID, strategy_id: str, symbol: str, side: str, order_type: str, quantity: int, expiration: datetime.date, strike: float, right: str, options: Dict[str, Any]):
        self.intent_id = intent_id
        self.strategy_id = strategy_id
        self.symbol = symbol
        self.side = side
        self.order_type = order_type
        self.quantity = quantity
        self.expiration = expiration
        self.strike = strike
        self.right = right
        self.options = options

# --- Mocking imports that cause ModuleNotFoundError during test collection ---
# Mocking alpaca_trade_api.rest.REST and APIError
class MockAlpacaAPIError(Exception):
    """Mock APIError for alpaca_trade_api.rest.api."""
    pass

class MockAlpacaREST:
    """Mock Alpaca REST client."""
    def __init__(self, *args, **kwargs):
        pass
    def submit_order(self, **kwargs):
        # Mock successful submission with a dummy order ID
        return MagicMock(id=f"mock_order_{uuid.uuid4().hex[:12]}")

# --- Mocking other dependencies ---
class MockShadowOptionsExecutor:
    """Mock ShadowOptionsExecutor."""
    def __init__(self, store):
        self.store = store
        self.execute = MagicMock() # Mock the execute method

class MockShadowOptionsExecutionResult:
    """Mock ShadowOptionsExecutionResult structure."""
    def __init__(self, stored):
        self.stored = stored

class MockInMemoryShadowTradeHistoryStore:
    """Mock InMemoryShadowTradeHistoryStore."""
    def __init__(self):
        pass

# --- Patching modules and classes ---
# These patches are applied to ensure tests run in isolation and do not make external calls.
# Patching core components like REST client, APIError, executor, and gate functions.

# IMPORTANT: Patching at the module level where they are USED, not where they are DEFINED.
# For alpaca_trade_api, it's used in alpaca_options_executor.py, but imported in options_intent_gate.py.
# The import error happens during options_intent_gate.py collection, so we need to patch where it's IMPORTED.
@patch('backend.trading.execution.options_intent_gate.APIError', MockAlpacaAPIError)
@patch('backend.trading.execution.options_intent_gate.REST', MockAlpacaREST)
@patch('backend.trading.execution.options_intent_gate.OptionOrderIntent', OptionOrderIntent)
@patch('backend.trading.execution.options_intent_gate.ExecutionResult', MockExecutionResult)
@patch('backend.trading.execution.options_intent_gate.uuid', uuid)
@patch('backend.trading.execution.options_intent_gate.datetime', MagicMock(now=lambda tz=None: datetime(2026, 2, 3, 15, 0, 0, tzinfo=timezone.utc)))
@patch('backend.trading.execution.options_intent_gate.os.environ', os.environ)
@patch('backend.trading.execution.options_intent_gate.log_event', lambda logger, event_name, severity, **kwargs: None)
# Patching the executor class itself as used within options_intent_gate
@patch('backend.trading.execution.options_intent_gate.ShadowOptionsExecutor', MagicMock(return_value=MockShadowOptionsExecutor(store=None)))
@patch('backend.trading.execution.options_intent_gate.ShadowOptionsExecutionResult', MockShadowOptionsExecutionResult)
@patch('backend.trading.execution.options_intent_gate.InMemoryShadowTradeHistoryStore', MockInMemoryShadowTradeHistoryStore)


# Now import the function under test AFTER setting up mocks for its dependencies in its module
from backend.trading.execution.options_intent_gate import process_option_intent, IntentGateResult
# Ensure other necessary imports are available
from backend.contracts.v2.trading import OptionOrderIntent, OptionRight, Side # Assuming these are the correct imports
from backend.trading.execution.alpaca_options_executor import execute_option_intent_paper # Import the actual executor function
from backend.trading.execution.alpaca_options_executor import ExecutionResult # Import ExecutionResult


# Mocking _as_decimal helper as it's used within the gate logic and might rely on external context
@patch('backend.trading.execution.options_intent_gate._as_decimal', lambda v: Decimal(str(v)) if v is not None else Decimal("0"))
class TestOptionsPaperExecutionRefusals(unittest.TestCase):

    def setUp(self):
        """Set up mocks and default environment variables for tests."""
        # Patching system environment variables and imports to control behavior
        self.patcher_os_environ = patch.dict(os.environ, {
            "TRADING_MODE": "paper",
            "APCA_API_KEY_ID": "MOCK_PAPER_KEY_ID",
            "APCA_API_SECRET_KEY": "MOCK_PAPER_API_SECRET",
            "APCA_API_BASE_URL": "https://paper-api.alpaca.markets",
            "EXECUTION_ENABLED": "1",
            "EXEC_GUARD_UNLOCK": "1",
            "EXECUTION_CONFIRM_TOKEN": "a_secret_token",
            "OPTIONS_EXECUTION_MODE": "paper", # Default to paper for these tests
        }, clear=True)
        self.mock_environ = self.patcher_os_environ.start()

        # Mocking Alpaca client construction directly.
        # The executor's _get_alpaca_client will use the mocked REST.
        # We need to patch where it's USED, which is in alpaca_options_executor.
        self.mock_trading_client = MagicMock()
        self.patcher_rest_client = patch('backend.trading.execution.alpaca_options_executor.REST', return_value=self.mock_trading_client)
        self.mock_rest_client = self.patcher_rest_client.start()

        # Mocking Firestore client and Firestore data for gate checks
        self.mock_firestore_client = MagicMock()
        # Mocking the chain of calls: collection().document().get()
        self.mock_firestore_client.collection.return_value.document.return_value.get.side_effect = self._mock_firestore_get
        self.patcher_firestore = patch('backend.trading.execution.options_intent_gate._get_firestore_client', return_value=self.mock_firestore_client)
        self.mock_firestore = self.patcher_firestore.start()

        # Mocking ShadowOptionsExecutor to verify it's NOT called when paper mode is active
        self.mock_shadow_executor_instance = MagicMock()
        self.patcher_shadow_executor_cls = patch('backend.trading.execution.options_intent_gate.ShadowOptionsExecutor', return_value=self.mock_shadow_executor_instance)
        self.mock_shadow_executor_cls = self.patcher_shadow_executor_cls.start()
        
        # Mocking log_event to check logging calls
        self.mock_log_event_patcher = patch('backend.trading.execution.options_intent_gate.log_event')
        self.mock_log_event = self.mock_log_event_patcher.start()
        
        # Mocking datetime.now for predictable timestamps if needed
        self.patcher_datetime = patch('backend.trading.execution.options_intent_gate.datetime')
        self.mock_datetime = self.patcher_datetime.start()
        self.mock_datetime.now.return_value = datetime(2026, 2, 3, 15, 0, 0, tzinfo=timezone.utc) # Example time

    def tearDown(self):
        """Stop all mocks."""
        self.patcher_os_environ.stop()
        self.patcher_rest_client.stop()
        self.patcher_firestore.stop()
        self.patcher_shadow_executor_cls.stop()
        self.mock_log_event_patcher.stop()
        self.patcher_datetime.stop()
        self.patcher_os_environ.stop() # Stop os.environ patch as well

    def _mock_firestore_get(self, *args, **kwargs):
        """Mock Firestore get calls based on the document path."""
        # Simulating paths used in _check_system_trading_gate and _check_system_drawdown_breaker
        # The actual path construction might differ; this is an approximation.
        path_str = '/'.join(map(str, args)) # Combine args into a string path
        
        if 'systemStatus/trading_gate' in path_str:
            # Simulate trading gate being open
            return MagicMock(exists=True, to_dict=lambda: {"trading_enabled": True, "status": "OPEN"})
        elif 'systemStatus/alpaca_account_snapshot' in path_str:
            # Simulate a healthy equity for drawdown check
            return MagicMock(exists=True, to_dict=lambda: {"equity": "100000.00"})
        elif 'systemStatus/risk' in path_str:
            # Simulate HWM that does not trigger drawdown breaker
            return MagicMock(exists=True, to_dict=lambda: {"high_water_mark": "105000.00"})
        return MagicMock(exists=False, to_dict=lambda: {}) # Default to not found

    def _create_mock_intent(self) -> OptionOrderIntent:
        """Helper to create a mock OptionOrderIntent."""
        # Ensure expiry is in the future for a valid intent
        future_date = (self._mock_datetime.now().date() + timedelta(days=5))
        return OptionOrderIntent(
            intent_id=uuid.uuid4(),
            strategy_id="test_strategy",
            symbol="SPY",
            side=Side.BUY, # Using enum members
            order_type="market",
            quantity=1,
            expiration=future_date,
            strike=450.0,
            right=OptionRight.CALL, # Using enum members
            options={
                "contract_symbol": f"SPY{future_date.strftime('%y%m%d')}C00450000", # Example, needs proper format
                "underlying_price": 450.50,
                "strategy": "test_strategy",
                "macro_event_active": False,
            }
        )

    def test_refusal_if_kill_switch_on(self):
        """Verify refusal if EXECUTION_HALTED is '1'."""
        self.mock_environ["EXECUTION_HALTED"] = "1"
        intent = self._create_mock_intent()
        result = process_option_intent(intent)
        self.assertTrue(result.blocked)
        self.assertIn("Kill switch is ON", result.reason)
        self.mock_trading_client.submit_order.assert_not_called() # Ensure no broker call
        self.mock_shadow_executor_instance.execute.assert_not_called() # Ensure shadow executor is not called

    def test_refusal_if_trading_mode_not_paper(self):
        """Verify refusal if TRADING_MODE is not 'paper'."""
        self.mock_environ["TRADING_MODE"] = "shadow" # Force shadow mode
        self.mock_environ["OPTIONS_EXECUTION_MODE"] = "paper" # Still try to enable paper for options
        intent = self._create_mock_intent()
        result = process_option_intent(intent)
        self.assertTrue(result.blocked)
        self.assertIn("TRADING_MODE is not set to 'paper'", result.reason)
        self.mock_trading_client.submit_order.assert_not_called()
        self.mock_shadow_executor_instance.execute.assert_not_called()

    def test_refusal_if_invalid_apca_url(self):
        """Verify refusal if APCA_API_BASE_URL is invalid."""
        self.mock_environ["APCA_API_BASE_URL"] = "https://api.alpaca.markets/v2" # Invalid URL for paper
        intent = self._create_mock_intent()
        result = process_option_intent(intent)
        self.assertTrue(result.blocked)
        self.assertIn("Invalid APCA_API_BASE_URL", result.reason)
        self.mock_trading_client.submit_order.assert_not_called()
        self.mock_shadow_executor_instance.execute.assert_not_called()
        
    def test_refusal_if_operator_intent_not_met(self):
        """Verify refusal if EXECUTION_ENABLED or EXEC_GUARD_UNLOCK are not set."""
        del self.mock_environ["EXECUTION_ENABLED"] # Remove required var
        intent = self._create_mock_intent()
        result = process_option_intent(intent)
        self.assertTrue(result.blocked)
        self.assertIn("EXECUTION_ENABLED must be '1'", result.reason)
        self.mock_trading_client.submit_order.assert_not_called()
        self.mock_shadow_executor_instance.execute.assert_not_called()

    def test_refusal_if_no_confirm_token(self):
        """Verify refusal if EXECUTION_CONFIRM_TOKEN is not set."""
        del self.mock_environ["EXECUTION_CONFIRM_TOKEN"] # Remove required var
        intent = self._create_mock_intent()
        result = process_option_intent(intent)
        self.assertTrue(result.blocked)
        self.assertIn("EXECUTION_CONFIRM_TOKEN is not set.", result.reason)
        self.mock_trading_client.submit_order.assert_not_called()
        self.mock_shadow_executor_instance.execute.assert_not_called()

    def test_refusal_if_missing_alpaca_credentials(self):
        """Verify refusal if Alpaca API keys are missing."""
        del self.mock_environ["APCA_API_KEY_ID"] # Remove required var
        intent = self._create_mock_intent()
        result = process_option_intent(intent)
        self.assertTrue(result.blocked)
        self.assertIn("APCA_API_KEY_ID or APCA_API_SECRET_KEY not set.", result.reason)
        self.mock_trading_client.submit_order.assert_not_called()
        self.mock_shadow_executor_instance.execute.assert_not_called()

    def test_shadow_mode_is_default_and_behaves_correctly(self):
        """Verify default behavior is shadow mode and it executes without broker client."""
        # Ensure paper mode is not explicitly enabled by env vars
        for key in ["TRADING_MODE", "OPTIONS_EXECUTION_MODE", "APCA_API_BASE_URL",
                    "EXECUTION_ENABLED", "EXEC_GUARD_UNLOCK", "EXECUTION_CONFIRM_TOKEN"]:
            if key in os.environ:
                del os.environ[key]
        
        intent = self._create_mock_intent()
        result = process_option_intent(intent)

        self.assertFalse(result.blocked)
        self.assertIsNone(result.reason)
        # Verify ShadowOptionsExecutor was called and Alpaca client was NOT constructed
        self.mock_shadow_executor_instance.execute.assert_called_once_with(intent=intent)
        self.mock_trading_client.submit_order.assert_not_called() # Ensure no broker call
        self.assertFalse(self.mock_rest_client.called) # Ensure REST client wasn't instantiated


if __name__ == "__main__":
    # This block is for demonstrating the gate logic.
    # In a real test suite, these would be managed by the test runner.
    # Ensure environment variables are set for paper execution if testing that path.
    
    # Basic setup for running tests directly if needed
    # unittest.main()
    pass # Prevent unittest.main() from running when imported as a module
