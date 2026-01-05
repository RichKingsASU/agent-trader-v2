import asyncio
import subprocess
from datetime import date
import argparse

from .config import config
from .models import fetch_recent_bars, fetch_recent_options_flow
from .risk import (
    get_or_create_strategy_definition,
    get_or_create_today_state,
    can_place_trade,
    record_trade,
    log_decision,
)
from .strategies.naive_flow_trend import make_decision

async def run_strategy(execute: bool):
    """
    Main function to run the strategy engine.
    """
    strategy_id = await get_or_create_strategy_definition(config.STRATEGY_NAME)
    today = date.today()
    
    print(f"Running strategy '{config.STRATEGY_NAME}' for {today}...")

    for symbol in config.STRATEGY_SYMBOLS:
        print(f"Processing symbol: {symbol}")

        bars = await fetch_recent_bars(symbol, config.STRATEGY_BAR_LOOKBACK_MINUTES)
        flow_events = await fetch_recent_options_flow(symbol, config.STRATEGY_FLOW_LOOKBACK_MINUTES)

        decision = make_decision(bars, flow_events)
        action = decision.get("action")

        if action == "flat":
            await log_decision(strategy_id, symbol, "flat", decision["reason"], decision["signal_payload"], False)
            print(f"  Decision: flat. Reason: {decision['reason']}")
            continue

        # Calculate notional
        last_price = bars[0].close if bars else 0
        notional = last_price * decision.get("size", 0)

        # Risk check
        if not await can_place_trade(strategy_id, today, notional):
            reason = "Risk limit exceeded."
            await log_decision(strategy_id, symbol, action, reason, decision["signal_payload"], False)
            print(f"  Decision: {action}, but trade blocked. Reason: {reason}")
            continue
            
        print(f"  Decision: {action}. Reason: {decision['reason']}")

        if execute:
            print(f"  Executing {action} order for 1 {symbol}...")
            # Call the existing paper trade script
            process = subprocess.run(
                [
                    "python",
                    "backend/streams/manual_paper_trade.py",
                    symbol,
                    action,
                    str(decision.get("size", 1)),
                ],
                capture_output=True,
                text=True,
            )
            print(f"   manual_paper_trade.py stdout: {process.stdout}")
            print(f"   manual_paper_trade.py stderr: {process.stderr}")

            # Record the trade
            await record_trade(strategy_id, today, notional)
            await log_decision(
                strategy_id,
                symbol,
                action,
                decision["reason"],
                decision["signal_payload"],
                True,
            )
        else:
            print("  Dry run mode, no trade executed.")
            await log_decision(
                strategy_id,
                symbol,
                action,
                "Dry run mode.",
                decision["signal_payload"],
                False,
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Actually place paper trades.")
    args = parser.parse_args()

    asyncio.run(run_strategy(args.execute))