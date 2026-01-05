# Whale Flow Tracker Component

## Overview

The **WhaleFlowTracker** is an institutional-grade options flow tracking component that provides real-time monitoring of significant options trades (aka "whale" trades). It features advanced filtering, sentiment analysis, and integration with the GEX (Gamma Exposure) engine to identify high-conviction market moves.

## Features

### 1. Real-time Firestore Integration
- Listens to `market_intelligence/options_flow/live` collection
- Auto-updates as new trades flow in
- Efficient query with configurable trade limit (default: 100)

### 2. Premium Flow Heat Map
- Visual intensity bar showing the ratio of **Bullish vs Bearish** premium
- Real-time calculation of total premium flow by sentiment
- Animated gradient display with percentage breakdown
- Instant visual identification of market sentiment shifts

### 3. Golden Sweeps Detection
- Automatically flags trades meeting criteria:
  - Premium > $1,000,000
  - Days to Expiry < 14 days
- Marked with a **Crown icon** (👑) using lucide-react
- Special highlighting with gold border and background

### 4. Smart Filters

#### Aggressive Only
- Filters for trades executed at the **Ask price**
- Indicates strong buying pressure
- Useful for identifying conviction trades
- Icon: ⚡ Zap (Orange)

#### OTM Focus
- Shows only significantly **Out-of-the-Money** trades (>5% OTM)
- Indicates directional bets with high leverage
- Filters out hedging activity
- Icon: 🎯 Target (Blue)

#### GEX Overlay
- Integrates with system GEX (Gamma Exposure) data
- Highlights trades that align with current market regime
- **Negative GEX (Bearish regime)**:
  - Flags aggressive Put buying as "Volatility Expansion Signal"
  - Flags aggressive Call selling as "Bearish Conviction"
- **Positive GEX (Bullish regime)**:
  - Flags aggressive Call buying as "Bullish Conviction"
  - Flags Put selling as "Premium Collection"
- Icon: ✨ Sparkles (Purple)

## Usage

### Basic Integration

```tsx
import { WhaleFlowTracker } from "@/components/WhaleFlowTracker";

function MyPage() {
  return (
    <div>
      <WhaleFlowTracker maxTrades={100} />
    </div>
  );
}
```

### With Custom Trade Limit

```tsx
<WhaleFlowTracker maxTrades={50} />
```

### In a Dashboard Layout

```tsx
import { WhaleFlowTracker } from "@/components/WhaleFlowTracker";
import { DashboardHeader } from "@/components/DashboardHeader";

export default function WhaleFlowPage() {
  return (
    <div className="min-h-screen">
      <DashboardHeader />
      <main className="container mx-auto p-8">
        <WhaleFlowTracker />
      </main>
    </div>
  );
}
```

## Data Model Requirements

### Firestore Collection Structure

The component expects data in the following Firestore collection:

```
tenants/{tenantId}/market_intelligence/options_flow/live/{tradeId}
```

### Trade Document Schema

Each trade document should contain:

```typescript
{
  // Required fields
  symbol: string;              // e.g., "SPY", "AAPL"
  strike: number;              // Strike price
  expiry: string;              // Expiry date string (e.g., "12/31")
  expiry_date: Timestamp;      // Firestore Timestamp
  option_type: string;         // "call" or "put"
  side: string;                // "buy" or "sell"
  execution_side: string;      // "ask", "bid", or "mid"
  size: number;                // Number of contracts
  premium: number;             // Total premium in dollars
  underlying_price: number;    // Current price of underlying
  timestamp: Timestamp;        // Trade timestamp
  
  // Optional but recommended
  iv: number;                  // Implied volatility (0-1 decimal)
  delta: number;               // Delta greek (-1 to 1)
  gamma: number;               // Gamma greek
  days_to_expiry: number;      // Days until expiration
}
```

### System Status Collection

For GEX overlay functionality, the component also subscribes to:

```
tenants/{tenantId}/ops/{docId}
```

