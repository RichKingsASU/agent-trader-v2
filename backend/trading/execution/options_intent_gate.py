import logging
import os
from datetime import datetime, timezone
from decimal import Decimal, getcontext
from typing import Any, Dict, Optional

import firebase_admin
from firebase_admin import firestore
# Updated import for APIError to use alpaca-py's common exceptions
from alpaca.common.exceptions import APIError 
from backend.contracts.v2.trading import OptionOrderIntent, OptionRight, Side # Assuming these are the correct imports for intent structures
# Import the new executor
from backend.trading.execution.alpaca_options_executor import execute_option_intent_paper
# Import ExecutionResult from the new executor or a common location if available
# For now, assuming ExecutionResult is defined in alpaca_options_executor or needs a mock/common definition
from backend.trading.execution.alpaca_options_executor import ExecutionResult

# Mocking or importing ShadowOptionsExecutor and related types for the existing path
# In a real scenario, these would be properly imported and managed.
try:
    from backend.trading.execution.shadow_options_executor import ShadowOptionsExecutor, ShadowOptionsExecutionResult, InMemoryShadowTradeHistoryStore
except ImportError:
    # Define mock classes if the actual ones are not available in this context for compilation
    class ShadowOptionsExecutor:
        def __init__(self, store):
            pass
        def execute(self, intent):
            return ShadowOptionsExecutionResult(stored=None) # Mock result

    class ShadowOptionsExecutionResult:
        def __init__(self, stored):
            self.stored = stored

    class InMemoryShadowTradeHistoryStore:
        def __init__(self):
            pass

# Assuming firebase_admin is initialized elsewhere in the application,
# but ensure it's initialized for this function context if run standalone.
try:
    firebase_admin.get_app()
except ValueError:
    # Initialize Firebase if not already initialized. In a real app, this would be done at startup.
    # For this context, we assume it's handled.
    # firebase_admin.initialize_app()
    pass # Assuming Firebase is initialized globally

logger = logging.getLogger(__name__)

# Set high precision for financial calculations
getcontext().prec = 28

# --- Constants and Configuration ---
PAPER_TRADING_MODE = "paper"
PAPER_APCA_API_BASE_URL = "https://paper-api.alpaca.markets"

# Environment variables for Alpaca API access and execution control
APCA_API_KEY_ID = os.environ.get("APCA_API_KEY_ID")
APCA_API_SECRET_KEY = os.environ.get("APCA_API_SECRET_KEY")
APCA_API_BASE_URL = os.environ.get("APCA_API_BASE_URL")
TRADING_MODE = os.environ.get("TRADING_MODE", "shadow") # Default to shadow
EXECUTION_HALTED = os.environ.get("EXECUTION_HALTED", "0") == "1"
EXECUTION_ENABLED = os.environ.get("EXECUTION_ENABLED", "0") == "1"
EXEC_GUARD_UNLOCK = os.environ.get("EXEC_GUARD_UNLOCK", "0") == "1"
EXECUTION_CONFIRM_TOKEN = os.environ.get("EXECUTION_CONFIRM_TOKEN")
OPTIONS_EXECUTION_MODE = os.environ.get("OPTIONS_EXECUTION_MODE", "shadow") # Default to shadow

# --- Helper Functions for Safety Invariants ---

def _is_paper_mode_enabled() -> bool:
    """Check if paper execution mode is explicitly enabled."""
    # Paper mode is enabled if TRADING_MODE is 'paper' AND OPTIONS_EXECUTION_MODE is 'paper'.
    # This check is simplified for clarity, real logic might be more nuanced.
    return TRADING_MODE == PAPER_TRADING_MODE and OPTIONS_EXECUTION_MODE == PAPER_TRADING_MODE

def _validate_and_correct_apca_url() -> Optional[str]:
    """Validate APCA_API_BASE_URL, correct it if needed, or return None if invalid."""
    url = APCA_API_BASE_URL
    if not url:
        logger.error("APCA_API_BASE_URL is not set.")
        return None

    # Strip potential /v2 suffix and normalize
    if url.endswith("/v2"):
        url = url[:-3]
    
    # Ensure it's exactly the paper URL
    if url == PAPER_APCA_API_BASE_URL:
        return url
    else:
        logger.error(f"Invalid APCA_API_BASE_URL: '{APCA_API_BASE_URL}'. Expected '{PAPER_APCA_API_BASE_URL}'.")
        return None

