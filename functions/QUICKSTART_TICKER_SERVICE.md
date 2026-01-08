# Ticker Service - Quick Start Guide

Get the real-time market data feed running in under 5 minutes.

## Prerequisites

- Alpaca API credentials ([Get them here](https://alpaca.markets/))
- Firebase project with Firestore enabled
- Python 3.8+ with dependencies installed

## Step 1: Install Dependencies

The required packages are already in `functions/requirements.txt`:
```
alpaca-trade-api
firebase-admin
firebase-functions
```

Install them:
```bash
pip install -r functions/requirements.txt
```

## Step 2: Configure Environment

Create a `.env.local` file in the project root:

```bash
# Required: Alpaca API credentials
export APCA_API_KEY_ID="YOUR_ALPACA_KEY_ID_HERE"
export APCA_API_SECRET_KEY="YOUR_ALPACA_SECRET_KEY_HERE"

# Optional: Customize symbols (default: AAPL,NVDA,TSLA)
export TICKER_SYMBOLS="AAPL,NVDA,TSLA,SPY,QQQ"

# Optional: Use paper trading endpoint
export APCA_API_BASE_URL="https://paper-api.alpaca.markets"
```

Replace `YOUR_ALPACA_KEY_ID_HERE` and `YOUR_ALPACA_SECRET_KEY_HERE` with your actual Alpaca credentials.

## Step 3: Run the Service

### Option A: Using the Runner Script (Recommended for Production)

```bash
./scripts/run-ticker-service.sh
```

This will:
- Source environment variables from `.env.local`
- Start the ticker service
- Auto-restart on failures
- Log to `logs/ticker_service.log`

### Option B: Direct Execution (Good for Development)

```bash
source .env.local
python -m functions.ticker_service
```

Press `Ctrl+C` to stop.

## Step 4: Verify It's Working

### Check the Logs

```bash
tail -f logs/ticker_service.log
```

You should see:
```
[INFO] Starting Ticker Service...
[INFO] Monitoring symbols: AAPL, NVDA, TSLA
[INFO] WebSocket connection established, streaming data...
[INFO] Bar received: AAPL @ 2025-12-30T14:30:00 O:195.42 H:195.88 L:195.35 C:195.67 V:125000
[INFO] Successfully upserted AAPL to Firestore
```

### Query Firestore

Run the example query:
```bash
python functions/ticker_service_example.py query
```

Output:
```
AAPL Latest Data:
  Timestamp: 2025-12-30 14:30:00+00:00
  Open: $195.42
  High: $195.88
  Low: $195.35
  Close: $195.67
  Volume: 125,000
```

### Check Firestore Console

1. Go to [Firebase Console](https://console.firebase.google.com/)
2. Select your project
3. Navigate to Firestore Database
4. Look for the `marketData` collection
5. You should see documents for AAPL, NVDA, TSLA with live data

## Step 5: Monitor Health

Check data freshness:
```bash
python functions/ticker_service_example.py health
```

Output:
```
Health check:
  AAPL: ✅ FRESH (last update: 15s ago)
  NVDA: ✅ FRESH (last update: 12s ago)
  TSLA: ✅ FRESH (last update: 8s ago)
```

## Troubleshooting

### "Missing Alpaca credentials" Error

**Problem**: Environment variables not set correctly.

**Solution**:
```bash
# Verify variables are set
echo $APCA_API_KEY_ID
echo $APCA_API_SECRET_KEY

# If empty, source .env.local
source .env.local
```

### No Data in Firestore

**Problem**: Market is closed or symbols are invalid.

**Solution**:
- Check market hours (9:30 AM - 4:00 PM ET, Mon-Fri)
- Verify symbols are valid: `AAPL`, `NVDA`, `TSLA` (uppercase)
- Check logs for error messages

### Connection Keeps Dropping

**Problem**: Network issues or API rate limits.

**Solution**:
- Check internet connection
- Verify Alpaca API key is valid and not rate-limited
- Review Alpaca service status: https://status.alpaca.markets/

### Service Won't Start

**Problem**: Port conflict or missing dependencies.

**Solution**:
```bash
# Check if service is already running
ps aux | grep ticker_service

# Kill existing instance if found
pkill -f ticker_service

# Reinstall dependencies
pip install -r functions/requirements.txt --force-reinstall
```

## Common Use Cases

### Use Case 1: Monitor Different Symbols

```bash
export TICKER_SYMBOLS="SPY,QQQ,IWM,DIA"
./scripts/run-ticker-service.sh
```

### Use Case 2: Run During Market Hours Only

Create a cron job:
```bash
# Edit crontab
crontab -e

# Add (runs 9:30 AM - 4:00 PM ET, Mon-Fri)
30 9 * * 1-5 /path/to/scripts/run-ticker-service.sh
0 16 * * 1-5 pkill -f ticker_service
```

### Use Case 3: Subscribe to Real-Time Updates

```python
from functions.ticker_service_example import example_realtime_subscription
example_realtime_subscription()
```

### Use Case 4: Get Historical Context

The service only stores the latest bar per symbol. For history:
1. Use the `ingest_market_data.py` script for historical data
2. Store historical bars in a separate collection or database
3. Query both for complete picture

## Next Steps

Once you have the basic service running:

1. **Set up monitoring**: Configure alerts for connection failures
2. **Integrate with strategies**: Use the market data in your trading algorithms
3. **Add custom logic**: Extend `TickerService` class with custom bar handlers
4. **Deploy to Cloud**: Use Cloud Functions for managed deployment

## Additional Examples

See `functions/ticker_service_example.py` for more:

```bash
# Run different examples
python functions/ticker_service_example.py standalone
python functions/ticker_service_example.py query
python functions/ticker_service_example.py multi
python functions/ticker_service_example.py realtime
python functions/ticker_service_example.py health
```

## Documentation

- **Full Documentation**: `functions/README_TICKER_SERVICE.md`
- **Implementation Details**: `functions/IMPLEMENTATION_SUMMARY.md`
- **Source Code**: `functions/ticker_service.py`
- **Tests**: `tests/test_ticker_service.py`

## Getting Help

1. Check the logs: `tail -f logs/ticker_service.log`
2. Review the FAQ in `functions/README_TICKER_SERVICE.md`
3. Run health check: `python functions/ticker_service_example.py health`
4. Verify credentials are correct

## Production Checklist

Before deploying to production:

- [ ] Use Secret Manager for API keys (not `.env.local`)
- [ ] Set up Cloud Monitoring alerts
- [ ] Configure Firestore security rules
- [ ] Enable Firestore backup/restore
- [ ] Set up log aggregation
- [ ] Test failover scenarios
- [ ] Document runbook for incidents
- [ ] Schedule regular key rotation

## Support

For issues specific to:
- **Alpaca API**: Check [Alpaca Docs](https://alpaca.markets/docs/)
- **Firestore**: See [Firebase Docs](https://firebase.google.com/docs/firestore)
- **This Service**: Review the implementation files and tests

---

**You're all set!** The ticker service is now streaming real-time market data to Firestore. 🚀
