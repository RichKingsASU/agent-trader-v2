import asyncio
import os
import json
import random
import signal
from datetime import datetime, timezone
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
    stop_event = asyncio.Event()

    # Best-effort: handle SIGINT/SIGTERM for clean shutdown.
    loop = asyncio.get_running_loop()

    def _handle_signal(signum: int, _frame=None) -> None:  # type: ignore[no-untyped-def]
        try:
            print(f"[mock_options_feed] signal_received signum={int(signum)}")
        except Exception:
            pass
        stop_event.set()

    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(s, _handle_signal, int(s), None)
        except NotImplementedError:
            try:
                signal.signal(s, _handle_signal)
            except Exception:
                pass

    while not stop_event.is_set():
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
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass
        
        # Wait for a second before the next batch of publications
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            pass

if __name__ == '__main__':
    print("Starting volatile options feed publisher...")
    try:
        asyncio.run(publish_volatile_options_feed())
    except KeyboardInterrupt:
        print("\nPublisher stopped.")
