import asyncio
import os
import json
import random
from datetime import datetime, timezone
from dotenv import load_dotenv
import nats

from backend.common.nats.subjects import market_subject
from backend.common.schemas.codec import encode_message
from backend.common.schemas.models import MarketEventV1

# --- Configuration ---
# Load environment variables from a .env file located in the parent 'backend' directory
dotenv_path = os.path.join(os.path.dirname(__file__), '..', 'backend', '.env')
load_dotenv(dotenv_path=dotenv_path)

NATS_URL = os.getenv("NATS_URL", "nats://localhost:4222")
TENANT_ID = (os.getenv("TENANT_ID") or "local").strip() or "local"
SYMBOLS = ["SPY", "IWM", "QQQ"]
BASE_PREMIUMS = {"SPY": 2.50, "IWM": 1.80, "QQQ": 3.10}

async def publish_volatile_options_feed():
    """
    Connects to NATS and streams mock options data with injected volatility.
    The price drops by 15% every 10th iteration and spikes by 25% every 15th.
    """
    print(f"Connecting to NATS server at {NATS_URL}...")
    try:
        nc = await nats.connect(NATS_URL)
        js = nc.jetstream()
        print("Successfully connected. Publishing tenant-scoped market subjects.")
    except Exception as e:
        print(f"Error connecting to NATS: {e}")
        return

    iteration_counter = 0
    premiums = BASE_PREMIUMS.copy()

    while True:
        iteration_counter += 1
        
        for symbol in SYMBOLS:
            premium = premiums[symbol]
            
            # --- Injected Volatility Logic ---
            if iteration_counter % 15 == 0:  # Every 15th iteration, spike price
                premium *= 1.25
                print(f"*** VOLATILITY TRIGGER (TAKE-PROFIT): {symbol} premium spiked to {premium:.2f} ***")
            elif iteration_counter % 10 == 0:  # Every 10th iteration, drop price
                premium *= 0.85
                print(f"*** VOLATILITY TRIGGER (STOP-LOSS): {symbol} premium dropped to {premium:.2f} ***")
            else:
                # Apply random noise for other iterations
                noise = random.uniform(-0.05, 0.05)
                premium += noise
                premium = max(0.01, premium) # Ensure premium doesn't go below zero
            
            # Update the current premium for the next iteration
            premiums[symbol] = premium

            # --- Construct and Publish Message ---
            message = {
                "symbol": symbol,
                "premium": round(premium, 2),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "iteration": iteration_counter,
                "source": "mock_volatile_feed"
            }
            
            try:
                evt = MarketEventV1(
                    tenant_id=TENANT_ID,
                    symbol=symbol,
                    source="mock-options-feed",
                    data=message,
                )
                await js.publish(market_subject(TENANT_ID, symbol), encode_message(evt))
                print(f"Published: {message}")
            except Exception as e:
                print(f"Error publishing to NATS: {e}")
                await asyncio.sleep(5) # Wait before retrying
        
        # Wait for a second before the next batch of publications
        await asyncio.sleep(1)

if __name__ == '__main__':
    print("Starting volatile options feed publisher...")
    try:
        asyncio.run(publish_volatile_options_feed())
    except KeyboardInterrupt:
        print("\nPublisher stopped.")
