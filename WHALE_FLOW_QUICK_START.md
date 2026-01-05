# Whale Flow Tracker - Quick Start Guide

## 🚀 What Was Built

A production-ready **Whale Flow Tracker** component that monitors institutional options flow in real-time with advanced filtering and GEX integration.

### Key Features
- ✅ Real-time Firestore listener on `market_intelligence/options_flow/live`
- ✅ Heat map showing Bullish vs Bearish premium ratio
- ✅ Golden Sweeps detection (>$1M premium, <14 DTE)
- ✅ Smart filters: Aggressive Only, OTM Focus, GEX Overlay
- ✅ Integration with GEX engine for regime-aligned signals

---

## 📁 Files Created

### Core Component
```
frontend/src/components/WhaleFlowTracker.tsx
```
Main component with heat map, filters, and trade display.

### Custom Hook
```
frontend/src/hooks/useWhaleFlow.ts
```
Firestore integration, data processing, and GEX status monitoring.

### Example Page
```
frontend/src/pages/WhaleFlow.tsx
```
Full-page implementation example.

### Documentation
```
frontend/src/components/WhaleFlowTracker.md
docs/WHALE_FLOW_TRACKER.md
```
Comprehensive feature documentation and integration guide.

### Test Data Seeder
```
scripts/seed_whale_flow_data.py
```
Python script to populate Firestore with realistic test data.

---

## 🏃 Quick Start (5 Minutes)

### Step 1: Seed Test Data

```bash
# Set your tenant ID
export TENANT_ID="your-tenant-id-here"

# Run the seeder script
python scripts/seed_whale_flow_data.py \
  --tenant-id $TENANT_ID \
  --num-trades 50 \
  --num-golden-sweeps 5
```

This creates:
- 50 realistic options flow trades
- 5 Golden Sweep trades (>$1M)
- System status with GEX data

### Step 2: Add Route to Your App

Update your router configuration (e.g., `App.tsx` or `routes.tsx`):

```tsx
import WhaleFlow from "@/pages/WhaleFlow";

// Add to your routes:
<Route path="/whale-flow" element={<WhaleFlow />} />
```

### Step 3: Navigate and Test

1. Open your app: `http://localhost:5173/whale-flow`
2. You should see:
   - Heat map with premium flow
   - 55 trades (50 regular + 5 golden)
   - 👑 Crown icons on golden sweeps
   - Active filters with toggles

### Step 4: Test Real-time Updates

1. Open Firestore Console
2. Navigate to: `tenants/{your-tenant-id}/market_intelligence/options_flow/live`
3. Add a new trade document:

```json
{
  "symbol": "SPY",
  "strike": 435,
  "expiry": "12/31",
  "expiry_date": "2025-12-31T00:00:00Z",
  "days_to_expiry": 7,
  "option_type": "call",
  "side": "buy",
  "execution_side": "ask",
  "size": 1000,
  "premium": 1500000,
  "underlying_price": 432.50,
  "iv": 0.25,
  "delta": 0.40,
  "gamma": 0.03,
  "moneyness": "OTM",
  "otm_percentage": 0.58,
  "sentiment": "bullish",
  "timestamp": "now"
}
```

4. Watch it appear instantly in the UI! 🎉

---

## 🎨 Component Features in Detail

### 1. Heat Map Intensity Bar

Visual representation of market sentiment:

```
[====== BULLISH 65% ======|=== BEARISH 35% ===]
```

- Green gradient for bullish
- Red gradient for bearish
- Real-time updates
- Shows $ amounts

### 2. Golden Sweeps

Automatically detected trades with:
- Premium > $1,000,000
- Days to Expiry < 14
- 👑 Crown icon
- Gold border and background
- Special "GOLDEN SWEEP" label

### 3. Smart Filters

#### ⚡ Aggressive Only
- Shows trades at the Ask
- Indicates buying pressure
- Filters passive orders

#### 🎯 OTM Focus  
- Shows OTM trades >5%
- Directional speculation
- High leverage plays

