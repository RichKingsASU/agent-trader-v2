# Macro-Event Scraper System

## Overview

The Macro-Event Scraper is an intelligent system that monitors major economic releases and news events, analyzes their market impact using AI, and automatically adjusts trading strategy risk parameters during periods of high volatility.

## Features

### 1. **Economic Data Ingestion**
- Federal Reserve Economic Calendar via FRED API
- Bureau of Labor Statistics data
- Real-time macro news from Alpaca News API

### 2. **AI-Powered Analysis**
- Uses Gemini 2.5 Flash for economic surprise analysis
- Detects significant deviations from expected values
- Assesses market impact and volatility expectations

### 3. **Automatic Risk Adjustment**
- Updates `systemStatus/market_regime` in Firestore
- Sets stop-loss multipliers (1.0x - 2.5x wider)
- Adjusts position size multipliers (0.25x - 1.0x smaller)
- Strategies automatically respond to regime changes

### 4. **Major Events Tracked**

| Event | Full Name | Threshold | Severity |
|-------|-----------|-----------|----------|
| **CPI** | Consumer Price Index | 0.2% deviation | HIGH |
| **FOMC** | Federal Reserve Rate Decision | 0.25% (25 bps) | CRITICAL |
| **NFP** | Non-Farm Payrolls | 50,000 jobs | HIGH |
| **GDP** | Gross Domestic Product | 0.5% deviation | HIGH |
| **PCE** | Personal Consumption Expenditures | 0.2% deviation | MEDIUM |
| **UNEMPLOYMENT** | Unemployment Rate | 0.2% deviation | HIGH |

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      Macro-Event Scraper                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
        ┌─────────────────────────────────────────────┐
        │         Data Ingestion Layer                │
        ├─────────────────────────────────────────────┤
        │  • Federal Reserve Economic Calendar        │
        │  • FRED API (CPI, GDP, Unemployment, etc.)  │
        │  • Alpaca News API (Macro headlines)        │
        └─────────────────────────────────────────────┘
                              │
                              ▼
        ┌─────────────────────────────────────────────┐
        │         AI Analysis Layer                   │
        ├─────────────────────────────────────────────┤
        │  • Gemini 2.5 Flash                         │
        │  • Surprise magnitude calculation           │
        │  • Market impact assessment                 │
        │  • Volatility expectation prediction        │
        └─────────────────────────────────────────────┘
                              │
                              ▼
        ┌─────────────────────────────────────────────┐
        │      Market Regime Update                   │
        ├─────────────────────────────────────────────┤
        │  Firestore: systemStatus/market_regime      │
        │  • macro_event_status                       │
        │  • stop_loss_multiplier                     │
        │  • position_size_multiplier                 │
        │  • macro_events[] (history)                 │
        └─────────────────────────────────────────────┘
                              │
                              ▼
        ┌─────────────────────────────────────────────┐
        │      Strategy Response                      │
        ├─────────────────────────────────────────────┤
        │  All active strategies automatically:       │
        │  • Widen stop-losses by multiplier          │
        │  • Reduce position sizes                    │
        │  • Adjust hedging thresholds                │
        └─────────────────────────────────────────────┘
```

## Installation & Setup

### 1. Environment Variables

Add to your Cloud Function environment:

```bash
# Required
APCA_API_KEY_ID=your_alpaca_key
APCA_API_SECRET_KEY=your_alpaca_secret
FIREBASE_PROJECT_ID=your_project_id
VERTEX_AI_PROJECT_ID=your_project_id  # Can be same as Firebase
VERTEX_AI_LOCATION=us-central1
VERTEX_AI_MODEL_ID=gemini-2.5-flash

# Optional
FRED_API_KEY=your_fred_api_key  # For Federal Reserve data
```

### 2. Deploy Cloud Functions

The macro scraper includes three Cloud Functions:

#### a. **Scheduled Scan** (Auto-runs every 30 minutes)
```bash
# Deployed automatically with main.py
firebase deploy --only functions:scan_macro_events
```

#### b. **Manual Trigger** (On-demand scan)
```bash
# Trigger via HTTP
curl -X POST https://us-central1-PROJECT.cloudfunctions.net/trigger_macro_scan \
  -H "Content-Type: application/json" \
  -d '{"data": {"lookback_hours": 24}}'

# Or via Firebase CLI
firebase functions:shell
> trigger_macro_scan({lookback_hours: 48})
```

#### c. **Status Check** (Get current regime)
```bash
curl -X POST https://us-central1-PROJECT.cloudfunctions.net/get_macro_status \
  -H "Content-Type: application/json"
