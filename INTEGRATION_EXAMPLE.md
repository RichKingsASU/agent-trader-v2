# 🎨 Integration Example: Adding AISignalWidget to Dashboard

## Quick Start

Add the AI Signal Widget to any page in just 3 lines!

### Example: Adding to Main Dashboard (`frontend/src/pages/Index.tsx`)

```tsx
// 1. Import the component
import { AISignalWidget } from "@/components/AISignalWidget";

// 2. Add to your JSX (inside the right column with AccountPanel)
{layout.showAccountPanel && (
  <div className="transition-all duration-300 animate-fade-in">
    <h3 className="text-xs font-semibold text-muted-foreground mb-2 uppercase tracking-wider ui-label">
      Account & Risk
    </h3>
    <AccountPanel data={effectiveAccountData} loading={false} />
  </div>
)}

{/* 3. Add the AI Signal Widget */}
<div className="transition-all duration-300 animate-fade-in">
  <h3 className="text-xs font-semibold text-muted-foreground mb-2 uppercase tracking-wider ui-label">
    AI Trading Signals
  </h3>
  <AISignalWidget />
</div>
```

## Complete Example

Here's a full example showing where to place the widget in `Index.tsx`:

```tsx
// At the top with other imports
import { AISignalWidget } from "@/components/AISignalWidget";

// ... rest of your imports and component code ...

return (
  <div className="min-h-screen bg-background">
    <DashboardHeader {...headerProps} />

    <div className="p-4 space-y-4">
      {/* Chart Section - Left Side */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        
        {/* Main Chart Area */}
        <div className="lg:col-span-2">
          <TradingViewChart symbol={currentSymbol} />
        </div>

        {/* Right Sidebar - Add AI Signal Widget Here */}
        <div className="space-y-4">
          
          {/* Account Panel */}
          {layout.showAccountPanel && (
            <div>
              <h3 className="text-xs font-semibold text-muted-foreground mb-2 uppercase tracking-wider ui-label">
                Account & Risk
              </h3>
              <AccountPanel data={effectiveAccountData} loading={false} />
            </div>
          )}

          {/* 🚀 AI SIGNAL WIDGET - ADD HERE 🚀 */}
          <div>
            <h3 className="text-xs font-semibold text-muted-foreground mb-2 uppercase tracking-wider ui-label">
              AI Trading Signals
            </h3>
            <AISignalWidget />
          </div>

          {/* Bot Status Panel (if enabled) */}
          {layout.showBotStatus && (
            <div>
              <h3 className="text-xs font-semibold text-muted-foreground mb-2 uppercase tracking-wider ui-label">
                Bot Status
              </h3>
              <BotStatusPanel data={botStatus} loading={false} />
            </div>
          )}

          {/* Other panels... */}
        </div>
      </div>
    </div>
  </div>
);
```

## Alternative: Standalone Page

Create a dedicated AI Signals page:

```tsx
// frontend/src/pages/AISignals.tsx
import { AISignalWidget } from "@/components/AISignalWidget";
import { DashboardHeader } from "@/components/DashboardHeader";

const AISignalsPage = () => {
  return (
    <div className="min-h-screen bg-background">
      <DashboardHeader
        currentSymbol="SPY"
        onSymbolChange={() => {}}
        environment="production"
        equity={125000}
        dayPnl={650}
        dayPnlPct={0.52}
      />

      <div className="p-4 max-w-4xl mx-auto">
        <h2 className="text-2xl font-bold mb-6">AI Trading Signals</h2>
        
        <div className="space-y-6">
          <AISignalWidget />
          
          {/* Optional: Add more AI-related components here */}
        </div>
      </div>
    </div>
  );
};

export default AISignalsPage;
```

Then add the route:

```tsx
// frontend/src/App.tsx
import AISignalsPage from "@/pages/AISignals";

// In your routes
<Route path="/ai-signals" element={<AISignalsPage />} />
```

## Layout Control Integration

If using the layout context, add a toggle:

```tsx
// In your layout context/state
const [layout, setLayout] = useState({
  showAccountPanel: true,
  showBotStatus: true,
  showAISignals: true,  // Add this
  // ... other toggles
});

// In your component
{layout.showAISignals && (
  <div>
    <h3 className="text-xs font-semibold text-muted-foreground mb-2 uppercase tracking-wider ui-label">
      AI Trading Signals
    </h3>
    <AISignalWidget />
  </div>
)}
```

## Conditional Rendering

Show the widget only for certain users or conditions:

```tsx
// Show only in production environment
{accountData?.environment === "production" && (
  <div>
    <h3 className="text-xs font-semibold text-muted-foreground mb-2 uppercase tracking-wider ui-label">
      AI Trading Signals
    </h3>
    <AISignalWidget />
  </div>
)}

// Show only for authenticated users
{user && (
  <div>
    <h3 className="text-xs font-semibold text-muted-foreground mb-2 uppercase tracking-wider ui-label">
      AI Trading Signals
    </h3>
    <AISignalWidget />
  </div>
)}
```

## Using the Hook Directly

If you want to build a custom UI instead of using the widget:

```tsx
import { useAISignals } from "@/hooks/useAISignals";

const MyCustomSignalDisplay = () => {
  const { signal, loading, error, generateSignal } = useAISignals();

  return (
    <div>
      <button onClick={generateSignal} disabled={loading}>
        {loading ? "Loading..." : "Get Signal"}
      </button>

      {error && <div className="text-red-500">{error}</div>}

      {signal && (
        <div>
          <h3>Action: {signal.action}</h3>
          <p>Confidence: {(signal.confidence * 100).toFixed(0)}%</p>
          <p>Reasoning: {signal.reasoning}</p>
          <p>Target Allocation: {(signal.target_allocation * 100).toFixed(0)}%</p>
        </div>
      )}
    </div>
  );
};
```

## Testing After Integration

1. **Start the frontend**:
   ```bash
   cd frontend
   npm run dev
   ```

2. **Navigate to your dashboard** where you added the widget

3. **Click "Generate Fresh Signal"**

4. **Verify**:
   - ✅ Loading spinner appears
   - ✅ Signal displays with color-coded action
   - ✅ Confidence, reasoning, and allocation shown
   - ✅ Refresh page - signal loads instantly (warm cache)

## Troubleshooting

### Issue: Widget doesn't render
**Solution**: Check that you imported the component correctly
```tsx
import { AISignalWidget } from "@/components/AISignalWidget";
```

### Issue: "Cannot call Cloud Function"
**Solution**: Deploy the backend first
```bash
firebase deploy --only functions
```

### Issue: CORS error
**Solution**: Verify CORS is configured in `functions/main.py`
```python
@https_fn.on_call(
    cors=options.CorsOptions(cors_origins="*", cors_methods=["GET", "POST"])
)
```

### Issue: No signal appears
**Solution**: 
1. Check that `pulse` is running (updates `alpacaAccounts/snapshot`)
2. Check Cloud Functions logs: `firebase functions:log`
3. Open browser console for frontend errors

## Next Steps

After integration:
1. Deploy backend: `firebase deploy --only functions`
2. Test signal generation
3. Verify warm cache works (refresh page)
4. Check Firestore `tradingSignals` collection
5. Review Cloud Functions logs for any issues

## Production Checklist

Before production deployment:
- [ ] Update CORS to specific domain
- [ ] Add Firebase Authentication
- [ ] Implement rate limiting
- [ ] Test with real account data
- [ ] Monitor Vertex AI costs

**See**: `PRODUCTION_DEPLOYMENT_GUIDE.md` for complete checklist

---

**Integration is that simple! Just import and render. 🚀**
