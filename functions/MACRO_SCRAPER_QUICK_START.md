# Macro-Event Scraper - Quick Start Guide

## 5-Minute Setup

### Step 1: Set Environment Variables

Add to your Cloud Function configuration (`.env` or Cloud Console):

```bash
# Required
APCA_API_KEY_ID=pk_...
APCA_API_SECRET_KEY=...
APCA_API_BASE_URL=https://paper-api.alpaca.markets
FIREBASE_PROJECT_ID=your-project-id
VERTEX_AI_PROJECT_ID=your-project-id
VERTEX_AI_MODEL_ID=gemini-2.5-flash

# Recommended (free API key)
FRED_API_KEY=your_fred_api_key
```

### Step 2: Deploy Cloud Functions

```bash
cd functions
firebase deploy --only functions:scan_macro_events,functions:trigger_macro_scan,functions:get_macro_status
```

### Step 3: Test It

```bash
# Manual trigger
curl -X POST https://us-central1-YOUR-PROJECT.cloudfunctions.net/trigger_macro_scan \
  -H "Content-Type: application/json" \
  -d '{"data": {"lookback_hours": 24}}'

# Check status
curl -X POST https://us-central1-YOUR-PROJECT.cloudfunctions.net/get_macro_status \
  -H "Content-Type: application/json"
```

### Step 4: Verify in Firestore

Navigate to Firestore Console:
- Check: `systemStatus/market_regime` document
- Look for: `macro_event_detected`, `macro_event_status`, `stop_loss_multiplier`

## How It Works

```
Every 30 minutes:
  1. Scan FRED for CPI, GDP, Unemployment, etc.
  2. Fetch macro news from Alpaca
  3. Analyze surprises with Gemini AI
  4. Update Firestore if significant event found
  5. Strategies automatically adjust stops & sizes
```

## What Gets Updated

**Firestore: `systemStatus/market_regime`**

```javascript
{
  "macro_event_detected": true,          // ← Strategies check this
  "macro_event_status": "Volatility_Event",
  "stop_loss_multiplier": 1.5,           // ← 50% wider stops
  "position_size_multiplier": 0.75,      // ← 25% smaller positions
  "macro_events": [                       // ← Event details
    {
      "event_name": "CPI",
      "surprise_magnitude": 0.35,
      "volatility_expectation": "high",
      "recommended_action": "widen_stops"
    }
  ]
}
```

## Strategy Integration Example

Your strategies automatically receive updates:

```python
# In your strategy (e.g., gamma_scalper_0dte/strategy.py)
def _fetch_market_regime_from_firestore():
    regime = db.collection('systemStatus').document('market_regime').get()
    
    if regime.get('macro_event_detected'):
        # Automatically apply wider stops
        stop_loss_multiplier = regime.get('stop_loss_multiplier', 1.5)
        position_size_multiplier = regime.get('position_size_multiplier', 0.75)
        
        # Your stops are now 1.5x wider!
        # Your positions are now 25% smaller!
```

## Major Events Tracked

| Event | Threshold | Example |
|-------|-----------|---------|
| **CPI** | 0.2% deviation | Expected 3.0%, Actual 3.3% = Alert! |
| **FOMC** | 0.25% (25 bps) | Expected no change, raised 0.5% = Alert! |
| **Jobs Report** | 50,000 jobs | Expected +150k, Actual +90k = Alert! |
| **GDP** | 0.5% deviation | Expected 2.0%, Actual 1.4% = Alert! |

## Monitoring Dashboard

Create a simple dashboard in your frontend:

```javascript
// Fetch macro status
const response = await fetch('https://us-central1-PROJECT.cloudfunctions.net/get_macro_status', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' }
});

const status = await response.json();

if (status.macro_event_active) {
  // Show alert banner
  alert(`⚠️ VOLATILITY EVENT: ${status.status}`);
  console.log(`Stop-loss multiplier: ${status.stop_loss_multiplier}x`);
  console.log(`Position size multiplier: ${status.position_size_multiplier}x`);
}
```

## Common Use Cases

### 1. Morning Check (8:30 AM ET - Economic Releases)
```bash
# Trigger scan after CPI/Jobs Report
curl -X POST .../trigger_macro_scan -d '{"data": {"lookback_hours": 2}}'
```

### 2. FOMC Days (2:00 PM ET - Rate Decision)
```bash
# Scan immediately after FOMC announcement
curl -X POST .../trigger_macro_scan -d '{"data": {"lookback_hours": 1}}'
```

### 3. Clear False Alarm
```bash
# If event was a false positive
curl -X POST .../trigger_macro_scan -d '{"data": {"clear_event": true}}'
```

## Expected Behavior

### Scenario 1: Normal Day
```
08:30 AM - Scan runs
Result: No significant surprises
Action: No changes to strategies
```

### Scenario 2: CPI Surprise
```
08:30 AM - CPI released: 3.5% (expected 3.0%)
08:31 AM - Gemini analysis: "High volatility expected"
08:32 AM - Firestore updated: macro_event_detected = true
08:33 AM - All strategies: Widen stops by 1.5x, reduce size by 25%
Result: Your strategies are now more defensive!
```

### Scenario 3: Extreme Event (Black Swan)
```
10:00 AM - Emergency FOMC meeting announced
10:01 AM - Gemini: "Extreme volatility"
10:02 AM - Firestore: stop_loss_multiplier = 2.5x, position_size = 0.25x
Result: Strategies now in ultra-defensive mode!
```

## Troubleshooting

**No events detected?**
- Get free FRED API key: https://fred.stlouisfed.org/docs/api/api_key.html
- Check Cloud Function logs

**Strategies not responding?**
- Verify `systemStatus/market_regime` exists in Firestore
- Check strategy is calling `_fetch_market_regime_from_firestore()`

**Gemini errors?**
- Enable Vertex AI in GCP Console
- Grant service account "Vertex AI User" role

## Next Steps

1. ✅ Deploy functions
2. ✅ Test with manual trigger
3. ✅ Verify Firestore updates
4. ✅ Check strategy logs confirm receipt
5. ✅ Monitor for next major release (CPI, Jobs, etc.)

## Full Documentation

See `MACRO_SCRAPER_README.md` for complete details, API reference, and advanced usage.

---

**Questions?** Check the logs:
```bash
firebase functions:log --only scan_macro_events
```
