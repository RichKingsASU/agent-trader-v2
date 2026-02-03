#!/usr/bin/env python3

import os
import sys
import uuid
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

# Add project root to Python path to allow imports from backend, scripts, etc.
# This is a common pattern for scripts in subdirectories.
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

# Ensure necessary backend modules are importable
# These imports assume the backend structure is available in the Python path
try:
    from backend.contracts.v2.trading import OptionOrderIntent, OptionRight, Side
    from backend.trading.execution.options_intent_gate import process_option_intent, IntentGateResult
    from backend.time.nyse_time import NYSE_TZ, utc_now # Assuming utc_now exists and is timezone-aware
    from backend.common.logging import log_event
except ImportError as e:
    print(f"ERROR: Could not import backend modules. Please ensure the project is set up correctly. Details: {e}", file=sys.stderr)
    sys.exit(1)

# --- Execution Policy Enforcement ---
# This is a simplified representation; actual enforcement might be more complex.
# It's crucial to ensure these checks are robust in a real system.

def enforce_execution_policy(script_name: str, argv: list[str]) -> bool:
    """
    Enforces execution policies for high-risk scripts.
    Returns True if policies are met, False otherwise.
    """
    policies_met = True
    reasons = []

    # 1. Paper-only hard lock
    if os.environ.get("TRADING_MODE") != "paper":
        policies_met = False
        reasons.append("TRADING_MODE must be 'paper'.")

    apca_url = os.environ.get("APCA_API_BASE_URL")
    if not apca_url:
        policies_met = False
        reasons.append("APCA_API_BASE_URL environment variable is not set.")
    else:
        # Normalize URL by stripping potential /v2 suffix
        normalized_url = apca_url[:-3] if apca_url.endswith("/v2") else apca_url
        if normalized_url != "https://paper-api.alpaca.markets":
            policies_met = False
            reasons.append(f"APCA_API_BASE_URL '{apca_url}' is invalid. Expected 'https://paper-api.alpaca.markets'.")

    # 2. Kill switch is instant
    if os.environ.get("EXECUTION_HALTED") == "1":
        policies_met = False
        reasons.append("EXECUTION_HALTED is set to '1'.")

    # 3. Explicit operator intent required
    if os.environ.get("EXECUTION_ENABLED") != "1":
        policies_met = False
        reasons.append("EXECUTION_ENABLED must be '1'.")
    if os.environ.get("EXEC_GUARD_UNLOCK") != "1":
        policies_met = False
        reasons.append("EXEC_GUARD_UNLOCK must be '1'.")
    if not os.environ.get("EXECUTION_CONFIRM_TOKEN"):
        policies_met = False
        reasons.append("EXECUTION_CONFIRM_TOKEN is not set.")
    
    # Note: The prompt mentions passing token via environment, not CLI args, for MUST_LOCK scripts.
    # This check assumes the token is expected in the environment.

    if not policies_met:
        print(f"Execution policy violation for script '{script_name}':", file=sys.stderr)
        for reason in reasons:
            print(f"- {reason}", file=sys.stderr)
        print("Execution aborted.", file=sys.stderr)
        return False
    
    return True

