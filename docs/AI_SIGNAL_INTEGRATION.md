# Phase 2: AI Signal Intelligence Integration

## Overview

This document describes the AI Signal Engine integration with Vertex AI Gemini and the React Dashboard.

## Backend Implementation

### 1. Files Modified

#### `functions/requirements.txt`
Added dependency:
```
google-cloud-aiplatform
```

#### `functions/main.py`
- **New Function**: `generate_trading_signal`
  - Type: HTTPS Callable (2nd Gen)
  - Model: Vertex AI `gemini-1.5-flash`
  - CORS: Configured with `cors_origins="*"`
  
**Flow**:
1. Reads latest account snapshot from `alpacaAccounts/snapshot`
2. Sends account data (equity, buying_power, cash) to Gemini
3. AI analyzes and returns JSON with:
   - `action`: "BUY" | "SELL" | "HOLD"
   - `confidence`: float (0-1)
   - `reasoning`: detailed explanation
   - `target_allocation`: suggested portfolio allocation percentage
4. Saves signal to `tradingSignals` Firestore collection
5. Returns signal with document ID to caller

### 2. Environment Variables Required

The backend function requires these environment variables:
- `GCP_PROJECT` or `GCLOUD_PROJECT`: Google Cloud project ID
- `GCP_REGION` (optional): defaults to "us-central1"
- Firestore must be initialized

### 3. Firestore Collections

**New Collection**: `tradingSignals`

Schema:
```typescript
{
  action: "BUY" | "SELL" | "HOLD",
  confidence: number,
  reasoning: string,
  target_allocation: number,
  timestamp: Timestamp,
  account_snapshot: {
    equity: string,
    buying_power: string,
    cash: string
  },
  id: string  // Document ID
}
```

## Frontend Implementation

### 1. New Hook: `useAISignals.ts`

Location: `frontend/src/hooks/useAISignals.ts`

**Usage**:
```typescript
import { useAISignals } from "@/hooks/useAISignals";

const MyComponent = () => {
  const { signal, loading, error, generateSignal } = useAISignals();
  
  // Call generateSignal() to fetch a new AI recommendation
  const handleGetSignal = async () => {
    await generateSignal();
  };
  
  // Display signal.action, signal.confidence, signal.reasoning
  return (
    <div>
      {signal && (
        <>
          <div>Action: {signal.action}</div>
          <div>Confidence: {(signal.confidence * 100).toFixed(0)}%</div>
          <div>Reasoning: {signal.reasoning}</div>
        </>
      )}
    </div>
  );
};
```

### 2. New Component: `AISignalWidget.tsx`

Location: `frontend/src/components/AISignalWidget.tsx`

**Features**:
- **Visual Indicators**: Color-coded action badges
  - BUY: Green
  - SELL: Red
  - HOLD: Amber
- **Confidence Display**: Progress bar showing AI confidence level
- **Target Allocation**: Suggested portfolio allocation percentage
- **AI Analysis Section**: Detailed reasoning from Gemini
- **Account Context**: Shows equity, buying power, and cash used for analysis
- **Refresh Button**: Manual trigger for new signal generation

**Integration Example**:

```tsx
import { AISignalWidget } from "@/components/AISignalWidget";

// In any page or dashboard:
<div className="space-y-4">
  <h3 className="text-xs font-semibold text-muted-foreground mb-2 uppercase tracking-wider ui-label">
    AI Trading Signals
  </h3>
  <AISignalWidget />
</div>
```

### 3. Adding to Dashboard

To add the AI Signal Widget to the main dashboard (`frontend/src/pages/Index.tsx`):