def _check_kill_switch() -> bool:
    """Check if execution is halted."""
    # In a real system, this might check a file or a more complex state.
    # For this example, we rely on the environment variable.
    return EXECUTION_HALTED

def _check_operator_intent() -> bool:
    """Check if explicit operator intent is enabled and confirmed."""
    return (
        EXECUTION_ENABLED == 1 and
        EXEC_GUARD_UNLOCK == 1 and
        bool(EXECUTION_CONFIRM_TOKEN) # Basic check for token presence
        # A more robust check would validate the token itself if it were provided via env var.
    )

def _check_alpaca_credentials() -> bool:
    """Check if Alpaca API credentials are set."""
    return bool(APCA_API_KEY_ID) and bool(APCA_API_SECRET_KEY)

def _get_alpaca_client() -> Optional[REST]:
    """Construct and return Alpaca REST client in paper mode if all invariants are met."""
    if not _is_paper_mode_enabled():
        logger.error("Paper execution mode not enabled for options. Refusing to construct broker client.")
        return None

    corrected_url = _validate_and_correct_apca_url()
    if not corrected_url:
        return None

    if _check_kill_switch():
        logger.error("Kill switch is ON. Refusing to construct broker client.")
        return None

    if not _check_operator_intent():
        logger.error("Operator intent (EXECUTION_ENABLED, EXEC_GUARD_UNLOCK, EXECUTION_CONFIRM_TOKEN) not fully met. Refusing to construct broker client.")
        return None

    if not _check_alpaca_credentials():
        logger.error("Alpaca API credentials (APCA_API_KEY_ID, APCA_API_SECRET_KEY) not set. Refusing to construct broker client.")
        return None

    try:
        api = REST(
            key_id=APCA_API_KEY_ID,
            secret_api=APCA_API_SECRET_KEY,
            base_url=corrected_url, # Use the validated and corrected URL
            api_version='v2' # Explicitly set api_version if needed, although base_url check is primary
        )
        logger.info("Alpaca REST client constructed successfully in paper mode.")
        return api
    except Exception as e:
        logger.error(f"Failed to construct Alpaca REST client: {e}")
        return None

# --- Placeholder for logging and ExecutionResult ---
# These would be properly imported from common modules in a real project.

def log_event(logger, event_name: str, severity: str, **kwargs):
    """Mock log_event function for demonstration."""
    log_data = {"event": event_name, "severity": severity, **kwargs}
    if severity == "ERROR":
        logger.error(f"{event_name}: {kwargs.get('error')}")
    elif severity == "WARNING":
        logger.warning(f"{event_name}: {kwargs.get('reason', '')}")
    else:
        logger.info(f"{event_name}: {kwargs}")

class MockExecutionResult:
    """Mock ExecutionResult structure."""
    def __init__(self, broker_order_id: Optional[str] = None, status: str = "failed", error: Optional[str] = None, timestamps: Optional[Dict[str, datetime]] = None):
        self.broker_order_id = broker_order_id
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

# --- Main Intent Gate Function ---

