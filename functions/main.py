import os
import sys
import logging
from datetime import datetime, timezone
from decimal import Decimal, getcontext

# Standardize on alpaca-py
# Remove direct import of alpaca_trade_api
# from alpaca_trade_api import tradeapi
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest # Assuming GetOrdersRequest is used
from alpaca.data.live.stream import DataStream # For streaming data if needed
from alpaca.common.exceptions import APIError # For catching Alpaca API errors

# Assuming contracts and other utility modules are accessible
# from backend.contracts.v2.trading import ...
# from backend.common.logging import log_event # Assuming a logging utility

# --- Constants and Configuration ---
# This section should be adapted based on how these are actually configured in the project.
# For demonstration, assuming PAPER_TRADING_MODE and PAPER_APCA_API_BASE_URL are relevant.
PAPER_TRADING_MODE = "paper"
PAPER_APCA_API_BASE_URL = "https://paper-api.alpaca.markets"

# Environment variables for Alpaca API access and execution control
APCA_API_KEY_ID = os.environ.get("APCA_API_KEY_ID")
APCA_API_SECRET_KEY = os.environ.get("APCA_API_SECRET_KEY")
APCA_API_BASE_URL = os.environ.get("APCA_API_BASE_URL")
TRADING_MODE = os.environ.get("TRADING_MODE", "shadow") # Default to shadow
OPTIONS_EXECUTION_MODE = os.environ.get("OPTIONS_EXECUTION_MODE", "shadow") # Default to shadow

logger = logging.getLogger(__name__)

# --- Helper Functions for Safety Invariants (adapted for alpaca-py) ---

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
    return os.environ.get("EXECUTION_HALTED", "0") == "1"

def _check_operator_intent() -> bool:
    """Check if explicit operator intent is enabled and confirmed."""
    return (
        os.environ.get("EXECUTION_ENABLED", "0") == "1" and
        os.environ.get("EXEC_GUARD_UNLOCK", "0") == "1" and
        bool(os.environ.get("EXECUTION_CONFIRM_TOKEN")) # Basic check for token presence
    )

def _check_alpaca_credentials() -> bool:
    """Check if Alpaca API credentials are set."""
    return bool(APCA_API_KEY_ID) and bool(APCA_API_SECRET_KEY)

def _get_alpaca_trading_client() -> Optional[TradingClient]:
    """Construct and return Alpaca TradingClient in paper mode if all invariants are met."""
    if not _is_paper_mode_enabled_for_executor():
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
        # Use TradingClient from alpaca-py
        client = TradingClient(
            key_id=APCA_API_KEY_ID,
            secret_key=APCA_API_SECRET_KEY,
            base_url=corrected_url,
            # oauth=None, # No OAuth needed for API key auth
        )
        logger.info("Alpaca TradingClient constructed successfully in paper mode.")
        return client
    except Exception as e:
        logger.error(f"Failed to construct Alpaca TradingClient: {e}")
        return None

# --- Mock/Placeholder Definitions (for standalone testing/development) ---
# In a production environment, these would be properly imported.

def log_event(logger, event_name: str, severity: str, **kwargs):
    """Mock log_event function for demonstration."""
    log_data = {"event": event_name, "severity": severity, **kwargs}
    if severity == "ERROR":
        logger.error(f"{event_name}: {kwargs.get('error')}")
    elif severity == "WARNING":
        logger.warning(f"{event_name}: {kwargs.get('reason', '')}")
    else:
        logger.info(f"{event_name}: {kwargs}")

# --- Main Function Example ---
def main():
    """Example function to demonstrate client usage."""
    print("--- Main Function ---")
    
    # Example: Get orders (replace with actual logic)
    trading_client = _get_alpaca_trading_client()
    if trading_client:
        try:
            # Example of getting orders - adapt parameters as needed
            # orders = trading_client.get_orders(GetOrdersRequest(status='open', limit=10))
            # logger.info(f"Successfully retrieved {len(orders)} open orders.")
            logger.info("Alpaca client is ready. Example order fetching logic can be implemented here.")
        except APIError as e:
            logger.error(f"Alpaca API error: {e.message} (Code: {e.code}, Status: {e.status})")
        except Exception as e:
            logger.error(f"An unexpected error occurred: {e}")
    else:
        logger.error("Failed to get Alpaca client, cannot proceed with trading operations.")

if __name__ == "__main__":
    # Set up basic logging for standalone execution
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', stream=sys.stdout)
    
    # Mock environment variables for a quick test run (replace with actual values if needed)
    os.environ["TRADING_MODE"] = "paper"
    os.environ["APCA_API_KEY_ID"] = "MOCK_KEY_ID"
    os.environ["APCA_API_SECRET_KEY"] = "MOCK_SECRET_KEY"
    os.environ["APCA_API_BASE_URL"] = "https://paper-api.alpaca.markets"
    os.environ["EXECUTION_ENABLED"] = "1"
    os.environ["EXEC_GUARD_UNLOCK"] = "1"
    os.environ["EXECUTION_CONFIRM_TOKEN"] = "mock_token"
    os.environ["OPTIONS_EXECUTION_MODE"] = "paper"

    main()

    # Clean up environment variables after example run
    for var in ["TRADING_MODE", "APCA_API_KEY_ID", "APCA_API_SECRET_KEY", "APCA_API_BASE_URL", "EXECUTION_ENABLED", "EXEC_GUARD_UNLOCK", "EXECUTION_CONFIRM_TOKEN", "OPTIONS_EXECUTION_MODE"]:
        if var in os.environ:
            del os.environ[var]
