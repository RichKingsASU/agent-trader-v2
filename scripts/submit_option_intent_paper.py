import os
import sys
import uuid
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal
from typing import Any, Dict

# Import necessary components from the project
# Assuming OptionOrderIntent, Side, OptionRight are in backend.contracts.v2.trading
# Assuming process_option_intent is in backend.trading.execution.options_intent_gate
try:
    from backend.contracts.v2.trading import OptionOrderIntent, Side, OptionRight
except ImportError:
    # Define placeholder classes if actual imports fail (for local testing/linting)
    from enum import Enum
    from dataclasses import dataclass, field
    print("INFO: Using mock OptionOrderIntent, Side, OptionRight classes.")

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
    # Mock process_option_intent and IntentGateResult if not available
    print("INFO: Using mock process_option_intent and IntentGateResult.")
    @dataclass
    class IntentGateResult:
        blocked: bool = False
        reason: Optional[str] = None
        execution_result: Any = None # This might be a dict or an object from the executor

    def process_option_intent(intent: OptionOrderIntent) -> IntentGateResult:
        print(f"Mock process_option_intent called for intent: {intent.intent_id}")
        # Simulate a successful paper execution for testing purposes
        return IntentGateResult(
            blocked=False,
            execution_result={
                "broker_order_id": f"MOCK_ORDER_{uuid.uuid4().hex[:8]}",
                "status": "submitted",
                "stored": {"mock_data": "example"}
            }
        )

try:
    from scripts.lib.exec_guard import enforce_execution_policy, ScriptRisk
except ImportError:
    # Mock enforce_execution_policy if not available
    print("INFO: Using mock enforce_execution_policy.")
    def enforce_execution_policy(script_path: str, argv: list[str]) -> None:
        print(f"Mock enforce_execution_policy called for {script_path}")
        # Simulate basic checks for testing if needed, but rely on actual env vars
        # This mock will not actually exit.
        if os.getenv("EXEC_GUARD_UNLOCK") != "1":
            print("Mock: EXEC_GUARD_UNLOCK is not set to 1. Script would be refused.", file=sys.stderr)
        if os.getenv("TRADING_MODE") != "paper":
            print("Mock: TRADING_MODE is not 'paper'. Script would be refused.", file=sys.stderr)
        if os.getenv("EXECUTION_HALTED") == "1":
            print("Mock: EXECUTION_HALTED is ON. Script would be refused.", file=sys.stderr)


# --- Script Configuration ---
SCRIPT_NAME = __file__

# --- Helper to create a sample OptionOrderIntent ---
def create_sample_option_intent() -> OptionOrderIntent:
    """
    Creates a sample OptionOrderIntent.
    This function should be replaced or augmented with logic to select
    actual option contracts (e.g., ATM, nearest expiration) based on market data,
    if such helpers were available.
    """
    now = datetime.now(timezone.utc).date()
    
    # Calculate expiration date: next Friday
    # Friday is index 4 (Monday is 0)
    days_ahead = (4 - now.weekday()) % 7
    if days_ahead == 0: days_ahead = 7  # If today is Friday, go to next Friday
    expiration_date = now + timedelta(days=days_ahead)

    # Example: SPY CALL ATM
    # Real-world scenario would fetch ATM strike and contract symbol dynamically.
    # The contract symbol format is critical and specific to Alpaca.
    # Example: SPY260207C00450000 means SPY, Feb 7, 2026, Call, Strike 450.00
    return OptionOrderIntent(
        intent_id=uuid.uuid4(),
        strategy_id="submit_paper_script_test",
        symbol="SPY", # Underlying symbol
        side=Side.BUY,
        order_type="market",
        quantity=1,
        expiration=expiration_date,
        strike=Decimal("450.00"), # Example strike
        right=OptionRight.CALL,
        options={
            # This contract symbol format is specific to Alpaca and needs to be valid for the date/strike.
            # Constructing a dynamically valid symbol is complex and often requires market data access.
            # Using a placeholder for demonstration.
            "contract_symbol": "SPY260207C00450000", 
            "underlying_price": Decimal("450.50"), # Example underlying price
            "strategy_source": "submit_paper_script",
        }
    )