#### ✨ GEX Overlay
- Reads GEX regime from system status
- Highlights regime-aligned trades
- **Negative GEX**: Flags aggressive Put buying
- **Positive GEX**: Flags aggressive Call buying

---

## 🔌 Integration with Your App

### Basic Usage

```tsx
import { WhaleFlowTracker } from "@/components/WhaleFlowTracker";

function MyDashboard() {
  return (
    <div className="container">
      <h1>Options Flow</h1>
      <WhaleFlowTracker maxTrades={100} />
    </div>
  );
}
```

### With Custom Styling

```tsx
<div className="grid grid-cols-2 gap-4">
  <div>
    <WhaleFlowTracker maxTrades={50} />
  </div>
  <div>
    {/* Other components */}
  </div>
</div>
```

### In a Tabbed Layout

```tsx
<Tabs defaultValue="flow">
  <TabsList>
    <TabsTrigger value="flow">Whale Flow</TabsTrigger>
    <TabsTrigger value="gex">GEX Map</TabsTrigger>
  </TabsList>
  <TabsContent value="flow">
    <WhaleFlowTracker />
  </TabsContent>
  <TabsContent value="gex">
    <GEXVisualization />
  </TabsContent>
</Tabs>
```

---

## 📊 Firestore Data Model

### Required Collection Structure

```
tenants/
  └── {tenantId}/
      ├── market_intelligence/
      │   └── options_flow/
      │       └── live/
      │           ├── {tradeId1}
      │           ├── {tradeId2}
      │           └── ...
      └── ops/
          └── system_status
```

### Trade Document Schema

```typescript
{
  // Required
  symbol: string;              // "SPY", "AAPL", etc.
  strike: number;              // 435.00
  expiry: string;              // "12/31"
  expiry_date: Timestamp;      // Firestore Timestamp
  option_type: string;         // "call" | "put"
  side: string;                // "buy" | "sell"
  execution_side: string;      // "ask" | "bid" | "mid"
  size: number;                // 500 (contracts)
  premium: number;             // 1250000 (dollars)
  underlying_price: number;    // 432.50
  timestamp: Timestamp;        // Trade time
  
  // Recommended
  iv: number;                  // 0.25 (25%)
  delta: number;               // 0.40
  gamma: number;               // 0.03
  days_to_expiry: number;      // 7
  moneyness: string;           // "ITM" | "ATM" | "OTM"
  otm_percentage: number;      // 2.5 (%)
  sentiment: string;           // "bullish" | "bearish" | "neutral"
}
```

---

## 🧪 Testing Checklist

- [ ] Component loads without errors
- [ ] Real-time Firestore subscription works
- [ ] Heat map displays correctly
- [ ] Golden sweeps are flagged with crown icon
- [ ] Aggressive Only filter works
- [ ] OTM Focus filter works
- [ ] GEX Overlay shows signals
- [ ] Trades update in real-time
- [ ] Scrolling works smoothly
- [ ] Responsive on mobile
- [ ] No console errors
- [ ] Proper loading states
- [ ] Error handling works

---

## 🐛 Troubleshooting

### No Trades Showing

**Problem**: Component loads but no trades display

**Solutions**:
1. Check tenant ID: `console.log(useAuth().tenantId)`
2. Verify Firestore path: `tenants/{tenantId}/market_intelligence/options_flow/live`
3. Check Firestore rules allow reads
4. Run seeder script to add test data

### Heat Map Not Updating

**Problem**: Heat map shows 50/50 split

**Solutions**:
1. Check trades have `sentiment` field
2. Verify `premium` values are numbers
3. Clear cache and reload
4. Check browser console for errors

### GEX Overlay Not Working

**Problem**: No GEX signals showing

**Solutions**:
1. Check `ops/system_status` document exists
2. Verify `net_gex` and `volatility_bias` fields
3. Enable GEX Overlay toggle
4. Run GEX engine to populate data

### Performance Issues

**Problem**: Slow loading or laggy scrolling

**Solutions**:
1. Reduce `maxTrades` prop (try 50 instead of 100)
2. Add Firestore indexes
3. Check network tab for excessive reads
4. Optimize Firestore queries

