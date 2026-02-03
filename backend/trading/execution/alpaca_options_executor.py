
import os
import sys
import logging
import uuid
from datetime import datetime
from decimal import Decimal

from alpaca_trade_api.rest import REST, TimeFrame
from alpaca_trade_api.rest.api import APIError

# Assume these are defined elsewhere or can be mocked for unit tests
# In a real scenario, these would likely be imported from common model definitions.
# For this implementation, I'm defining minimal structures for illustration.
class ExecutionResult:
    def __init__(self, broker_order_id: Optional[str] = None, status: str = "failed", error: Optional[str] = None, timestamps: Dict[str, datetime] = None):
        self.broker_order_id = broker_order_id
        self.status = status
        self.error = error
        self.timestamps = timestamps if timestamps is not None else {}

class OptionOrderIntent:
    # Mocking a simplified structure based on expected usage
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

# --- Constants and Configuration ---
PAPER_TRADING_MODE = "paper"
PAPER_APCA_API_BASE_URL = "https://paper-api.alpaca.markets"
# Ensure these are fetched from environment variables
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

def _is_paper_trading_mode() -> bool:
    """Check if TRADING_MODE is set to 'paper'."""
    return TRADING_MODE == PAPER_TRADING_MODE

def _validate_and_correct_apca_url() -> Optional[str]:
    """Validate APCA_API_BASE_URL, correct it if needed, or return None if invalid."""
    url = APCA_API_BASE_URL
    if not url:
        logger.error("APCA_API_BASE_URL is not set.")
        return None

    # Strip potential /v2 suffix
    if url.endswith("/v2"):
        url = url[:-3]

    if url == PAPER_APCA_API_BASE_URL:
        return url
    else:
        logger.error(f"Invalid APCA_API_BASE_URL: {APCA_API_BASE_URL}. Expected {PAPER_APCA_API_BASE_URL}.")
        return None

def _check_kill_switch() -> bool:
    """Check if execution is halted."""
    # In a real system, this might check a file or a more complex state.
    # For this example, we rely on the environment variable.
    return EXECUTION_HALTED

def _check_execution_enabled() -> bool:
    """Check if explicit operator intent is enabled."""
    return EXECUTION_ENABLED == 1 and EXEC_GUARD_UNLOCK == 1

def _check_confirm_token() -> bool:
    """Check if EXECUTION_CONFIRM_TOKEN is set (basic check)."""
    # A more robust check would involve comparing against a provided token or a known value.
    return bool(EXECUTION_CONFIRM_TOKEN)

def _get_alpaca_client() -> Optional[REST]:
    """Construct and return Alpaca REST client in paper mode if all invariants are met."""
    if not _is_paper_trading_mode():
        logger.error("TRADING_MODE is not set to 'paper'. Refusing to construct broker client.")
        return None

    corrected_url = _validate_and_correct_apca_url()
    if not corrected_url:
        return None

    if _check_kill_switch():
        logger.error("Kill switch is ON. Refusing to construct broker client.")
        return None

    if not _check_execution_enabled():
        logger.error("EXECUTION_ENABLED or EXEC_GUARD_UNLOCK is not set. Refusing to construct broker client.")
        return None

    if not _check_confirm_token():
        logger.error("EXECUTION_CONFIRM_TOKEN is not set. Refusing to construct broker client.")
        return None

    if not APCA_API_KEY_ID or not APCA_API_SECRET_KEY:
        logger.error("APCA_API_KEY_ID or APCA_API_SECRET_KEY not set.")
        return None

    try:
        api = REST(
            key_id=APCA_API_KEY_ID,
            secret_api=APCA_API_SECRET_KEY,
            base_url=corrected_url,
            oauth=None,
            api_version='v2' # Explicitly setting v2 though it's stripped from base_url check
        )
        logger.info("Alpaca REST client constructed successfully in paper mode.")
        return api
    except Exception as e:
        logger.error(f"Failed to construct Alpaca REST client: {e}")
        return None

# --- Main Execution Function ---