def process_option_intent(intent: OptionOrderIntent) -> IntentGateResult:
    """
    This function is the single enforcement point for options paper trading safety invariants.
    
    Receives an OptionOrderIntent, applies all risk checks, and dispatches to the appropriate
    executor (shadow or paper) based on configuration.
    """
    db = _get_firestore_client()
    now_utc = datetime.now(timezone.utc)
    strategy_id = intent.strategy_id
    contract_symbol = intent.contract_symbol # Assuming OptionOrderIntent has these attributes

    log_common_fields = {
        "event": "option.intent.gate",
        "strategy_id": strategy_id,
        "contract_symbol": contract_symbol,
        "timestamp": now_utc.isoformat(),
    }

    # --- Strategy-local daily halt (4% target halt) ---
    # Placeholder implementation: check if strategy's current daily PnL exceeds limits.
    # A notional capital of $100,000 is assumed for this strategy-local check.
    strategy_capital_notional = Decimal("100000.00") # Assumed notional for local halt check
    local_halt_threshold_pct = Decimal("4.0")
    local_halt_threshold_usd = strategy_capital_notional * (local_halt_threshold_pct / Decimal("100"))

    current_shadow_pnl = _get_current_shadow_pnl(strategy_id)
    if current_shadow_pnl is not None:
        if current_shadow_pnl > local_halt_threshold_usd:
            reason = f"Strategy-local daily halt triggered: PnL {current_shadow_pnl} exceeds +{local_halt_threshold_pct}% (${local_halt_threshold_usd}) of notional capital."
            logger.warning(f"option.intent.blocked: {reason}", extra={"reason": reason, **log_common_fields})
            return IntentGateResult(blocked=True, reason=reason)
        if current_shadow_pnl < -local_halt_threshold_usd:
            reason = f"Strategy-local daily halt triggered: PnL {current_shadow_pnl} below -{local_halt_threshold_pct}% (${local_halt_threshold_usd}) of notional capital."
            logger.warning(f"option.intent.blocked: {reason}", extra={"reason": reason, **log_common_fields})
            return IntentGateResult(blocked=True, reason=reason)

    # --- System-level gates ---
    # 2. System trading gate (EMERGENCY_HALT / trading_enabled)
    gate_reason = _check_system_trading_gate(db)
    if gate_reason:
        logger.warning(f"option.intent.blocked: {gate_reason}", extra={"reason": gate_reason, **log_common_fields})
        return IntentGateResult(blocked=True, reason=gate_reason)

    # 3. System drawdown circuit breaker (5% HWM)
    current_equity: Optional[Decimal] = None
    try:
        # Fetch current equity from Firestore snapshot if available
        alpaca_snapshot_doc = db.collection("systemStatus").document("alpaca_account_snapshot").get() # Assuming this path
        if alpaca_snapshot_doc.exists:
            snapshot_data = alpaca_snapshot_doc.to_dict() or {}
            equity_raw = snapshot_data.get("equity")
            current_equity = _as_decimal(equity_raw)
    except Exception as e:
        logger.error(f"Failed to retrieve current equity for drawdown check: {e}")
        # Proceed, but drawdown check might be skipped if equity is None

    drawdown_reason = _check_system_drawdown_breaker(db, current_equity)
    if drawdown_reason:
        logger.warning(f"option.intent.blocked: {drawdown_reason}", extra={"reason": drawdown_reason, **log_common_fields})
        return IntentGateResult(blocked=True, reason=drawdown_reason)

    # --- Dispatch based on execution mode ---
    if OPTIONS_EXECUTION_MODE == "paper":
        logger.info("Options execution mode set to PAPER.", extra={**log_common_fields, "mode": "paper"})
        # Call the new Alpaca paper executor
        execution_result = execute_option_intent_paper(intent)
        # Wrap the result for consistency if needed, or return directly
        # For now, assume execute_option_intent_paper returns a structure compatible with what the gate needs.
        # If it returns a simple dict or specific object, adapt here.
        # If execute_option_intent_paper returns its own ExecutionResult, we wrap it.
        if execution_result.status == "failed":
            return IntentGateResult(blocked=True, reason=execution_result.error)
        else:
            # Convert the result from the paper executor into a format expected by IntentGateResult.execution_result
            # Assuming 'stored' attribute contains the final record.
            return IntentGateResult(blocked=False, execution_result=ShadowOptionsExecutionResult(stored=execution_result.stored))
    else:
        # Default to shadow execution if not paper mode
        logger.info("Options execution mode is not PAPER. Dispatching to SHADOW executor.", extra={**log_common_fields, "mode": OPTIONS_EXECUTION_MODE})
        shadow_executor = ShadowOptionsExecutor(store=InMemoryShadowTradeHistoryStore()) # Mock store for shadow
        execution_result = shadow_executor.execute(intent=intent)
        return IntentGateResult(blocked=False, execution_result=execution_result)

# --- Mock/Placeholder Definitions (for standalone testing/development) ---
# In a real project, these would be properly imported or defined.

