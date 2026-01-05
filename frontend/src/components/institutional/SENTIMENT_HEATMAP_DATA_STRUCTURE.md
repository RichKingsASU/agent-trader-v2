# Sentiment Heatmap - Firestore Data Structure

## Collection Path
```
marketData/sentiment/sectors/{sectorId}
```

## Document Structure

Each document represents a market sector with the following fields:

| Field | Type | Range | Description | Example |
|-------|------|-------|-------------|---------|
| `value` | number | > 0 | Market capitalization or relative weight | `1500000000000` (1.5T) |
| `sentiment` | number | -1.0 to 1.0 | AI-driven sentiment score | `0.65` |
| `leadingTicker` | string | - | Leading stock ticker in this sector | `"NVDA"` |

## Sample Data

### Example 1: Technology Sector (Bullish)
```json
{
  "value": 1500000000000,
  "sentiment": 0.75,
  "leadingTicker": "NVDA"
}
```
**Document ID**: `Technology`

### Example 2: Energy Sector (Bearish)
```json
{
  "value": 800000000000,
  "sentiment": -0.65,
  "leadingTicker": "XOM"
}
```
**Document ID**: `Energy`

### Example 3: Healthcare Sector (Neutral)
```json
{
  "value": 1200000000000,
  "sentiment": 0.05,
  "leadingTicker": "UNH"
}
```
**Document ID**: `Healthcare`

## Complete Sample Dataset

Here's a full set of 11 sectors you can add to Firestore:

```javascript
// Copy this into Firebase Console or use a Cloud Function to seed

const sectors = [
  {
    id: "Technology",
    value: 1500000000000,
    sentiment: 0.75,
    leadingTicker: "NVDA"
  },
  {
    id: "Healthcare",
    value: 1200000000000,
    sentiment: 0.05,
    leadingTicker: "UNH"
  },
  {
    id: "Financials",
    value: 1100000000000,
    sentiment: 0.35,
    leadingTicker: "JPM"
  },
  {
    id: "Consumer Discretionary",
    value: 950000000000,
    sentiment: -0.25,
    leadingTicker: "AMZN"
  },
  {
    id: "Communication Services",
    value: 850000000000,
    sentiment: 0.42,
    leadingTicker: "GOOGL"
  },
  {
    id: "Industrials",
    value: 800000000000,
    sentiment: 0.18,
    leadingTicker: "BA"
  },
  {
    id: "Consumer Staples",
    value: 750000000000,
    sentiment: -0.12,
    leadingTicker: "WMT"
  },
  {
    id: "Energy",
    value: 650000000000,
    sentiment: -0.68,
    leadingTicker: "XOM"
  },
  {
    id: "Utilities",
    value: 450000000000,
    sentiment: -0.35,
    leadingTicker: "NEE"
  },
  {
    id: "Real Estate",
    value: 400000000000,
    sentiment: -0.45,
    leadingTicker: "PLD"
  },
  {
    id: "Materials",
    value: 350000000000,
    sentiment: 0.22,
    leadingTicker: "LIN"
  }
];

// Firebase Admin SDK example
const admin = require('firebase-admin');
const db = admin.firestore();

async function seedSentimentData() {
  const batch = db.batch();
  
  sectors.forEach(sector => {
    const ref = db.collection('marketData')
      .doc('sentiment')
      .collection('sectors')
      .doc(sector.id);
    
    batch.set(ref, {
      value: sector.value,
      sentiment: sector.sentiment,
      leadingTicker: sector.leadingTicker,
      lastUpdated: admin.firestore.FieldValue.serverTimestamp()
    });
  });
  
  await batch.commit();
  console.log('Sentiment data seeded successfully!');
}
```

## Firestore Console Quick Add

Navigate to Firestore Console → Create Collection:

1. **Collection ID**: `marketData`
2. **Document ID**: `sentiment`
3. **Add Subcollection**: `sectors`
4. For each sector, create a document with:
   - **Document ID**: Sector name (e.g., "Technology")
   - **Fields**:
     - `value` (number)
     - `sentiment` (number, -1.0 to 1.0)
     - `leadingTicker` (string)

## Color Scale Mapping

The component uses a diverging color scale:

| Sentiment Range | Color | Hex Code | Interpretation |
|----------------|-------|----------|----------------|
| -1.0 to -0.3 | Red | `#ef4444` | Extreme Bearish |
| -0.3 to 0.3 | Gray | `#71717a` | Neutral / Consolidation |
| 0.3 to 1.0 | Green | `#22c55e` | Extreme Bullish |

## Real-Time Updates

The component uses Firestore's `onSnapshot` listener, so any changes to the sentiment data will automatically update the treemap in real-time without requiring a page refresh.

## Performance Optimization

The treemap is memoized and will only re-render when sentiment scores change by more than **0.05**, preventing unnecessary visual updates from minor fluctuations.
