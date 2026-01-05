# Congressional Alpha Tracker - Quick Start Guide

## 🚀 Getting Started in 5 Minutes

This guide will help you get the Congressional Alpha Tracker strategy running locally in under 5 minutes.

## Prerequisites

- Python 3.8+ installed
- Docker (for NATS)
- Basic command line knowledge

## Step 1: Start NATS (Message Broker)

Open a terminal and run:

```bash
docker run -p 4222:4222 nats:latest
```

Keep this terminal open. You should see:
```
[1] 2024/12/30 10:00:00.000000 [INF] Starting nats-server
[1] 2024/12/30 10:00:00.000000 [INF] Listening for client connections on 0.0.0.0:4222
```

## Step 2: Run the Ingestion Service

Open a **new terminal** and run:

```bash
cd /workspace
./scripts/run_congressional_ingest.sh local
```

You should see:
```
🚀 Starting Congressional Disclosure Ingestion Service
Environment: local
...
📊 Congressional Trade: Nancy Pelosi purchase NVDA ($50,001-$100,000)
📊 Congressional Trade: Tommy Tuberville purchase MSFT ($100,001-$250,000)
📊 Congressional Trade: Josh Gottheimer purchase AAPL ($15,001-$50,000)
Published 3 new congressional trades
```

**Note**: Since you don't have a Quiver API key, it will use mock data. This is perfect for testing!

## Step 3: Test the Strategy

Open a **new terminal** and run:

```bash
cd /workspace
python3 -m backend.strategy_runner.runner \
  --strategy-path backend/strategy_runner/examples/congressional_alpha/strategy.py \
  --events-file backend/strategy_runner/examples/congressional_alpha/events.ndjson
```

You should see order intents generated for qualifying trades:

```json
{
  "protocol": "v1",
  "type": "order_intent",
  "intent_id": "congress_a1b2c3d4",
  "symbol": "NVDA",
  "side": "buy",
  "order_type": "market",
  "metadata": {
    "politician": "Nancy Pelosi",
    "confidence": 0.82,
    "reasoning": "Copying Nancy Pelosi's purchase of NVDA. Confidence: 82%..."
  }
}
```

## Step 4: Run Tests

Verify everything works:

```bash
cd /workspace
python3 -m pytest tests/test_congressional_alpha_strategy.py -v
```

Expected output: **✅ 23 passed**

## 🎉 Success!

You now have the Congressional Alpha Tracker running locally!

## What's Happening?

1. **NATS** - Message broker that connects components
2. **Ingestion Service** - Fetches congressional trades and publishes them
3. **Strategy** - Analyzes trades and generates copy-trade signals
4. **Tests** - Verify all logic works correctly

## Next Steps

### Add Real Data (Optional)

Get a free API key from [Quiver Quantitative](https://www.quiverquant.com/) and set:

```bash
export QUIVER_API_KEY="your_api_key_here"
./scripts/run_congressional_ingest.sh local
```

### Modify Tracked Politicians

Edit `backend/strategy_runner/examples/congressional_alpha/strategy.py`:

```python
POLICY_WHALES = {
    "Your Favorite Politician": {
        "weight_multiplier": 1.4,
        "min_confidence": 0.7,
    },
}
```

### Adjust Position Sizes

Edit constants in `strategy.py`:

```python
MIN_TRANSACTION_SIZE = 15000.0  # Minimum trade to copy
MAX_POSITION_SIZE_PCT = 0.05    # Max 5% per position
```

### Deploy to Production

See the full deployment guide in [`CONGRESSIONAL_ALPHA_STRATEGY.md`](./CONGRESSIONAL_ALPHA_STRATEGY.md).

## Troubleshooting

### "Cannot reach NATS"
- Make sure Docker is running
- Check if port 4222 is available: `lsof -i :4222`
- Restart NATS: `docker restart <container_id>`

### "No module named pytest"
```bash
pip3 install pytest
```

### "No signals generated"
- Check if transactions meet minimum size ($15k)
- Verify politician is in POLICY_WHALES list
- Look at ingestion logs for API errors

## Learn More

- 📖 [Full Documentation](./CONGRESSIONAL_ALPHA_STRATEGY.md)
- 📄 [Strategy README](../backend/strategy_runner/examples/congressional_alpha/README.md)
- 🧪 [Test Suite](../tests/test_congressional_alpha_strategy.py)

## Support

Having issues? Check:
1. All three terminals are running (NATS, ingestion, strategy)
2. No port conflicts (4222 for NATS)
3. Python 3.8+ is installed
4. You're in the `/workspace` directory

---

**Built with ❤️ by the AgentTrader Team**