```tsx
// Add import at top
import { AISignalWidget } from "@/components/AISignalWidget";

// Add in the right column alongside AccountPanel and BotStatusPanel
{layout.showAccountPanel && (
  <div className="transition-all duration-300 animate-fade-in">
    <h3 className="text-xs font-semibold text-muted-foreground mb-2 uppercase tracking-wider ui-label">
      Account & Risk
    </h3>
    <AccountPanel data={effectiveAccountData} loading={false} />
  </div>
)}

{/* Add AI Signal Widget */}
<div className="transition-all duration-300 animate-fade-in">
  <h3 className="text-xs font-semibold text-muted-foreground mb-2 uppercase tracking-wider ui-label">
    AI Trading Signals
  </h3>
  <AISignalWidget />
</div>
```

## Deployment

### 1. Deploy Functions

```bash
cd /workspace
firebase deploy --only functions
```

This will deploy both:
- Existing `pulse` scheduler function
- New `generate_trading_signal` HTTPS callable function

### 2. Verify Deployment

Check Firebase Console:
- Navigate to Firebase Console → Functions
- Verify `generate_trading_signal` is deployed
- Check logs for any initialization errors

### 3. Test the Integration

1. Open the React dashboard
2. Navigate to the page with AISignalWidget
3. Click "Request Signal" button
4. Verify:
   - Loading state appears
   - AI generates signal successfully
   - Signal displays with action, confidence, and reasoning
   - Check Firestore `tradingSignals` collection for saved signals

## CORS Configuration

The backend function is configured with:
```python
@https_fn.on_call(
    cors=options.CorsOptions(cors_origins="*", cors_methods=["GET", "POST"])
)
```

For production, replace `"*"` with specific allowed origins:
```python
cors=options.CorsOptions(
    cors_origins=["https://yourdomain.com"],
    cors_methods=["POST"]
)
```

## Error Handling

### Backend
- Returns `HttpsError` with appropriate error codes
- Falls back to HOLD signal if AI response is unparseable
- Validates and sanitizes all AI outputs

### Frontend
- Displays error messages in red alert box
- Maintains previous signal during errors
- Shows loading spinner during generation

## Monitoring

### Firestore
Monitor the `tradingSignals` collection to see:
- Signal generation frequency
- Distribution of BUY/SELL/HOLD recommendations
- Confidence levels over time

### Function Logs
Check Cloud Functions logs for:
- Vertex AI API calls
- Error rates
- Response times

## Future Enhancements

1. **Historical Signal Tracking**: Display past signals and their outcomes
2. **Signal Execution**: One-click trade execution based on AI recommendations
3. **Backtesting**: Test AI signals against historical data
4. **Custom Parameters**: Allow users to adjust risk tolerance and allocation preferences
5. **Multi-Symbol Support**: Generate signals for multiple assets
6. **Real-time Updates**: Subscribe to signal collection for automatic updates

## Security Considerations

1. **Authentication**: Add Firebase Auth checks in the callable function
2. **Rate Limiting**: Implement rate limits to prevent abuse
3. **API Costs**: Monitor Vertex AI usage and implement cost controls
4. **Data Privacy**: Ensure account data is properly scoped per user

## Testing

Run the following checks before deploying to production:

1. ✅ Backend function deploys without errors
2. ✅ CORS is properly configured
3. ✅ Firestore permissions allow writes to `tradingSignals`
4. ✅ Vertex AI is initialized with valid project ID
5. ✅ Frontend successfully calls the function
6. ✅ UI displays signals correctly
7. ✅ Error states are handled gracefully

## Git Commit

After successful deployment:

```bash
git add .
git commit -m "Phase 2: Vertex AI Signal Integration Complete

- Added Vertex AI Gemini integration to backend
- Created generate_trading_signal Cloud Function
- Implemented useAISignals React hook
- Built AISignalWidget dashboard component
- Configured CORS for cross-origin requests
- Added tradingSignals Firestore collection"

# DO NOT push (remote environment will handle this automatically)
```

## Support

For issues or questions:
1. Check Cloud Functions logs in Firebase Console
2. Verify Vertex AI API is enabled in GCP
3. Ensure all environment variables are set correctly
4. Review CORS configuration if frontend calls fail
