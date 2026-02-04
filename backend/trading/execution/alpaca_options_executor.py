from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional
import os
import logging
import uuid

# Import necessary classes from alpaca_trade_api
from alpaca_trade_api.rest import REST, APIError, TimeFrame
# Assuming OptionOrderIntent and Side, OptionRight enums are available or defined.
# For this example, we'll use placeholder enums if not explicitly found in the context.
# In a real scenario, these would be imported from backend.contracts.v2.trading or similar.

# --- Placeholder Definitions for Contract Types (if not imported) ---
# These should be replaced with actual imports from the project.
from enum import Enum

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
    expiration: datetime.date # Should be a date object
    strike: Decimal
    right: OptionRight
    options: Dict[str, Any] # Other contract-specific details

# --- Execution Result Structure ---
@dataclass
class ExecutionResult:
    broker_order_id: Optional[str] = None
    status: str = "failed"  # e.g., "submitted", "failed", "filled"
    error: Optional[str] = None
    timestamps: Dict[str, datetime] = field(default_factory=dict)
    stored: Any = None # To hold data that will be passed to the gate's ShadowOptionsExecutionResult

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

logger = logging.getLogger(__name__)

# --- Helper Functions for Safety Invariants ---

def _is_paper_mode_enabled_for_executor() -> bool:
    """Check if paper execution mode is explicitly enabled for this executor."""
    # This function ensures that when this executor is called, paper mode is intended.
    # It's a subset of checks done in the gate, specifically for direct executor invocation.
    return (
        TRADING_MODE == PAPER_TRADING_MODE
        and OPTIONS_EXECUTION_MODE == PAPER_TRADING_MODE
        and APCA_API_BASE_URL is not None
        and _validate_and_correct_apca_url() is not None
        and not _check_kill_switch()
        and _check_operator_intent()
        and _check_alpaca_credentials()
    )

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
    return EXECUTION_HALTED

def _check_operator_intent() -> bool:
    """Check if explicit operator intent is enabled and confirmed."""
    return (
        EXECUTION_ENABLED
        and EXEC_GUARD_UNLOCK
        and bool(EXECUTION_CONFIRM_TOKEN) # Basic check for token presence
    )

def _check_alpaca_credentials() -> bool:
    """Check if Alpaca API credentials are set."""
    return bool(APCA_API_KEY_ID) and bool(APCA_API_SECRET_KEY)

def _get_alpaca_trading_client() -> Optional[REST]:
    """Construct and return Alpaca REST client in paper mode if all invariants are met."""
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
            base_url=corrected_url,
            api_version='v2'
        )
        logger.info("Alpaca REST client constructed successfully in paper mode.")
        return api
    except Exception as e:
        logger.error(f"Failed to construct Alpaca REST client: {e}")
        return None

# --- Main Execution Function for Paper Mode ---

