"""
Example usage of the Ticker Service for real-time market data.

This file demonstrates various ways to integrate and use the ticker service.
"""

import asyncio
import os
from firebase_admin import firestore

# Example 1: Run the service standalone
async def example_standalone():
    """Run the ticker service as a standalone application."""
    from functions.ticker_service import run_ticker_service
    
    # Set environment variables
    os.environ["APCA_API_KEY_ID"] = "your_key_id"
    os.environ["APCA_API_SECRET_KEY"] = "your_secret_key"
    os.environ["APCA_API_BASE_URL"] = "https://paper-api.alpaca.markets"
    os.environ["TICKER_SYMBOLS"] = "AAPL,NVDA,TSLA"
    
    # Run the service
    await run_ticker_service()


# Example 2: Use TickerService class directly with custom logic
async def example_custom_service():
    """Use the TickerService class with custom initialization."""
    from functions.ticker_service import TickerService
    
    # Initialize service
    service = TickerService()
    
    # Start streaming in the background
    stream_task = asyncio.create_task(service.start())
    
    # Do other work...
    await asyncio.sleep(60)  # Run for 60 seconds
    
    # Stop the service
    await service.stop()
    
    # Wait for stream task to complete
    try:
        await stream_task
    except Exception as e:
        print(f"Stream task completed with error: {e}")


# Example 3: Query Firestore for latest market data
def example_query_firestore():
    """Query Firestore to get the latest market data."""
    from functions.ticker_service import _get_firestore
    
    db = _get_firestore()
    
    # Get latest price for AAPL
    doc = db.collection('marketData').document('AAPL').get()
    if doc.exists:
        data = doc.to_dict()
        print(f"AAPL Latest Data:")
        print(f"  Timestamp: {data['timestamp']}")
        print(f"  Open: ${data['open']:.2f}")
        print(f"  High: ${data['high']:.2f}")
        print(f"  Low: ${data['low']:.2f}")
        print(f"  Close: ${data['close']:.2f}")
        print(f"  Volume: {data['volume']:,}")
    else:
        print("No data found for AAPL")


# Example 4: Subscribe to real-time Firestore updates
def example_realtime_subscription():
    """Subscribe to real-time updates from Firestore."""
    from functions.ticker_service import _get_firestore
    
    db = _get_firestore()
    
    def on_snapshot(doc_snapshot, changes, read_time):
        """Callback for Firestore document changes."""
        for change in changes:
            if change.type.name == 'MODIFIED':
                doc = change.document
                data = doc.to_dict()
                print(f"{data['symbol']}: ${data['close']:.2f} @ {data['timestamp']}")
    
    # Watch the marketData collection for changes
    collection_ref = db.collection('marketData')
    doc_watch = collection_ref.on_snapshot(on_snapshot)
    
    # Keep the subscription active
    try:
        input("Press Enter to stop watching...\n")
    finally:
        doc_watch.unsubscribe()


# Example 5: Get data for multiple symbols
def example_multi_symbol_query():
    """Query market data for multiple symbols."""
    from functions.ticker_service import _get_firestore
    
    db = _get_firestore()
    symbols = ["AAPL", "NVDA", "TSLA"]
    
    print("Latest prices:")
    for symbol in symbols:
        doc = db.collection('marketData').document(symbol).get()
        if doc.exists:
            data = doc.to_dict()
            print(f"  {symbol}: ${data['close']:.2f} (Vol: {data['volume']:,})")
        else:
            print(f"  {symbol}: No data available")


# Example 6: Integration with Firebase Cloud Functions
def example_cloud_function():
    """
    Example integration with Firebase Cloud Functions.
    
    This would be used in functions/main.py or similar.
    """
    # NOTE: This is pseudocode - actual implementation depends on your setup
    
    # from firebase_functions import https_fn
    # import asyncio
    # from functions.ticker_service import TickerService
    
    # @https_fn.on_request()
    # def start_ticker_stream(req: https_fn.Request) -> https_fn.Response:
    #     """HTTP endpoint to start the ticker stream."""
    #     service = TickerService()
    #     
    #     # In a real Cloud Function, you'd want to run this in a background task
    #     # or use a different trigger (like Pub/Sub or Cloud Scheduler)
    #     asyncio.run(service.start())
    #     
    #     return https_fn.Response("Ticker stream started")
    
    # @https_fn.on_request()
    # def get_latest_price(req: https_fn.Request) -> https_fn.Response:
    #     """HTTP endpoint to get latest price for a symbol."""
    #     from functions.ticker_service import _get_firestore
    #     
    #     symbol = req.args.get('symbol', 'AAPL')
    #     db = _get_firestore()
    #     
    #     doc = db.collection('marketData').document(symbol).get()
    #     if doc.exists:
    #         return https_fn.Response(doc.to_dict())
    #     else:
    #         return https_fn.Response(f"No data for {symbol}", status=404)
    
    pass


# Example 7: Custom bar handler with additional logic
async def example_custom_bar_handler():
    """Use the ticker service with custom bar processing logic."""
    from functions.ticker_service import TickerService
    
    class CustomTickerService(TickerService):
        """Extended ticker service with custom bar handling."""
        
        async def _handle_bar(self, bar):
            """Override bar handler to add custom logic."""
            # Call the parent handler to store in Firestore
            await super()._handle_bar(bar)
            
            # Add custom logic here
            symbol = bar.symbol if hasattr(bar, 'symbol') else bar.get('S')
            close_price = float(bar.close if hasattr(bar, 'close') else bar.get('c', 0))
            
            # Example: Alert if price crosses threshold
            if symbol == "AAPL" and close_price > 200:
                print(f"🚨 ALERT: AAPL crossed $200! Current: ${close_price:.2f}")
            
            # Example: Calculate and store derived metrics
            # You could calculate indicators, trigger strategies, etc.
    
    service = CustomTickerService()
    await service.start()


# Example 8: Monitoring and health checks
def example_health_check():
    """Check if the ticker service is providing fresh data."""
    from functions.ticker_service import _get_firestore
    from datetime import datetime, timezone, timedelta
    
    db = _get_firestore()
    symbols = ["AAPL", "NVDA", "TSLA"]
    
    print("Health check:")
    now = datetime.now(timezone.utc)
    stale_threshold = timedelta(minutes=5)
    
    for symbol in symbols:
        doc = db.collection('marketData').document(symbol).get()
        if doc.exists:
            data = doc.to_dict()
            timestamp = data['timestamp']
            age = now - timestamp
            
            status = "✅ FRESH" if age < stale_threshold else "⚠️ STALE"
            print(f"  {symbol}: {status} (last update: {age.total_seconds():.0f}s ago)")
        else:
            print(f"  {symbol}: ❌ NO DATA")


if __name__ == "__main__":
    """
    Run examples based on command line argument.
    
    Usage:
        python functions/ticker_service_example.py standalone
        python functions/ticker_service_example.py query
        python functions/ticker_service_example.py health
    """
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python ticker_service_example.py <example_name>")
        print("Examples: standalone, query, health, multi, realtime")
        sys.exit(1)
    
    example = sys.argv[1].lower()
    
    if example == "standalone":
        asyncio.run(example_standalone())
    elif example == "custom":
        asyncio.run(example_custom_service())
    elif example == "query":
        example_query_firestore()
    elif example == "realtime":
        example_realtime_subscription()
    elif example == "multi":
        example_multi_symbol_query()
    elif example == "health":
        example_health_check()
    elif example == "custom_handler":
        asyncio.run(example_custom_bar_handler())
    else:
        print(f"Unknown example: {example}")
        sys.exit(1)