```

### 3. Dependencies

Already added to `functions/requirements.txt`:
- `alpaca-py>=0.8.0`
- `google-cloud-aiplatform>=1.38.0`
- `requests>=2.31.0`

## Usage

### Programmatic Usage

```python
from functions.utils.macro_scraper import create_macro_coordinator
from google.cloud import firestore

# Initialize
db = firestore.Client()
coordinator = create_macro_coordinator(db_client=db)

# Scan for events in last 24 hours
results = coordinator.scan_and_analyze(lookback_hours=24)

# Check for significant events
if results['significant_events']:
    print(f"ALERT: {len(results['significant_events'])} significant events detected!")
    print(f"New regime: {results.get('new_regime')}")
    
    for event in results['significant_events']:
        release = event['release']
        analysis = event['analysis']
        print(f"\n{release['event_name']}:")
        print(f"  Actual: {release['actual_value']}")
        print(f"  Expected: {release['expected_value']}")
        print(f"  Surprise: {analysis['surprise_magnitude']:.2f}%")
        print(f"  Action: {analysis['recommended_action']}")

# Clear volatility event manually
coordinator.clear_volatility_event(reason="Event resolved")
```

### Strategy Integration

Strategies automatically receive regime updates. Example from `gamma_scalper_0dte/strategy.py`:

```python
def _fetch_market_regime_from_firestore() -> None:
    """Fetch market regime including macro event status"""
    global _macro_event_active, _stop_loss_multiplier, _position_size_multiplier
    
    db = firestore.Client()
    regime_ref = db.collection('systemStatus').document('market_regime')
    regime_data = regime_ref.get().to_dict()
    
    # Check for macro event
    if regime_data.get('macro_event_detected', False):
        _macro_event_active = True
        _stop_loss_multiplier = Decimal(regime_data.get('stop_loss_multiplier', 1.5))
        _position_size_multiplier = Decimal(regime_data.get('position_size_multiplier', 0.75))
        
        # Strategies automatically apply these multipliers to:
        # - Stop-loss orders (wider stops)
        # - Position sizing (smaller positions)
        # - Hedging thresholds (adjusted frequency)
```

## Market Regime States

### Normal
- **Status**: `"Normal"`
- **Stop-Loss Multiplier**: 1.0x (no change)
- **Position Size Multiplier**: 1.0x (no change)
- **Description**: No significant macro events detected

### Volatility Event
- **Status**: `"Volatility_Event"`
- **Stop-Loss Multiplier**: 1.5x (50% wider stops)
- **Position Size Multiplier**: 0.75x (25% smaller positions)
- **Trigger**: 1-2 high-impact events or moderate surprises
- **Example**: CPI misses expectations by 0.3%

### High Volatility
- **Status**: `"High_Volatility"`
- **Stop-Loss Multiplier**: 2.0x (100% wider stops)
- **Position Size Multiplier**: 0.50x (50% smaller positions)
- **Trigger**: 2+ high-impact events
- **Example**: CPI miss + unexpected FOMC statement

### Extreme Volatility
- **Status**: `"Extreme_Volatility"`
- **Stop-Loss Multiplier**: 2.5x (150% wider stops)
- **Position Size Multiplier**: 0.25x (75% smaller positions)
- **Trigger**: Any extreme-volatility event (e.g., emergency FOMC meeting)
- **Example**: Black swan event or major policy surprise

## Firestore Schema

### systemStatus/market_regime

```javascript
{
  // Existing GEX data
  "spy": {
    "net_gex": "-150000000",
    "volatility_bias": "Volatile",
    "spot_price": "495.50"
  },
  "qqq": { /* ... */ },
  
  // NEW: Macro event data
  "macro_event_detected": true,
  "macro_event_status": "Volatility_Event",
  "macro_event_time": Timestamp,
  "stop_loss_multiplier": 1.5,
  "position_size_multiplier": 0.75,
  
  "macro_events": [
    {
      "event_name": "CPI",
      "surprise_magnitude": 0.35,
      "volatility_expectation": "high",
      "recommended_action": "widen_stops",
      "confidence": 0.85,
      "reasoning": "CPI exceeded expectations by 0.35%, indicating persistent inflation..."
    }
  ],
  
  "updated_by": "macro_scraper",
  "last_updated": Timestamp
}
```

### systemStatus/macro_scraper_status

```javascript
{
  "last_scan": Timestamp,
  "status": "success",
  "significant_events_count": 1,
  "last_scan_results": {
    "scan_time": "2024-01-15T10:30:00Z",
    "releases_found": 5,
    "news_articles": 23,
    "significant_events": [ /* ... */ ]
  }
}
```

## Testing

Run the test suite:

```bash
# Run all tests
pytest functions/test_macro_scraper.py -v

# Run specific test
pytest functions/test_macro_scraper.py::TestMacroEventCoordinator::test_determine_regime_status_extreme -v