# --- Helper to build OptionOrderIntent ---
def build_example_option_intent() -> OptionOrderIntent:
    """
    Builds a sample OptionOrderIntent for SPY CALL ATM.
    Uses current NYSE time to determine nearest expiration and strike.
    """
    now_ny = utc_now().astimezone(NYSE_TZ)
    
    # Determine nearest expiration for 0DTE SPY CALL
    # For simplicity, let's target the next available trading day's expiration.
    # A real implementation would need a proper expiry calculation based on SPY's options schedule.
    # For now, assume next day is a trading day for simplicity.
    expiration_date = now_ny.date() + timedelta(days=1)
    
    # Get current underlying price for ATM strike
    # This is a placeholder; in a real script, this price would be fetched live.
    # Using a fixed value or environment variable if available.
    try:
        underlying_price = Decimal(os.environ.get("MOCK_UNDERLYING_PRICE", "450.50"))
    except InvalidOperation:
        underlying_price = Decimal("450.50")
    
    strike_price = float(underlying_price.quantize(Decimal("1"), rounding='ROUND_HALF_UP'))
    quantity = 1
    side = Side.BUY # Default to buy for example
    
    # Contract symbol format is complex and depends on exchange/broker conventions.
    # This is a placeholder. A real implementation would use actual contract symbol generation.
    # Example format: SPY260203C00450000 (SymbolYYMMDDRightSTRIKE00)
    contract_symbol = f"SPY{expiration_date.strftime('%y%m%d')}{OptionRight.CALL.value.upper()[0]}{int(strike_price*100):08}"

    return OptionOrderIntent(
        intent_id=uuid.uuid4(),
        strategy_id="submit_paper_script",
        symbol="SPY",
        side=side,
        order_type="market",
        quantity=quantity,
        expiration=expiration_date,
        strike=strike_price,
        right=OptionRight.CALL,
        options={
            "contract_symbol": contract_symbol,
            "underlying_price": float(underlying_price),
            "strategy": "submit_paper_script",
            "macro_event_active": False, # Example value
        }
    )

# --- Main Script Logic ---

def main():
    script_name = os.path.basename(__file__)
    
    # Enforce execution policies
    if not enforce_execution_policy(script_name, sys.argv):
        sys.exit(1)

    print(f"--- {script_name} ---")

    # Build the intent
    try:
        option_intent = build_example_option_intent()
        print(f"Built OptionOrderIntent: ID={option_intent.intent_id}, Symbol={option_intent.symbol}, Strike={option_intent.strike}, Side={option_intent.side}")
    except Exception as e:
        print(f"Error building OptionOrderIntent: {e}", file=sys.stderr)
        sys.exit(1)

    # Call the intent gate with paper mode enabled
    print("Processing intent via options intent gate with OPTIONS_EXECUTION_MODE='paper'...")
    # Temporarily set environment variable for the gate to pick up paper mode
    original_options_mode = os.environ.get("OPTIONS_EXECUTION_MODE")
    os.environ["OPTIONS_EXECUTION_MODE"] = "paper"

    try:
        gate_result = process_option_intent(option_intent)

        if gate_result.blocked:
            print(f"Intent BLOCKED by gate: {gate_result.reason}")
            sys.exit(1)
        else:
            if gate_result.execution_result and gate_result.execution_result.stored:
                # Assuming execution_result.stored contains the broker order ID and status
                order_info = gate_result.execution_result.stored
                broker_order_id = order_info.get("broker_order_id")
                status = order_info.get("status")
                error = order_info.get("error")

                if status == "submitted":
                    print(f"SUCCESS: Option intent submitted to paper broker.")
                    print(f"  Broker Order ID: {broker_order_id}")
                    print(f"  Status: {status}")
                else:
                    print(f"FAILURE: Option intent submission failed.")
                    print(f"  Status: {status}")
                    if error:
                        print(f"  Error: {error}")
                    sys.exit(1)
            else:
                print("FAILURE: Intent processed but no execution result or stored order found.")
                sys.exit(1)

    except Exception as e:
        print(f"An unexpected error occurred during intent processing: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        # Restore original environment variable or unset if it wasn't set
        if original_options_mode is None:
            if "OPTIONS_EXECUTION_MODE" in os.environ:
                del os.environ["OPTIONS_EXECUTION_MODE"]
        else:
            os.environ["OPTIONS_EXECUTION_MODE"] = original_options_mode

if __name__ == "__main__":
    # This block is for demonstrating the gate logic.
    # In a real test suite, these would be managed by the test runner.
    # Ensure environment variables are set for paper execution if testing this path.
    
    # Basic setup for running tests directly if needed
    # unittest.main()
    pass # Prevent unittest.main() from running when imported as a module