# Whale Flow Dashboard - Institutional Order Flow Tracking

## Overview

The Whale Flow Dashboard is an institutional-grade component that tracks and analyzes unusual options activity in real-time. It helps traders identify where "Big Money" is moving by visualizing sweeps and block trades with AI-powered insights.

## Components Created

### 1. Frontend Hook: `useWhaleFlow`
**Location:** `/workspace/frontend/src/hooks/useWhaleFlow.ts`

**Features:**
- Real-time Firestore listener on `marketData/options/unusual_activity`
- Automatically sorts by timestamp (most recent first)
- Configurable max records (default: 50)
- Type-safe TypeScript interfaces

**Usage:**
```typescript
import { useWhaleFlow } from "@/hooks/useWhaleFlow";

function MyComponent() {
  const { trades, loading, error } = useWhaleFlow(50);
  
  // trades: Array of WhaleFlowTrade objects
  // loading: Boolean indicating data fetch status
  // error: Error message string or null
}
```

**Data Structure:**
```typescript
interface WhaleFlowTrade {
  id: string;
  ticker: string;
  type: "SWEEP" | "BLOCK";
  sentiment: "BULLISH" | "BEARISH" | "NEUTRAL";
  option_type: "CALL" | "PUT";
  strike: string;
  expiry: string;
  premium: string; // Total premium in dollars
  size: number; // Number of contracts
  timestamp: any;
  spot_price?: string;
  implied_volatility?: string;
  description?: string;
}
```

### 2. Frontend Component: `WhaleFlow`
**Location:** `/workspace/frontend/src/components/WhaleFlow.tsx`

**Features:**
- **Sortable Table**: Click column headers to sort by Ticker, Premium, Size, or Time
- **Color-Coded Sentiment**: 
  - Green = Bullish (calls at the ask)
  - Red = Bearish (puts at the ask)
  - Gray = Neutral
- **Real-Time Updates**: Automatically refreshes as new trades come in
- **Flow Balance**: Shows count of bullish vs bearish trades
- **Premium Formatting**: Uses Decimal logic for accurate currency display
- **AI Summary Box**: Gemini 1.5 Flash analysis of top 10 trades

**UI Components Used:**
- shadcn/ui Table
- shadcn/ui Card
- shadcn/ui Badge
- shadcn/ui Button
- lucide-react Icons

### 3. Backend Function: `analyze_whale_flow`
**Location:** `/workspace/functions/main.py`

**Features:**
- Vertex AI Gemini 1.5 Flash integration
- Analyzes up to 10 whale flow trades
- Calculates dominant sentiment (BULLISH/BEARISH/MIXED)
- Identifies hot tickers with most activity
- Calculates total premium flow
- Fallback to rule-based summary if AI fails

**API Endpoint:**
```typescript
const functions = getFunctions(app);
const analyzeWhaleFlow = httpsCallable(functions, "analyze_whale_flow");

const result = await analyzeWhaleFlow({ 
  trades: topTrades.slice(0, 10) 
});

// Returns:
// {
//   summary: string,
//   dominant_sentiment: "BULLISH" | "BEARISH" | "MIXED",
//   top_tickers: string[],
//   total_flow: string
// }
```

## Firestore Data Model

### Collection Path
```
marketData/options/unusual_activity
```

### Document Schema
```typescript
{
  ticker: string;           // e.g., "TSLA", "SPY"
  type: string;            // "SWEEP" or "BLOCK"
  sentiment: string;       // "BULLISH", "BEARISH", "NEUTRAL"
  option_type: string;     // "CALL" or "PUT"
  strike: string;          // e.g., "450.00"
  expiry: string;          // e.g., "2025-01-17"
  premium: string;         // Total premium in dollars, e.g., "125000.00"
  size: number;            // Number of contracts
  timestamp: Timestamp;    // Firestore server timestamp
  spot_price?: string;     // Optional underlying price
  implied_volatility?: string;  // Optional IV
  description?: string;    // Optional trade description
}
```

## Integration Guide

### Step 1: Add Route to Frontend

Edit `/workspace/frontend/src/App.tsx` (or your routing file):

```typescript
import WhaleFlow from "@/components/WhaleFlow";

// Add route:
<Route path="/whale-flow" element={<WhaleFlow />} />
```