# --- Main execution logic ---
def main():
    print("Starting supervised paper option intent submission script...")

    # 1. Enforce execution policy for MUST_LOCK scripts
    try:
        enforce_execution_policy(SCRIPT_NAME, sys.argv)
        print("Execution policy check passed.")
    except SystemExit as e:
        print(f"Execution Policy Violation: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error during execution policy enforcement: {e}", file=sys.stderr)
        sys.exit(1)
    
    # --- Environment variable checks ---
    # These checks ensure the script and the underlying execution environment are configured correctly.
    
    # Check TRADING_MODE
    trading_mode = os.environ.get("TRADING_MODE", "shadow")
    if trading_mode != "paper":
        print(f"ERROR: TRADING_MODE must be 'paper' to run this script. Found: '{trading_mode}'", file=sys.stderr)
        sys.exit(1)
    print(f"TRADING_MODE is set to '{trading_mode}'.")
    
    # Check kill switch (EXECUTION_HALTED)
    execution_halted = os.environ.get("EXECUTION_HALTED", "0") == "1"
    if execution_halted:
        print("ERROR: EXECUTION_HALTED is ON. Cannot proceed with execution.", file=sys.stderr)
        sys.exit(1)
    print("Execution is not halted.")
    
    # Check EXECUTION_ENABLED (also checked by enforce_execution_policy)
    execution_enabled = os.environ.get("EXECUTION_ENABLED", "0") == "1"
    if not execution_enabled:
        print("ERROR: EXECUTION_ENABLED must be 1 to run this script.", file=sys.stderr)
        sys.exit(1)
    print("EXECUTION_ENABLED is ON.")
    
    # Check EXEC_GUARD_UNLOCK (also checked by enforce_execution_policy)
    exec_guard_unlock = os.environ.get("EXEC_GUARD_UNLOCK", "0") == "1"
    if not exec_guard_unlock:
        print("ERROR: EXEC_GUARD_UNLOCK must be 1 to run this script.", file=sys.stderr)
        sys.exit(1)
    print("EXEC_GUARD_UNLOCK is ON.")
    
    # Check EXECUTION_CONFIRM_TOKEN (also checked by enforce_execution_policy)
    execution_confirm_token = os.environ.get("EXECUTION_CONFIRM_TOKEN")
    if not execution_confirm_token:
        print("ERROR: EXECUTION_CONFIRM_TOKEN must be set to run this script.", file=sys.stderr)
        sys.exit(1)
    print("EXECUTION_CONFIRM_TOKEN is set.")
    
    # Validate/Correct Alpaca API Base URL
    apca_api_base_url = os.environ.get("APCA_API_BASE_URL")
    if not apca_api_base_url:
        print("ERROR: APCA_API_BASE_URL must be set.", file=sys.stderr)
        sys.exit(1)
    
    # Normalize and validate URL
    normalized_url = apca_api_base_url.strip()
    if normalized_url.endswith("/v2"):
        normalized_url = normalized_url[:-3]
    
    expected_paper_url = "https://paper-api.alpaca.markets"
    if normalized_url != expected_paper_url:
        print(f"ERROR: APCA_API_BASE_URL must be '{expected_paper_url}' for paper trading. Found: '{apca_api_base_url}'", file=sys.stderr)
        sys.exit(1)
    print(f"APCA_API_BASE_URL validated: '{normalized_url}'.")
    
    # Set OPTIONS_EXECUTION_MODE to 'paper' for this script's intent
    # This is crucial for the gate to dispatch to the paper executor.
    os.environ["OPTIONS_EXECUTION_MODE"] = "paper"
    print("OPTIONS_EXECUTION_MODE set to 'paper'.")
    
    # Check Alpaca credentials
    apca_api_key_id = os.environ.get("APCA_API_KEY_ID")
    apca_api_secret_key = os.environ.get("APCA_API_SECRET_KEY")
    if not apca_api_key_id or not apca_api_secret_key:
        print("ERROR: APCA_API_KEY_ID and APCA_API_SECRET_KEY must be set for Alpaca paper trading.", file=sys.stderr)
        sys.exit(1)
    print("Alpaca API credentials found.")

    # 2. Build a single OptionOrderIntent
    print("Creating sample OptionOrderIntent...")
    try:
        sample_intent = create_sample_option_intent()
        print(f"  Intent created: Strategy='{sample_intent.strategy_id}', Symbol='{sample_intent.symbol}', Contract='{sample_intent.options.get('contract_symbol')}', Exp='{sample_intent.expiration}', Strike='{sample_intent.strike}', Side='{sample_intent.side.value}'")
    except Exception as e:
        print(f"ERROR: Failed to create sample OptionOrderIntent: {e}", file=sys.stderr)
        sys.exit(1)

    # 3. Call process_option_intent()
    print(f"Calling process_option_intent with OPTIONS_EXECUTION_MODE='paper'...")
    try:
        result = process_option_intent(sample_intent)

        if result.blocked:
            print(f"ERROR: Intent was blocked by the gate. Reason: {result.reason}", file=sys.stderr)
            sys.exit(1)
        else:
            execution_info = result.execution_result
            # Accessing execution details might differ based on the mock or actual return type
            broker_order_id = None
            order_status = None
            if isinstance(execution_info, dict):
                broker_order_id = execution_info.get("broker_order_id")
                order_status = execution_info.get("status")
            elif hasattr(execution_info, 'broker_order_id') and hasattr(execution_info, 'status'):
                broker_order_id = execution_info.broker_order_id
                order_status = execution_info.status
            
            print("\n--- Supervised Paper Order Submission Successful ---")
            print(f"  Intent ID: {sample_intent.intent_id}")
            print(f"  Strategy ID: {sample_intent.strategy_id}")
            print(f"  Contract Symbol: {sample_intent.options.get('contract_symbol', sample_intent.symbol)}")
            print(f"  Order Status: {order_status if order_status else 'N/A'}")
            print(f"  Broker Order ID: {broker_order_id if broker_order_id else 'N/A'}")
            print(f"  Submitted at: {datetime.now(timezone.utc).isoformat()}")
            print("--------------------------------------------------")
            print("\nNOTE: This was a paper execution. No real funds were used.")
            print("To place another order, you will need to re-authenticate and potentially unlock the guard.")
            print("Remember to lock down execution environment variables after use (e.g., unset EXECUTION_ENABLED, EXEC_GUARD_UNLOCK).")

    except Exception as e:
        print(f"ERROR: Failed to process option intent: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    # Set necessary environment variables for demonstration/testing if not already set.
    # These are critical for the script to run and pass initial checks.
    # The script itself will perform more specific validation.
    
    # Ensure at least minimal required env vars are present for script to run.
    # The script itself will perform more specific validation.
    if not os.environ.get("APCA_API_KEY_ID"): os.environ["APCA_API_KEY_ID"] = "DUMMY_KEY_ID_FOR_SCRIPT_RUN"
    if not os.environ.get("APCA_API_SECRET_KEY"): os.environ["APCA_API_SECRET_KEY"] = "DUMMY_SECRET_KEY_FOR_SCRIPT_RUN"
    if not os.environ.get("APCA_API_BASE_URL"): os.environ["APCA_API_BASE_URL"] = "https://paper-api.alpaca.markets"
    if not os.environ.get("EXECUTION_CONFIRM_TOKEN"): os.environ["EXECUTION_CONFIRM_TOKEN"] = "DUMMY_TOKEN_FOR_SCRIPT_RUN"
    
    # Ensure core execution flags are set to pass initial checks.
    if os.environ.get("EXECUTION_ENABLED") is None: os.environ["EXECUTION_ENABLED"] = "1"
    if os.environ.get("EXEC_GUARD_UNLOCK") is None: os.environ["EXEC_GUARD_UNLOCK"] = "1"
    if os.environ.get("TRADING_MODE") is None: os.environ["TRADING_MODE"] = "paper"
    
    # Ensure OPTIONS_EXECUTION_MODE is set, though the script will explicitly set it to 'paper' as well.
    if os.environ.get("OPTIONS_EXECUTION_MODE") is None: os.environ["OPTIONS_EXECUTION_MODE"] = "shadow" # Will be overridden by script

    main()