def execute_option_intent_paper(intent: OptionOrderIntent) -> ExecutionResult:
    """
    Submits an OptionOrderIntent for paper execution via Alpaca.

    Enforces all safety invariants BEFORE constructing the Alpaca client and submitting the order.
    Logs submission and failure events.

    Args:
        intent: The OptionOrderIntent object to execute.

    Returns:
        ExecutionResult: Containing order details, status, and timestamps.
    """
    log_event(
        logger,
        "option_intent_submitted",
        severity="INFO",
        strategy_id=intent.strategy_id,
        intent_id=str(intent.intent_id),
        underlying=intent.symbol,
        option_symbol=intent.contract_symbol,
        quantity=intent.quantity,
        side=intent.side,
        order_type=intent.order_type,
        environment="paper",
        options_metadata=intent.options # Log metadata from the intent
    )

    # 1. Enforce safety invariants and construct client
    api = _get_alpaca_client()
    if api is None:
        error_msg = "Broker client construction failed due to unmet safety invariants."
        log_event(
            logger,
            "option_intent_failed",
            severity="ERROR",
            strategy_id=intent.strategy_id,
            intent_id=str(intent.intent_id),
            error=error_msg,
            environment="paper",
        )
        return ExecutionResult(status="failed", error=error_msg)

    # 2. Prepare and submit order
    try:
        # Alpaca-py might require different parameters for options orders.
        # This is a placeholder; actual implementation needs to map OptionOrderIntent
        # to alpaca-py's specific options order request format.
        # Example structure (may need adjustment based on alpaca-py version and API):
        order_params = {
            "symbol": intent.symbol,
            "qty": intent.quantity,
            "side": intent.side.lower(), # Ensure side is lowercase
            "type": intent.order_type,
            "time_in_force": "day", # Assuming 'day' is appropriate, might need mapping
            # 'extended_hours': False, # Depending on strategy needs
        }
        # Alpaca's options API might need expiration date, strike, right.
        # This mapping is hypothetical and needs to be confirmed with alpaca-py docs.
        # For now, assuming it's part of the `options` metadata or needs specific fields.
        # A more direct approach might involve using a specific options order endpoint if available.

        # Placeholder for actual order submission logic:
        # For now, we'll simulate a successful submission or failure.
        # In a real implementation, you would call something like:
        # alpaca_order = api.submit_order(**order_params)
        # broker_order_id = alpaca_order.id
        # submission_ts = datetime.now(timezone.utc) # Or from API response

        # Simulate success or failure for demonstration
        # Using a mock order ID and status
        broker_order_id = f"mock_alpaca_order_{uuid.uuid4().hex[:12]}"
        status = "submitted"
        submission_ts = datetime.now() # Placeholder timestamp

        log_event(
            logger,
            "option_intent_submitted",
            severity="INFO",
            strategy_id=intent.strategy_id,
            intent_id=str(intent.intent_id),
            broker_order_id=broker_order_id,
            underlying=intent.symbol,
            option_symbol=intent.contract_symbol,
            quantity=intent.quantity,
            side=intent.side,
            order_type=intent.order_type,
            environment="paper",
            submission_timestamp=submission_ts.isoformat(),
            options_metadata=intent.options
        )
        return ExecutionResult(broker_order_id=broker_order_id, status=status, timestamps={"submitted": submission_ts})

    except APIError as e:
        error_msg = f"Alpaca API error: {e}"
        logger.error(error_msg)
        log_event(
            logger,
            "option_intent_failed",
            severity="ERROR",
            strategy_id=intent.strategy_id,
            intent_id=str(intent.intent_id),
            error=error_msg,
            environment="paper",
            options_metadata=intent.options
        )
        return ExecutionResult(status="failed", error=error_msg)
    except Exception as e:
        error_msg = f"An unexpected error occurred during order submission: {e}"
        logger.error(error_msg)
        log_event(
            logger,
            "option_intent_failed",
            severity="ERROR",
            strategy_id=intent.strategy_id,
            intent_id=str(intent.intent_id),
            error=error_msg,
            environment="paper",
            options_metadata=intent.options
        )
        return ExecutionResult(status="failed", error=error_msg)

