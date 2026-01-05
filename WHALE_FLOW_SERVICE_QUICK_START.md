# Whale Flow Service - Quick Start Guide

## 5-Minute Integration

This guide gets you up and running with the WhaleFlowService in 5 minutes.

## Prerequisites

✅ Firebase/Firestore configured  
✅ Google Application Default Credentials set  
✅ Python 3.8+  

## Step 1: Import the Service (30 seconds)

```python
from backend.services.whale_flow import WhaleFlowService, get_recent_conviction
from decimal import Decimal
```

## Step 2: Ingest Your First Flow (1 minute)

```python
# Create service instance
service = WhaleFlowService()

# Sample flow data from your provider
flow_data = {
    "timestamp": "2025-12-30T12:00:00Z",
    "underlying_symbol": "SPY",
    "option_symbol": "SPY251219C00580000",
    "side": "buy",
    "size": 100,
    "premium": 10000.50,
    "strike_price": 580.00,
    "expiration_date": "2025-12-19",
    "option_type": "call",
    "trade_price": 4.00,
    "bid_price": 3.90,
    "ask_price": 4.10,
    "spot_price": 575.00,
    "implied_volatility": 0.18,
    "open_interest": 1000,
    "volume": 1500,
}

# Ingest for a user
doc_id = service.ingest_flow(
    uid="user123",
    flow_data=flow_data,
    source="my_provider"
)

print(f"✅ Ingested flow: {doc_id}")
```

## Step 3: Query Recent Conviction (30 seconds)

```python
# Check recent whale activity for AAPL
conviction = get_recent_conviction(
    uid="user123",
    ticker="AAPL",
    lookback_minutes=30
)

# Check results
if conviction['has_activity']:
    print(f"📊 Found {conviction['total_flows']} recent flows")
    print(f"🎯 Avg conviction: {conviction['avg_conviction']}")
    print(f"💰 Total premium: ${conviction['total_premium']}")
    print(f"📈 Sentiment: {conviction['dominant_sentiment']}")
else:
    print("No recent activity")
```

## Step 4: Use in Maestro Strategy (2 minutes)

```python
class MyStrategy:
    """Example strategy with whale flow validation."""
    
    def should_enter_trade(self, ticker: str, direction: str) -> tuple[bool, str]:
        """Validate trade against recent whale activity."""
        
        # Check whale flow
        conviction = get_recent_conviction(self.uid, ticker, lookback_minutes=30)
        
        # No activity = proceed with base strategy
        if not conviction['has_activity']:
            return True, "No whale signal"
        
        # High conviction + aligned sentiment = approve
        if conviction['avg_conviction'] > Decimal("0.7"):
            if direction == "LONG" and conviction['dominant_sentiment'] == "BULLISH":
                return True, f"✅ Whale activity aligned: {conviction['total_flows']} bullish flows"
            elif direction == "SHORT" and conviction['dominant_sentiment'] == "BEARISH":
                return True, f"✅ Whale activity aligned: {conviction['total_flows']} bearish flows"
            else:
                return False, f"⚠️ Whale activity conflicts: {conviction['dominant_sentiment']}"
        
        # Low conviction = proceed
        return True, "Weak whale signal"
```

## Step 5: Batch Ingestion (1 minute)

For better performance, ingest multiple flows at once:

```python
flows = [flow1, flow2, flow3]  # List of flow dictionaries

doc_ids = service.ingest_batch(
    uid="user123",
    flows=flows,
    source="my_provider"
)

print(f"✅ Ingested {len(doc_ids)} flows")
```

## That's It! 🎉

You're now ingesting whale flow data and validating trades.

## Common Use Cases

### Use Case 1: Real-time Stream Ingestion

```python
from backend.services.whale_flow import WhaleFlowService

service = WhaleFlowService()

async def on_websocket_message(message):
    """Handle incoming options flow from websocket."""
    flow = parse_message(message)
    
    # Ingest for all subscribed users
    for uid in get_premium_users():
        service.ingest_flow(uid, flow, source="websocket_stream")
```

### Use Case 2: Alert on High Conviction

```python
from backend.services.whale_flow import WhaleFlowService
from decimal import Decimal

service = WhaleFlowService()

def process_and_alert(uid: str, flow_data: dict):
    """Process flow and alert if high conviction."""
    
    # Map to schema (includes conviction calculation)
    mapped = service.map_flow_to_schema(uid, flow_data)
    
    conviction = Decimal(mapped['conviction_score'])
    
    # Alert on high conviction
    if conviction > Decimal("0.85"):
        send_push_notification(
            uid=uid,
            title=f"🐋 High Conviction: {mapped['underlying_symbol']}",
            body=f"{mapped['flow_type']} - ${mapped['premium']}"
        )
    
    # Ingest
    service.ingest_flow(uid, flow_data)
```

### Use Case 3: Pre-Trade Validation