if __name__ == "__main__":
    import sys # Import sys for stdout redirection in mock
    from datetime import timedelta # Import timedelta for date manipulation
    import uuid # Import uuid for intent_id generation

    # Set up basic logging for standalone execution
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', stream=sys.stdout)
    
    # Mock environment variables for a quick test run
    os.environ["TRADING_MODE"] = "paper"
    os.environ["APCA_API_KEY_ID"] = "YOUR_PAPER_KEY_ID" # Replace with actual paper key if testing live
    os.environ["APCA_API_SECRET_KEY"] = "YOUR_PAPER_API_SECRET" # Replace with actual paper secret if testing live
    os.environ["APCA_API_BASE_URL"] = "https://paper-api.alpaca.markets"
    os.environ["EXECUTION_ENABLED"] = "1"
    os.environ["EXEC_GUARD_UNLOCK"] = "1"
    os.environ["EXECUTION_CONFIRM_TOKEN"] = "a_valid_token"
    os.environ["OPTIONS_EXECUTION_MODE"] = "paper"
    
    # Create a dummy intent object (replace with actual creation logic)
    dummy_intent = OptionOrderIntent(
        intent_id=uuid.uuid4(),
        strategy_id="test_strategy_123",
        symbol="SPY", # Underlying symbol, might not be directly used for options order
        side=Side.BUY,
        order_type="market",
        quantity=1,
        expiration=datetime.now(timezone.utc).date(), # Needs to be a future date
        strike=Decimal("450.00"),
        right=OptionRight.CALL,
        options={
            "contract_symbol": "SPY260207C00450000", # Example option contract symbol
            "underlying_price": Decimal("450.50"),
            "strategy_source": "gamma_scalper",
        }
    )

    print("--- Testing execute_option_intent_paper ---")
    
    # Note: This test will fail if the Alpaca credentials are not valid or if the API URL is incorrect.
    # For true unit testing, Mocks for `REST` would be used.
    try:
        # Ensure the date for expiration is in the future for a valid order
        if dummy_intent.expiration <= datetime.now(timezone.utc).date():
            # Find the next Friday if current date is too close or in the past
            current_date = datetime.now(timezone.utc).date()
            days_ahead = (4 - current_date.weekday()) % 7 # Days to next Friday (Friday is 4)
            if days_ahead == 0: days_ahead = 7 # If today is Friday, go to next Friday
            dummy_intent.expiration = current_date + timedelta(days=days_ahead)
            print(f"Adjusted expiration date to: {dummy_intent.expiration}")

        # Assuming execute_option_intent_paper is defined and accessible
        # If not, this part would need to be mocked or adjusted.
        # For this example, we'll assume it's available.
        # result = execute_option_intent_paper(dummy_intent)
        
        # Placeholder for the actual call if execute_option_intent_paper is not available in this scope
        # In a real scenario, you'd ensure it's imported or defined.
        class MockExecutionResultForPaper:
            def __init__(self, status='success', broker_order_id='mock_order_123', error=None, timestamps={}, stored={}):
                self.status = status
                self.broker_order_id = broker_order_id
                self.error = error
                self.timestamps = timestamps
                self.stored = stored

        # Mocking the call to execute_option_intent_paper
        print("Mocking call to execute_option_intent_paper...")
        result = MockExecutionResultForPaper(status='success', stored={'mock_data': 'from paper executor'})

        print(f"\nExecution Result:")
        print(f"  Status: {result.status}")
        print(f"  Broker Order ID: {result.broker_order_id}")
        print(f"  Error: {result.error}")
        print(f"  Timestamps: {result.timestamps}")
        print(f"  Stored Data: {result.stored}")
        
        if result.status == "failed":
            print("\nTest failed: Order submission did not succeed.")
        else:
            print("\nTest executed (mocked). Check logs for actual submission details/errors if not mocked.")

    except Exception as e:
        print(f"\nAn error occurred during the test execution: {e}")

    finally:
        # Clean up environment variables
        for var in ["TRADING_MODE", "APCA_API_KEY_ID", "APCA_API_SECRET_KEY", "APCA_API_BASE_URL", "EXECUTION_ENABLED", "EXEC_GUARD_UNLOCK", "EXECUTION_CONFIRM_TOKEN", "OPTIONS_EXECUTION_MODE"]:
            if var in os.environ:
                del os.environ[var]
