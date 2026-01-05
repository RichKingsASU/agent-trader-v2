# WhaleFlowService Documentation

## Overview

The `WhaleFlowService` is a production-ready service for ingesting, scoring, and analyzing institutional options flow data ("whale flow"). It provides:

1. **Data Ingestion**: Maps raw JSON from data providers to a standardized Firestore schema
2. **Conviction Scoring**: Calculates quantitative conviction scores based on flow characteristics
3. **Maestro Integration**: Provides lookback queries for trade validation

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Data Provider                             │
│            (Websocket, API, or CSV feed)                     │
└──────────────────────┬──────────────────────────────────────┘
                       │ Raw JSON
                       ▼
┌─────────────────────────────────────────────────────────────┐
│               WhaleFlowService                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 1. map_flow_to_schema()                             │   │
│  │    - Parse timestamp                                │   │
│  │    - Normalize fields                               │   │
│  │    - Calculate metrics (vol/OI, OTM)                │   │
│  │    - Detect flow type (SWEEP/BLOCK)                 │   │
│  │    - Determine sentiment                            │   │
│  └─────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 2. calculate_conviction_score()                     │   │
│  │    - Base: 0.8 (SWEEP), 0.5 (BLOCK)                │   │
│  │    - +0.1 if OTM                                    │   │
│  │    - +0.1 if vol/OI > 1.2                           │   │
│  └─────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 3. ingest_flow() / ingest_batch()                   │   │
│  │    - Write to Firestore                             │   │
│  └─────────────────────────────────────────────────────┘   │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                   Firestore                                  │
│          users/{uid}/whaleFlow/{doc_id}                      │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│         Maestro Strategy (Trade Validation)                  │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ get_recent_conviction(uid, ticker)                  │   │
│  │  - Query last 30 minutes                            │   │
│  │  - Aggregate conviction scores                      │   │
│  │  - Analyze sentiment alignment                      │   │
│  │  - Approve/reject trade                             │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## Firestore Schema

Data is stored at: `users/{uid}/whaleFlow/{doc_id}`

### Document Structure

```python
{
    # Core identifiers
    "timestamp": datetime,           # Trade timestamp (UTC)
    "source": str,                   # Data provider identifier
    "underlying_symbol": str,        # Stock ticker (uppercase)
    "option_symbol": str,            # Full option contract symbol
    
    # Flow classification
    "flow_type": str,                # "SWEEP", "BLOCK", or "UNKNOWN"
    "sentiment": str,                # "BULLISH", "BEARISH", or "NEUTRAL"
    "side": str,                     # "buy" or "sell"
    
    # Size and premium
    "size": int,                     # Number of contracts
    "premium": str,                  # Total premium (Decimal as string)
    
    # Option details
    "strike_price": str,             # Strike price (Decimal as string)
    "expiration_date": str,          # "YYYY-MM-DD"
    "option_type": str,              # "CALL" or "PUT"
    
    # Pricing
    "trade_price": str,              # Price per contract
    "bid_price": str,                # Bid at time of trade
    "ask_price": str,                # Ask at time of trade
    "spot_price": str,               # Underlying spot price
    
    # Greeks and metrics
    "implied_volatility": str,       # IV at time of trade
    "open_interest": int,            # OI at strike
    "volume": int,                   # Option volume
    "vol_oi_ratio": str,             # Volume / OI ratio
    "is_otm": bool,                  # Is out-of-the-money
    
    # Conviction
    "conviction_score": str,         # 0.0 to 1.0 (Decimal as string)
    
    # Exchange and raw data
    "exchange": str,                 # Exchange identifier
    "raw_payload": dict,             # Original raw data
}
```

### Why Decimal as String?

Firestore doesn't have a native Decimal type. Storing as strings preserves precision for financial calculations while allowing Firestore queries.

## API Reference

### WhaleFlowService

#### `__init__(db: Optional[Client] = None)`

Create a service instance.

```python
from backend.services.whale_flow import WhaleFlowService

service = WhaleFlowService()
```

#### `map_flow_to_schema(uid: str, flow_data: Dict, source: str = "provider") -> Dict`

Map raw flow data to Firestore schema.

**Parameters:**
- `uid`: User ID for scoping
- `flow_data`: Raw flow data dictionary
- `source`: Data source identifier

**Returns:** Schema-compliant dictionary ready for Firestore