```python
from backend.services.whale_flow import get_recent_conviction
from decimal import Decimal

def validate_trade(uid: str, ticker: str, direction: str, size: int) -> dict:
    """Validate trade before execution."""
    
    conviction = get_recent_conviction(uid, ticker, lookback_minutes=30)
    
    if not conviction['has_activity']:
        return {
            "approved": True,
            "reason": "No recent whale activity",
            "confidence": 0.5
        }
    
    # Check alignment
    is_aligned = (
        (direction == "LONG" and conviction['dominant_sentiment'] == "BULLISH") or
        (direction == "SHORT" and conviction['dominant_sentiment'] == "BEARISH")
    )
    
    if is_aligned and conviction['avg_conviction'] > Decimal("0.7"):
        return {
            "approved": True,
            "reason": f"Strong {conviction['dominant_sentiment']} whale activity",
            "confidence": float(conviction['avg_conviction']),
            "whale_flows": conviction['total_flows'],
            "whale_premium": float(conviction['total_premium'])
        }
    elif not is_aligned and conviction['avg_conviction'] > Decimal("0.7"):
        return {
            "approved": False,
            "reason": f"Conflicting whale activity: {conviction['dominant_sentiment']}",
            "confidence": float(conviction['avg_conviction']),
            "whale_flows": conviction['total_flows']
        }
    else:
        return {
            "approved": True,
            "reason": "Weak whale signal",
            "confidence": 0.6
        }
```

## API Quick Reference

### Ingestion

```python
# Single flow
service.ingest_flow(uid, flow_data, source="provider")

# Batch (more efficient)
service.ingest_batch(uid, flows, source="provider")

# Map without ingesting
mapped = service.map_flow_to_schema(uid, flow_data)
```

### Queries

```python
# Get recent conviction
conviction = get_recent_conviction(uid, ticker, lookback_minutes=30)

# Access results
conviction['has_activity']      # bool
conviction['total_flows']       # int
conviction['avg_conviction']    # Decimal
conviction['dominant_sentiment'] # str: BULLISH/BEARISH/NEUTRAL/MIXED
conviction['total_premium']     # Decimal
conviction['flows']             # List[dict] - raw flows
```

### Conviction Scoring

```python
# Calculate score manually
score = service.calculate_conviction_score({
    "flow_type": "SWEEP",
    "is_otm": True,
    "vol_oi_ratio": "1.5"
})
# Returns: Decimal("1.00")
```

## Schema Reference

### Required Fields

```python
{
    "timestamp": str,              # ISO format
    "underlying_symbol": str,       # Stock ticker
    "option_symbol": str,          # Contract symbol
    "side": str,                   # "buy" or "sell"
    "size": int,                   # Number of contracts
    "premium": float,              # Total premium
}
```

### Optional (but recommended)

```python
{
    "strike_price": float,
    "expiration_date": str,        # YYYY-MM-DD
    "option_type": str,            # "call" or "put"
    "trade_price": float,
    "bid_price": float,
    "ask_price": float,
    "spot_price": float,
    "implied_volatility": float,
    "open_interest": int,
    "volume": int,
}
```

## Conviction Score Algorithm

| Component | Condition | Points |
|-----------|-----------|--------|
| Base (SWEEP) | `flow_type == "SWEEP"` | 0.8 |
| Base (BLOCK) | `flow_type == "BLOCK"` | 0.5 |
| OTM Boost | `is_otm == True` | +0.1 |
| Vol/OI Boost | `vol_oi_ratio > 1.2` | +0.1 |
| **Maximum** | All conditions | **1.0** |

## Troubleshooting

### Flow not detected as SWEEP/BLOCK

**Solution:** Provide `trade_price`, `ask_price`, and `size` fields.

### Conviction score is 0.3 (UNKNOWN)

**Solution:** Ensure flow detection fields are present (see above).

### get_recent_conviction returns no activity

**Solutions:**
1. Check `underlying_symbol` matches exactly (case-sensitive)
2. Increase `lookback_minutes`
3. Verify flows were ingested successfully

### Decimal precision issues

**Solution:** Service handles this automatically - all premiums/ratios use `Decimal`.

## Next Steps

✅ **Integrate with your data pipeline** → See `whale_flow_writer.py`  
✅ **Add to Maestro strategies** → Use `get_recent_conviction()`  
✅ **Set up alerts** → Check conviction scores after ingestion  
✅ **Monitor performance** → Track ingestion rate and query latency  

## Full Documentation

📚 **API Reference**: `/workspace/backend/services/README_WHALE_FLOW.md`  
🧪 **Tests**: `/workspace/tests/test_whale_flow_service.py`  
🎬 **Demo**: `python scripts/demo_whale_flow_service.py`  
📋 **Implementation Summary**: `/workspace/WHALE_FLOW_SERVICE_IMPLEMENTATION.md`  

## Questions?

Check the full documentation or review the demo script for detailed examples.

---

**Ready to trade with whale flow intelligence! 🐋📈**