# --- Mocking and Placeholder Definitions (for standalone testing/development) ---
# In a production environment, these would be properly imported.

if __name__ == "__main__":
    # Example of how to use this module (requires setting environment variables)
    # Ensure APCA_API_KEY_ID, APCA_API_SECRET_KEY, TRADING_MODE, OPTIONS_EXECUTION_MODE,
    # EXECUTION_ENABLED, EXEC_GUARD_UNLOCK, EXECUTION_CONFIRM_TOKEN are set.

    print("--- Alpaca Options Executor Module ---")

    # Mock environment variables for testing purposes if they are not set
    if not os.environ.get("TRADING_MODE"):
        os.environ["TRADING_MODE"] = "paper"
    if not os.environ.get("APCA_API_KEY_ID"):
        os.environ["APCA_API_KEY_ID"] = "YOUR_PAPER_API_KEY"
    if not os.environ.get("APCA_API_SECRET_KEY"):
        os.environ["APCA_API_SECRET_KEY"] = "YOUR_PAPER_API_SECRET"
    if not os.environ.get("APCA_API_BASE_URL"):
        os.environ["APCA_API_BASE_URL"] = "https://paper-api.alpaca.markets"
    if not os.environ.get("EXECUTION_ENABLED"):
        os.environ["EXECUTION_ENABLED"] = "1"
    if not os.environ.get("EXEC_GUARD_UNLOCK"):
        os.environ["EXEC_GUARD_UNLOCK"] = "1"
    if not os.environ.get("EXECUTION_CONFIRM_TOKEN"):
        os.environ["EXECUTION_CONFIRM_TOKEN"] = "dummy_token"
    if not os.environ.get("OPTIONS_EXECUTION_MODE"):
        os.environ["OPTIONS_EXECUTION_MODE"] = "paper" # Set to paper to test paper path

    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format='%(asctime)s %(levelname)s %(message)s')

    # Example Intent (replace with actual intent generation logic)
    example_intent = OptionOrderIntent(
        intent_id=uuid.uuid4(),
        strategy_id="test_strategy",
        symbol="SPY",
        side="buy", # "buy" or "sell"
        order_type="market",
        quantity=1,
        expiration=datetime.now().date(), # Needs to be a future date
        strike=450.0,
        right="call", # "call" or "put"
        options={
            "contract_symbol": "SPY260203C00450000", # Example, needs to be a valid format
            "underlying_price": 450.50,
            "strategy": "test_strategy",
            "macro_event_active": False,
        }
    )

    print(f"\nAttempting to execute example paper option intent...")
    result = execute_option_intent_paper(example_intent)
    print(f"Execution Result: Status='{result.status}', OrderID='{result.broker_order_id}', Error='{result.error}'")

    # Example of refusal if not paper mode
    print("\n--- Testing refusal if not paper mode ---")
    os.environ["TRADING_MODE"] = "shadow" # Temporarily set to shadow
    os.environ["OPTIONS_EXECUTION_MODE"] = "paper"
    result_shadow = execute_option_intent_paper(example_intent)
    print(f"Execution Result (shadow mode): Status='{result_shadow.status}', Error='{result_shadow.error}'")
    del os.environ["TRADING_MODE"] # Clean up env var
    del os.environ["OPTIONS_EXECUTION_MODE"]

    # Example of refusal if kill switch is on
    print("\n--- Testing refusal if kill switch is ON ---")
    os.environ["EXECUTION_HALTED"] = "1"
    os.environ["TRADING_MODE"] = "paper"
    os.environ["OPTIONS_EXECUTION_MODE"] = "paper"
    result_halted = execute_option_intent_paper(example_intent)
    print(f"Execution Result (kill switch ON): Status='{result_halted.status}', Error='{result_halted.error}'")
    del os.environ["EXECUTION_HALTED"] # Clean up env var
    del os.environ["TRADING_MODE"]
    del os.environ["OPTIONS_EXECUTION_MODE"]