def execute_option_intent_paper(intent: OptionOrderIntent) -> ExecutionResult:
    """
    Submits an options order to Alpaca in paper trading mode after enforcing safety invariants.
    """
    start_time = datetime.now(timezone.utc)
    log_common_fields = {
        "event": "option.intent.executor.paper",
        "strategy_id": intent.strategy_id,
        "contract_symbol": intent.options.get("contract_symbol", intent.symbol), # Use contract_symbol from options if available, else fallback to symbol
        "intent_id": str(intent.intent_id),
        "timestamp": start_time.isoformat(),
    }

    # 1. Enforce safety invariants BEFORE any Alpaca client construction.
    #    These checks are partially duplicated from the gate for executor robustness.
    if not _is_paper_mode_enabled_for_executor():
        error_msg = "Pre-execution safety invariants not met for paper trading."
        logger.error(error_msg, extra={**log_common_fields, "error": error_msg})
        # Return a failed result
        return ExecutionResult(
            status="failed",
            error=error_msg,
            timestamps={"start": start_time, "end": datetime.now(timezone.utc)},
            stored=None # No execution attempt made
        )

    # 2. Construct the Alpaca TradingClient
    trading_client = _get_alpaca_trading_client()
    if not trading_client:
        # Error logged within _get_alpaca_trading_client
        error_msg = "Failed to construct Alpaca trading client."
        return ExecutionResult(
            status="failed",
            error=error_msg,
            timestamps={"start": start_time, "end": datetime.now(timezone.utc)},
            stored=None
        )

    # 3. Prepare and submit the options order
    try:
        # Map OptionOrderIntent to Alpaca's option order format.
        # This mapping needs to be accurate based on alpaca-py's API for options.
        # Refer to alpaca-py documentation for options order submission.
        
        # Alpaca's create_order API for options typically uses the contract symbol.
        order_params = {
            "symbol": intent.options.get("contract_symbol", intent.symbol), # Use contract symbol from intent.options
            "qty": intent.quantity,
            "side": intent.side.value, # 'buy' or 'sell'
            "type": intent.order_type, # 'market', 'limit', etc.
            "time_in_force": "day", # Default to 'day' for simplicity, adjust if needed
            # Add limit price if order_type is 'limit'
            # "limit_price": Decimal("1.23"),
            # For options, the order class is typically 'simple' for single legs.
            "order_class": "simple",
        }
        
        # Alpaca's `submit_order` method should handle options if the symbol is an option symbol.
        # We rely on the TradingClient being configured with the paper URL.
        
        logger.info(f"Submitting options order to Alpaca: {order_params}", extra=log_common_fields)
        
        order_response = trading_client.submit_order(**order_params)
        
        broker_order_id = order_response.id
        status = order_response.status # e.g., 'new', 'partially_filled', 'filled', 'rejected', 'canceled'
        
        # Log successful submission
        log_event(logger, "option_intent_submitted", "INFO", broker_order_id=broker_order_id, status=status, **log_common_fields)

        # Construct the 'stored' part of the result.
        execution_data_to_store = {
            "broker_order_id": broker_order_id,
            "status": status,
            "alpaca_response": order_response.dict(), # Capture raw response if needed
            "submitted_at": start_time,
            "received_at": datetime.now(timezone.utc)
        }

        return ExecutionResult(
            broker_order_id=broker_order_id,
            status=status,
            timestamps={"start": start_time, "end": datetime.now(timezone.utc)},
            stored=execution_data_to_store
        )

    except APIError as e:
        error_msg = f"Alpaca API Error during order submission: {e}"
        logger.error(error_msg, extra={**log_common_fields, "error": error_msg, "alpaca_error_code": e.code, "alpaca_error_status": e.status})
        return ExecutionResult(
            status="failed",
            error=error_msg,
            timestamps={"start": start_time, "end": datetime.now(timezone.utc)},
            stored=None # No execution attempt resulted in a stored record
        )
    except Exception as e:
        error_msg = f"Unexpected error during order submission: {e}"
        logger.error(error_msg, extra={**log_common_fields, "error": error_msg})
        return ExecutionResult(
            status="failed",
            error=error_msg,
            timestamps={"start": start_time, "end": datetime.now(timezone.utc)},
            stored=None
        )

# --- Mocking/Utility Functions (if needed for testing or standalone execution) ---
def log_event(logger, event_name: str, severity: str, **kwargs):
    """Mock log_event function for demonstration."""
    log_data = {"event": event_name, "severity": severity, **kwargs}
    if severity == "ERROR":
        logger.error(f"{event_name}: {kwargs.get('error')}")
    elif severity == "WARNING":
        logger.warning(f"{event_name}: {kwargs.get('reason', '')}")
    else:
        logger.info(f"{event_name}: {kwargs}")

# --- Example of how this might be used (for testing purposes) ---
if __name__ == "__main__":
    import sys # Import sys for stdout redirection in mock
    from datetime import timedelta # Import timedelta for date manipulation

    # Set up basic logging for standalone execution
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', stream=sys.stdout)
    
    # Mock environment variables for a quick test run
    os.environ["TRADING_MODE"] = "paper"
    os.environ["APCA_API_KEY_ID"] = "YOUR_PAPER_KEY_ID" # Replace with actual paper key if testing live
    os.environ["APCA_API_SECRET_KEY"] = "YOUR_PAPER_SECRET_KEY" # Replace with actual paper secret if testing live
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

        result = execute_option_intent_paper(dummy_intent)
        print(f"\nExecution Result:")
        print(f"  Status: {result.status}")
        print(f"  Broker Order ID: {result.broker_order_id}")
        print(f"  Error: {result.error}")
        print(f"  Timestamps: {result.timestamps}")
        print(f"  Stored Data: {result.stored}")
        
        if result.status == "failed":
            print("\nTest failed: Order submission did not succeed.")
        else:
            print("\nTest executed (check logs for actual submission details/errors).")

    except Exception as e:
        print(f"\nAn error occurred during the test execution: {e}")

    finally:
        # Clean up environment variables
        for var in ["TRADING_MODE", "APCA_API_KEY_ID", "APCA_API_SECRET_KEY", "APCA_API_BASE_URL", "EXECUTION_ENABLED", "EXEC_GUARD_UNLOCK", "EXECUTION_CONFIRM_TOKEN", "OPTIONS_EXECUTION_MODE"]:
            if var in os.environ:
                del os.environ[var]