---

## 🔗 Integration with GEX Engine

The component automatically integrates with your existing GEX engine:

### Python Backend (Already Exists)

```python
# functions/utils/gex_engine.py

gex_data = calculate_net_gex(symbol="SPY", api=alpaca_client)

# Write to Firestore
db.collection("tenants").document(tenant_id).collection("ops").document("system_status").set({
    "net_gex": gex_data["net_gex"],
    "volatility_bias": gex_data["volatility_bias"],
    "timestamp": datetime.utcnow()
})
```

### Frontend Component (Automatic)

The component automatically:
1. Subscribes to `ops/system_status`
2. Reads `net_gex` and `volatility_bias`
3. Cross-references with options flow
4. Highlights matching trades

---

## 🎯 Example Use Cases

### Use Case 1: Detecting Volatility Expansion
1. GEX turns negative (bearish regime)
2. Multiple large Put trades execute at Ask
3. Component flags as "Volatility Expansion Signal"
4. Trader expects increased volatility

### Use Case 2: Golden Sweep Alert
1. $2.5M Call trade detected
2. Expiry in 7 days (< 14 DTE)
3. Executed at Ask (aggressive)
4. Component shows crown icon
5. Trader investigates potential move

### Use Case 3: Conviction Filter
1. Enable "Aggressive Only" filter
2. Enable "OTM Focus" filter
3. See only high-conviction directional bets
4. Filter out hedging activity

---

## 📱 Responsive Design

The component is fully responsive:

- **Desktop**: Full 12-column grid layout
- **Tablet**: Stacked layout with wrapped elements
- **Mobile**: Single column with touch-friendly controls

---

## 🚀 Next Steps

### Immediate (Already Done)
- [x] Create component
- [x] Create hook
- [x] Add filters
- [x] Integrate GEX
- [x] Add documentation
- [x] Create test data seeder

### Short Term (You Can Add)
- [ ] Add to main navigation
- [ ] Create alerts system
- [ ] Add export to CSV
- [ ] Add symbol filter dropdown

### Medium Term (Future Enhancements)
- [ ] Historical replay mode
- [ ] Custom alert rules
- [ ] Volume profile chart
- [ ] Sector grouping
- [ ] Multi-timeframe view

### Long Term (Advanced Features)
- [ ] ML prediction models
- [ ] Trade execution integration
- [ ] Mobile app version
- [ ] Real-time notifications
- [ ] Social sharing

---

## 📚 Additional Resources

- **Component Docs**: `frontend/src/components/WhaleFlowTracker.md`
- **Implementation Summary**: `docs/WHALE_FLOW_TRACKER.md`
- **GEX Engine**: `functions/utils/gex_engine.py`
- **Example Page**: `frontend/src/pages/WhaleFlow.tsx`
- **Test Seeder**: `scripts/seed_whale_flow_data.py`

---

## 💡 Pro Tips

1. **Start Small**: Begin with 50 trades, increase as needed
2. **Use Filters**: Combine filters for powerful signal detection
3. **Watch GEX**: Enable GEX Overlay for regime-aligned trades
4. **Golden Sweeps**: These are your highest-conviction signals
5. **Real-time**: Keep component open for live monitoring
6. **Test Data**: Use seeder script for development/testing

---

## ✅ Verification

Run through this checklist to verify everything works:

```bash
# 1. Seed data
python scripts/seed_whale_flow_data.py --tenant-id YOUR_TENANT_ID

# 2. Start frontend
cd frontend && npm run dev

# 3. Navigate to component
# Open: http://localhost:5173/whale-flow

# 4. Check features:
# - Heat map displays
# - Trades are listed
# - Filters toggle
# - Golden sweeps have crown icon
# - GEX overlay shows signals

# 5. Test real-time
# - Add trade in Firestore Console
# - Watch it appear in UI

# ✅ Success!
```

---

## 🎉 You're Ready!

The Whale Flow Tracker is now fully integrated and ready to track institutional options flow in real-time. Start monitoring whale trades and watch for golden sweeps!

**Happy Trading! 🚀📊💰**