**Example:**
```python
raw_flow = {
    "timestamp": "2025-12-30T12:00:00Z",
    "underlying_symbol": "spy",
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
    "open_interest": 1000,
    "volume": 1500,
}

mapped = service.map_flow_to_schema("user123", raw_flow)
# Returns normalized, enriched document
```

#### `calculate_conviction_score(flow_data: Dict) -> Decimal`

Calculate conviction score (0.0 to 1.0).

**Scoring Algorithm:**
- Base 0.5 for BLOCK
- Base 0.8 for SWEEP
- +0.1 if OTM
- +0.1 if vol/OI > 1.2
- Clamped to [0, 1]

**Example:**
```python
flow = {
    "flow_type": "SWEEP",
    "is_otm": True,
    "vol_oi_ratio": "1.5",
}
score = service.calculate_conviction_score(flow)
# Returns: Decimal("1.00")
```

#### `ingest_flow(uid: str, flow_data: Dict, source: str = "provider", doc_id: Optional[str] = None) -> str`

Ingest a single flow event.

**Parameters:**
- `uid`: User ID
- `flow_data`: Raw flow data
- `source`: Data source identifier
- `doc_id`: Optional document ID (auto-generated if not provided)

**Returns:** Document ID

**Example:**
```python
doc_id = service.ingest_flow("user123", raw_flow)
```

#### `ingest_batch(uid: str, flows: List[Dict], source: str = "provider") -> List[str]`

Ingest multiple flows in a batch (more efficient).

**Parameters:**
- `uid`: User ID
- `flows`: List of raw flow data
- `source`: Data source identifier

**Returns:** List of document IDs

**Example:**
```python
flows = [flow1, flow2, flow3]
doc_ids = service.ingest_batch("user123", flows)
```

#### `get_recent_conviction(uid: str, ticker: str, lookback_minutes: int = 30) -> Dict`

Get recent conviction data for a ticker (for Maestro).

**Parameters:**
- `uid`: User ID
- `ticker`: Stock symbol
- `lookback_minutes`: Lookback window (default: 30)

**Returns:** Dictionary with aggregated metrics

**Response Structure:**
```python
{
    "ticker": str,                    # Stock symbol
    "has_activity": bool,             # True if flows found
    "total_flows": int,               # Count of flows
    "avg_conviction": Decimal,        # Average conviction score
    "max_conviction": Decimal,        # Maximum conviction score
    "bullish_flows": int,             # Count of bullish flows
    "bearish_flows": int,             # Count of bearish flows
    "total_premium": Decimal,         # Sum of all premiums
    "dominant_sentiment": str,        # "BULLISH", "BEARISH", "NEUTRAL", "MIXED"
    "flows": List[Dict],              # List of flow documents
}
```

**Example:**
```python
conviction = service.get_recent_conviction("user123", "AAPL", lookback_minutes=30)

if conviction['has_activity'] and conviction['avg_conviction'] > Decimal("0.7"):
    print(f"Strong {conviction['dominant_sentiment']} activity!")
```

### Convenience Functions

#### `get_recent_conviction(uid, ticker, lookback_minutes=30, db=None)`

Standalone function for Maestro integration.

```python
from backend.services.whale_flow import get_recent_conviction

conviction = get_recent_conviction("user123", "AAPL")
```

## Integration Examples

### 1. Data Pipeline Integration

```python
# In your options flow ingestion pipeline
from backend.services.whale_flow import WhaleFlowService

service = WhaleFlowService()

async def on_options_flow(websocket_message):
    """Handle incoming options flow from provider."""
    flows = parse_provider_message(websocket_message)
    
    for flow in flows:
        # Ingest for all subscribed users
        for uid in get_subscribed_users():
            service.ingest_flow(uid, flow, source="provider_name")
```

### 2. Maestro Strategy Integration

```python
# In your strategy decision logic
from backend.services.whale_flow import get_recent_conviction
from decimal import Decimal

class MyStrategy:
    def should_enter_long_position(self, ticker: str) -> Tuple[bool, str]:
        """Decide whether to enter long position."""
        # Check recent whale activity
        conviction = get_recent_conviction(
            self.uid,
            ticker,
            lookback_minutes=30
        )
        
        # Require strong bullish whale activity
        if conviction['has_activity']:
            if conviction['dominant_sentiment'] == 'BULLISH':
                if conviction['avg_conviction'] > Decimal("0.7"):
                    return True, f"Strong bullish whale activity: {conviction['total_flows']} flows, ${conviction['total_premium']} premium"
            elif conviction['dominant_sentiment'] == 'BEARISH':
                return False, f"Bearish whale activity detected, avoiding long entry"
        
        # Proceed with base strategy if no strong signal
        return True, "No strong whale signal"
```

