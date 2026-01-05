# Ticker Service - Real-Time Market Data Feed

## Overview

The Ticker Service provides real-time market data streaming from Alpaca's WebSocket API. It continuously streams minute bars for configured ticker symbols and stores them in Firestore for downstream consumption.

## Features

- **Real-time streaming**: Uses Alpaca WebSocket API for live minute bar data
- **Automatic retries**: Handles connection failures with exponential backoff
- **Firestore integration**: Upserts data to `marketData` collection keyed by ticker symbol
- **Configurable symbols**: Set target tickers via environment variables
- **Production-ready**: Includes logging, error handling, and graceful shutdown

## Architecture

```
Alpaca WebSocket API
        ↓ (minute bars)
  Ticker Service
        ↓ (upsert)
Firestore: marketData/{symbol}
```

### Data Model

Each ticker document in Firestore contains:

```json
{
  "symbol": "AAPL",
  "timestamp": "2025-12-30T14:30:00Z",
  "open": 195.42,
  "high": 195.88,
  "low": 195.35,
  "close": 195.67,
  "volume": 125000,
  "updatedAt": "<firestore_server_timestamp>"
}
```

## Configuration

### Required Environment Variables

- `ALPACA_KEY_ID`: Your Alpaca API key ID
- `ALPACA_SECRET_KEY`: Your Alpaca API secret key

### Optional Environment Variables

- `TICKER_SYMBOLS`: Comma-separated list of symbols to stream (default: `AAPL,NVDA,TSLA`)
- `APCA_API_BASE_URL`: Alpaca API base URL (default: `https://api.alpaca.markets`)
- `ALPACA_API_BASE_URL`: Alternative env var for API base URL

## Usage

### Standalone Execution

Run the service directly for testing:

```bash
export ALPACA_KEY_ID=your_key_id
export ALPACA_SECRET_KEY=your_secret_key
export TICKER_SYMBOLS=AAPL,NVDA,TSLA
python -m functions.ticker_service
```

### Using the Runner Script

For production deployment with automatic restarts:

```bash
# Ensure environment variables are set in .env.local
./scripts/run-ticker-service.sh
```

The runner script:
- Sources environment variables from `.env.local`
- Implements PID-based locking to prevent multiple instances
- Automatically restarts on failure
- Logs output to `logs/ticker_service.log`

### As a Cloud Function

The service can be integrated into Firebase Cloud Functions:

```python
from functions.ticker_service import run_ticker_service

@functions_framework.cloud_event
def start_ticker_stream(cloud_event):
    asyncio.run(run_ticker_service())
```

## Connection Management

The service implements robust connection handling:

1. **Initial Connection**: Establishes WebSocket connection to Alpaca
2. **Streaming**: Continuously receives and processes minute bars
3. **Retry Logic**: On connection failure:
   - Waits 5 seconds before first retry
   - Implements exponential backoff (max 60 seconds)
   - Attempts up to 5 retries before failing
4. **Graceful Shutdown**: Cleanly closes connections on service stop

## Error Handling

- **Missing Credentials**: Raises `ValueError` with clear error message
- **Bar Processing Errors**: Logs error but continues streaming
- **Connection Failures**: Automatically retries with backoff
- **Max Retries Exceeded**: Raises exception after 5 failed attempts

## Monitoring

### Logs

The service emits structured logs for monitoring:

```
2025-12-30T14:30:00 [INFO] Starting Ticker Service...
2025-12-30T14:30:00 [INFO] Monitoring symbols: AAPL, NVDA, TSLA
2025-12-30T14:30:01 [INFO] WebSocket connection established, streaming data...
2025-12-30T14:30:15 [INFO] Bar received: AAPL @ 2025-12-30T14:30:00 O:195.42 H:195.88 L:195.35 C:195.67 V:125000
2025-12-30T14:30:15 [INFO] Successfully upserted AAPL to Firestore
```

### Key Metrics to Monitor

- Connection uptime/downtime
- Bar processing rate per symbol
- Firestore write success rate
- Retry frequency and success rate

## Firestore Query Examples

### Get Latest Price for a Symbol

```python
doc = db.collection('marketData').document('AAPL').get()
if doc.exists:
    data = doc.to_dict()
    print(f"Latest AAPL price: ${data['close']}")
```

### Subscribe to Real-Time Updates

```python
def on_snapshot(doc_snapshot, changes, read_time):
    for change in changes:
        if change.type.name == 'MODIFIED':
            data = change.document.to_dict()
            print(f"{data['symbol']}: ${data['close']}")

# Watch for updates
db.collection('marketData').on_snapshot(on_snapshot)
```

## Troubleshooting

### Service Won't Start

1. Verify Alpaca credentials are set correctly
2. Check Firebase credentials are configured
3. Ensure alpaca-trade-api and firebase-admin are installed

### No Data in Firestore

1. Verify symbols are valid and supported by Alpaca
2. Check if market is open (minute bars only stream during market hours)
3. Review logs for error messages

### Frequent Reconnections

1. Check network connectivity
2. Verify Alpaca API key is not rate-limited
3. Review Alpaca service status

## Dependencies

- `alpaca-trade-api`: Alpaca WebSocket and REST API client
- `firebase-admin`: Firestore client library
- `firebase-functions` (optional): For Cloud Function deployment

## Security Notes

- Never commit API keys to version control
- Use Secret Manager for production deployments
- Rotate API keys regularly
- Monitor API usage to detect anomalies

## Future Enhancements

Potential improvements for the ticker service:

- [ ] Add support for quote streams in addition to bars
- [ ] Implement data validation before Firestore writes
- [ ] Add Pub/Sub notifications for price alerts
- [ ] Support multiple data feeds (SIP, IEX, OTC)
- [ ] Add metrics export to Cloud Monitoring
- [ ] Implement circuit breaker pattern for Firestore writes
- [ ] Add historical data backfill on startup