### Step 2: Add Navigation Link

Add to your sidebar or navigation:

```typescript
import { Activity } from "lucide-react";

<NavLink to="/whale-flow">
  <Activity className="h-4 w-4" />
  Whale Flow
</NavLink>
```

### Step 3: Deploy Backend Function

Deploy the updated Firebase Functions:

```bash
cd /workspace/functions
firebase deploy --only functions:analyze_whale_flow
```

### Step 4: Populate Test Data

To test the dashboard, add sample data to Firestore:

```javascript
// In Firebase Console or via script
const db = getFirestore();
const ref = collection(db, "marketData", "options", "unusual_activity");

await addDoc(ref, {
  ticker: "TSLA",
  type: "SWEEP",
  sentiment: "BULLISH",
  option_type: "CALL",
  strike: "450.00",
  expiry: "2025-01-17",
  premium: "125000.00",
  size: 250,
  timestamp: serverTimestamp(),
  spot_price: "442.50",
  implied_volatility: "0.45"
});
```

## AI Summary Configuration

The AI summary uses Gemini 1.5 Flash (configurable via environment variables):

```bash
# Environment Variables
VERTEX_AI_LOCATION=us-central1
VERTEX_AI_MODEL_ID=gemini-1.5-flash  # or gemini-2.5-flash
```

### Query Caching
- AI summaries are cached for 5 minutes
- Auto-refreshes when top 10 trades change
- Manual refresh button available

## Sentiment Color Coding

The dashboard uses institutional-grade color coding:

| Sentiment | Color | Meaning |
|-----------|-------|---------|
| BULLISH | Green (`emerald-400`) | Aggressive call buying at the ask |
| BEARISH | Red (`red-400`) | Aggressive put buying at the ask |
| NEUTRAL | Gray (`slate-400`) | Mid-market or spread trades |

## Performance Considerations

- **Real-time Updates**: Uses Firestore `onSnapshot` for live data
- **Sorting**: Client-side sorting with useMemo for performance
- **Pagination**: Limited to 50 records by default (configurable)
- **AI Throttling**: Only analyzes top 10 trades to reduce API costs
- **Auto-refresh**: AI summary refreshes only when trade IDs change

## Security Rules

Ensure your Firestore security rules allow reading whale flow data:

```javascript
// firestore.rules
match /marketData/options/unusual_activity/{doc} {
  allow read: if request.auth != null;  // Authenticated users only
}
```

## Monitoring & Observability

The backend function logs key events:

- Trade count received
- AI analysis completion
- API failures with fallback activation
- Processing time metrics

Check logs in Firebase Console:
```bash
firebase functions:log --only analyze_whale_flow
```

## Future Enhancements

Potential improvements for Phase 5:

1. **Real-time Alerts**: Push notifications for massive flows
2. **Historical Charts**: Visualize flow trends over time
3. **Ticker Deep Dive**: Click ticker to see detailed option chain
4. **Flow Screener**: Filter by ticker, sentiment, or premium size
5. **Export to CSV**: Download flows for external analysis
6. **Multi-Tenant Support**: Tenant-scoped whale flow collections

## Troubleshooting

### No Data Showing
- Check Firestore collection path: `marketData/options/unusual_activity`
- Verify security rules allow reads
- Check browser console for Firebase errors

### AI Summary Not Loading
- Verify `VERTEX_AI_LOCATION` and `VERTEX_AI_MODEL_ID` are set
- Check Firebase Functions logs for API errors
- Ensure billing is enabled for Vertex AI
- Fallback summary should still work if AI fails

### Sorting Not Working
- Check that timestamp fields are proper Firestore Timestamps
- Verify premium values are numeric strings
- Open browser console to check for JavaScript errors

## Tech Stack

- **Frontend**: React 18 + TypeScript + Vite
- **UI Framework**: shadcn/ui + Tailwind CSS
- **State Management**: React Query (@tanstack/react-query)
- **Backend**: Firebase Functions (Python)
- **AI**: Vertex AI Gemini 1.5 Flash
- **Database**: Cloud Firestore
- **Auth**: Firebase Authentication

## License

Part of the AgentTrader SaaS platform.