With fields:
```typescript
{
  net_gex: number;             // Net gamma exposure
  volatility_bias: string;     // "Bullish", "Bearish", or "Neutral"
}
```

## Component Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `maxTrades` | `number` | `100` | Maximum number of trades to display |

## Visual Elements

### Icons Used (lucide-react)

- 👑 **Crown**: Golden Sweeps
- 📈 **TrendingUp**: Bullish trades
- 📉 **TrendingDown**: Bearish trades
- ✨ **Sparkles**: GEX signals
- ⚡ **Zap**: Aggressive filter
- 🎯 **Target**: OTM filter
- 🔍 **Filter**: Filter section
- 📊 **Activity**: Heat map

### Color Scheme

- **Bullish**: Emerald (green) - `emerald-500`
- **Bearish**: Red - `red-500`
- **Golden Sweep**: Yellow/Gold - `yellow-500`
- **GEX Signal**: Purple - `purple-500`
- **Aggressive**: Orange - `orange-500`
- **OTM Focus**: Blue - `blue-500`

## Performance Considerations

1. **Firestore Queries**: Limited to `maxTrades` documents using Firestore `limit()`
2. **Real-time Updates**: Uses efficient `onSnapshot` listeners
3. **Memoization**: Heavy calculations (premium stats, filtering) are memoized
4. **Cleanup**: Properly unsubscribes from listeners on unmount

## Integration with GEX Engine

The component automatically integrates with your `gex_engine.py` by:

1. Subscribing to system status updates
2. Reading `net_gex` and `volatility_bias` fields
3. Cross-referencing options flow with current market regime
4. Highlighting trades that align with or contradict the regime

This creates powerful signals:
- **Negative GEX** + **Aggressive Put Buying** = Volatility Expansion Signal
- **Positive GEX** + **Aggressive Call Buying** = Bullish Conviction
- And more...

## Example Scenarios

### Scenario 1: Detecting a Volatility Event
1. GEX turns negative (Short Gamma regime)
2. Multiple large Put trades execute at the Ask
3. Component flags these as "Volatility Expansion Signals"
4. Heat map shifts heavily toward Bearish
5. Trader can anticipate increased volatility

### Scenario 2: Golden Sweep Alert
1. $2.5M Call trade detected
2. Expiry in 7 days (< 14 DTE threshold)
3. Trade executed at Ask (aggressive)
4. Component displays Crown icon
5. Gold border and special highlighting
6. Trader investigates potential major move

### Scenario 3: OTM Speculation
1. Enable "OTM Focus" filter
2. See only trades >5% out of the money
3. Identify directional bets with high conviction
4. Filter out hedging and ATM activity

## Troubleshooting

### No Trades Showing

1. Check Firestore collection path is correct
2. Verify tenantId is properly set in AuthContext
3. Ensure trades exist in the `live` subcollection
4. Check browser console for Firestore errors

### GEX Overlay Not Working

1. Verify `ops` collection exists in Firestore
2. Check that `net_gex` and `volatility_bias` fields are present
3. Ensure system is writing GEX data from `gex_engine.py`

### Performance Issues

1. Reduce `maxTrades` prop value
2. Check Firestore query indexes
3. Monitor network tab for excessive reads
4. Consider pagination for large datasets

## Future Enhancements

Potential additions:
- [ ] Export trades to CSV
- [ ] Trade alerts/notifications
- [ ] Historical replay mode
- [ ] Sector/symbol filtering
- [ ] Custom alert rules
- [ ] Integration with trade execution
- [ ] Volume-weighted premium flow
- [ ] Multi-symbol comparison

## Related Components

- `GEXVisualization`: Shows full GEX strike ladder
- `UnusualActivityScanner`: Alternative flow scanner
- `OptionsChain`: Full options chain viewer
- `SystemPulse`: System health monitoring

## Dependencies

```json
{
  "firebase": "^10.x",
  "lucide-react": "^0.x",
  "@radix-ui/react-*": "Latest",
  "recharts": "^2.x"
}
```

## License

Part of AgentTrader institutional trading platform.