### 3. Real-time Alert System

```python
from backend.services.whale_flow import WhaleFlowService
from decimal import Decimal

service = WhaleFlowService()

def process_and_alert(uid: str, raw_flow: dict):
    """Process flow and send alert if high conviction."""
    mapped = service.map_flow_to_schema(uid, raw_flow)
    
    conviction = Decimal(mapped['conviction_score'])
    
    if conviction > Decimal("0.85"):
        send_alert(
            uid=uid,
            title=f"🐋 High Conviction Flow: {mapped['underlying_symbol']}",
            body=f"{mapped['flow_type']} - {mapped['sentiment']} - ${mapped['premium']} premium"
        )
    
    # Ingest regardless
    service.ingest_flow(uid, raw_flow)
```

## Testing

Run the test suite:

```bash
pytest tests/test_whale_flow_service.py -v
```

Run the demo script:

```bash
python scripts/demo_whale_flow_service.py
```

## Performance Considerations

### Ingestion

- **Single Flow**: ~10-20ms per write
- **Batch (10 flows)**: ~50-100ms total (~5-10ms per flow)
- **Recommendation**: Use `ingest_batch()` for multiple flows

### Queries

- **get_recent_conviction**: ~50-200ms depending on flow count
- **Firestore indexed on**: `underlying_symbol`, `timestamp`
- **Query limit**: 50 flows (prevents slow queries)

### Cost Optimization

1. **Batch writes**: Use `ingest_batch()` instead of multiple `ingest_flow()` calls
2. **TTL policy**: Consider Firestore TTL to auto-delete old flows (e.g., after 7 days)
3. **User-scoped**: Data is per-user, so no multi-tenant query issues

## Security

### Firestore Rules

```javascript
// Firestore security rules
match /users/{uid}/whaleFlow/{doc} {
  // Users can read their own whale flow data
  allow read: if request.auth != null && request.auth.uid == uid;
  
  // Only backend services can write
  allow write: if false;
}
```

### Access Control

- Service writes are authenticated via ADC (Application Default Credentials)
- No direct user writes to `whaleFlow` collection
- All ingestion goes through backend services

## Monitoring

### Logging

The service logs key events:

```python
logger.info(f"Ingested whale flow for user {uid}: {doc_id}")
logger.info(f"Batch ingested {len(flows)} whale flows for user {uid}")
```

### Metrics to Track

1. **Ingestion rate**: Flows per minute
2. **Conviction distribution**: Histogram of conviction scores
3. **Query latency**: P50, P95, P99 for `get_recent_conviction()`
4. **Error rate**: Failed ingestions or mappings

## Troubleshooting

### Issue: Conviction score is always 0.3

**Cause:** Flow type not detected (UNKNOWN)

**Solution:** Ensure `flow_type`, `trade_price`, `ask_price`, and `size` are provided

### Issue: is_otm is always False

**Cause:** Missing `spot_price` or `strike_price`

**Solution:** Ensure both prices are provided in flow_data

### Issue: get_recent_conviction returns no activity

**Cause:** 
1. No flows ingested for that ticker
2. Lookback window too short
3. Timestamp timezone issues

**Solution:**
1. Verify flows are being ingested with correct `underlying_symbol`
2. Increase `lookback_minutes`
3. Ensure timestamps are UTC

## Roadmap

### Phase 5 Enhancements

1. **Multi-leg detection**: Detect spreads, straddles, butterflies
2. **Volume profile**: Track cumulative volume by strike
3. **Flow clustering**: Group related flows (same ticker + similar timing)
4. **Machine learning**: Train conviction model on historical outcomes
5. **Cross-ticker analysis**: Detect sector-wide flows

## Support

- **Service code**: `backend/services/whale_flow.py`
- **Tests**: `tests/test_whale_flow_service.py`
- **Demo**: `scripts/demo_whale_flow_service.py`
- **This doc**: `backend/services/README_WHALE_FLOW.md`

## License

Internal use only. Part of the AgentTrader platform.