# Run with coverage
pytest functions/test_macro_scraper.py --cov=functions.utils.macro_scraper --cov-report=html
```

## Monitoring & Alerts

### Check System Status

```python
from google.cloud import firestore

db = firestore.Client()

# Check if macro event is active
regime = db.collection('systemStatus').document('market_regime').get()
if regime.exists:
    data = regime.to_dict()
    if data.get('macro_event_detected'):
        print(f"⚠️  MACRO EVENT ACTIVE: {data['macro_event_status']}")
        print(f"   Stop-loss multiplier: {data['stop_loss_multiplier']}x")
        print(f"   Position size multiplier: {data['position_size_multiplier']}x")
```

### View Scan History

```python
# Get recent scans
scraper_status = db.collection('systemStatus').document('macro_scraper_status').get()
if scraper_status.exists:
    data = scraper_status.to_dict()
    print(f"Last scan: {data['last_scan']}")
    print(f"Status: {data['status']}")
    print(f"Significant events: {data['significant_events_count']}")
```

### View Event History

```python
# Get archived events
events_ref = db.collection('systemStatus').document('market_regime').collection('macro_events')
recent_events = events_ref.order_by('archived_at', direction='DESCENDING').limit(10).get()

for event_doc in recent_events:
    event = event_doc.to_dict()
    print(f"\n{event['release']['event_name']}:")
    print(f"  Time: {event['release']['release_time']}")
    print(f"  Surprise: {event['analysis']['surprise_magnitude']:.2f}%")
    print(f"  Action: {event['analysis']['recommended_action']}")
```

## Best Practices

### 1. **FRED API Key** (Highly Recommended)
While optional, obtaining a free FRED API key provides much better economic data:
- Sign up at: https://fred.stlouisfed.org/docs/api/api_key.html
- Add to environment: `FRED_API_KEY=your_key`

### 2. **Scan Schedule**
The default 30-minute schedule is optimal for:
- Capturing economic releases (typically published at 8:30 AM ET)
- Monitoring ongoing market reactions
- Minimizing API costs

For high-frequency needs, reduce to every 15 minutes:
```python
@scheduler_fn.on_schedule(schedule="*/15 * * * *")
```

### 3. **Manual Overrides**
Clear false positives manually:
```python
coordinator.clear_volatility_event(reason="False alarm - data revision")
```

### 4. **Event Thresholds**
Customize thresholds in `macro_scraper.py`:
```python
MAJOR_ECONOMIC_EVENTS = {
    "CPI": {
        "surprise_threshold": 0.2,  # Adjust as needed
        "severity": EventSeverity.HIGH
    }
}
```

## Troubleshooting

### No Events Detected
1. Check FRED API key is set
2. Verify Alpaca credentials are valid
3. Check Cloud Function logs for errors
4. Manually trigger scan to test: `trigger_macro_scan()`

### Gemini Analysis Fails
1. Verify Vertex AI is enabled in GCP project
2. Check `VERTEX_AI_PROJECT_ID` is correct
3. Ensure service account has Vertex AI permissions
4. Check Gemini 2.5 Flash is available in your region

### Strategies Not Responding
1. Verify `systemStatus/market_regime` document exists
2. Check `macro_event_detected` flag is set to `true`
3. Ensure strategies are calling `_fetch_market_regime_from_firestore()`
4. Review strategy logs for errors

### Rate Limits
- FRED API: 120 requests/minute (free tier)
- Alpaca News: Check your plan limits
- Gemini: 300 requests/minute (default quota)

## Example Output

```
2024-01-15 08:35:00 [INFO] scan_macro_events: Starting macro event scan...
2024-01-15 08:35:02 [INFO] Found 5 economic releases
2024-01-15 08:35:05 [INFO] Found 23 macro-relevant news articles
2024-01-15 08:35:08 [INFO] Analyzing CPI with Gemini gemini-2.5-flash
2024-01-15 08:35:10 [WARNING] SIGNIFICANT SURPRISE DETECTED: CPI - Magnitude: 0.35%, Volatility: high, Action: widen_stops
2024-01-15 08:35:11 [WARNING] MARKET REGIME UPDATED: Volatility_Event - Stop-loss multiplier: 1.50x, Position size multiplier: 0.75x
2024-01-15 08:35:11 [INFO] scan_macro_events: Scan complete. Found 1 significant events.
```

## References

- [Federal Reserve Economic Data (FRED)](https://fred.stlouisfed.org/)
- [Alpaca News API](https://docs.alpaca.markets/docs/news-api)
- [Vertex AI Gemini](https://cloud.google.com/vertex-ai/docs/generative-ai/model-reference/gemini)
- [Firebase Cloud Functions](https://firebase.google.com/docs/functions)

## License

Part of the AgentTrader platform. Internal use only.
