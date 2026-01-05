# SaaS Platform Migration Guide

## Overview

This guide documents the transformation of the AgentTrader bot from a personal tool into a multi-tenant SaaS platform. The refactoring enables support for multiple users with isolated data, private API keys, and user-specific controls.

## Architecture Changes

### Database Structure (Before → After)

#### Before (Single User)
```
alpacaAccounts/
  └── snapshot/
      ├── syncedAt
      ├── account
      ├── equity
      ├── buying_power
      └── cash

tradingSignals/
  └── {signalId}/
      ├── createdAt
      ├── response
      └── ...
```

#### After (Multi-Tenant)
```
users/
  └── {userId}/
      ├── onboarded: true
      ├── onboardedAt: timestamp
      ├── email: string
      ├── config/
      │   └── alpaca/
      │       ├── configured: boolean
      │       └── instructions: string
      ├── secrets/
      │   └── alpaca/
      │       ├── key_id: string (encrypted)
      │       ├── secret_key: string (encrypted)
      │       └── base_url: string
      ├── status/
      │   ├── trading/
      │   │   ├── enabled: boolean (kill-switch)
      │   │   └── message: string
      │   └── last_sync_error/
      │       ├── error: string
      │       └── timestamp: timestamp
      ├── data/
      │   └── snapshot/
      │       ├── syncedAt: timestamp
      │       ├── account: object
      │       ├── equity: string
      │       ├── buying_power: string
      │       └── cash: string
      └── trading_signals/
          └── {signalId}/
              ├── createdAt: timestamp
              ├── userId: string
              ├── response: string
              └── ...

ops/
  └── last_pulse/
      ├── timestamp: timestamp
      ├── success_count: number
      ├── error_count: number
      └── skipped_count: number
```

## Key Features

### 1. Multi-Tenant Heartbeat (Pulse Function)

The `pulse` scheduled function now:
- Queries all users from the `users` collection
- Iterates through each user sequentially
- Fetches user-specific Alpaca API keys from `users/{userId}/secrets/alpaca`
- Checks user-specific kill-switch at `users/{userId}/status/trading`
- Syncs account data to `users/{userId}/data/snapshot`
- **Error Isolation**: One user's failure (e.g., invalid API keys) does not stop the loop for other users
- Logs aggregated statistics to `ops/last_pulse`

### 2. User-Specific Kill-Switch

Each user has their own kill-switch at:
```
users/{userId}/status/trading
{
  "enabled": boolean,
  "message": string,
  "createdAt": timestamp
}
```

- Default: `enabled: false` (trading disabled until user explicitly enables)
- The pulse function checks this before syncing each user's account
- Users can toggle this via the frontend to pause/resume trading

### 3. Tenant Onboarding

New callable function: `onboard_user`

**Called automatically after user sign-up** (integrate with Firebase Auth triggers or frontend).

Creates the following structure for new users:
- `users/{userId}` (root document with onboarded flag)
- `users/{userId}/config/alpaca` (placeholder for configuration)
- `users/{userId}/secrets/alpaca` (placeholder for API keys)
- `users/{userId}/status/trading` (kill-switch, disabled by default)
- `users/{userId}/data/snapshot` (empty placeholder)

### 4. User-Scoped Signal Generation

The `generate_trading_signal` function is now a **callable function** (not HTTP endpoint) that:
- Requires authentication via Firebase Auth
- Extracts `userId` from `request.auth.uid`
- Reads from `users/{userId}/data/snapshot`
- Stores signals in `users/{userId}/trading_signals/{signalId}`
- Includes `userId` in signal documents for audit trails

### 5. Data Migration Helper

New callable function: `migrate_legacy_data`

**Admin-only function** (requires `admin: true` custom claim) that:
- Migrates data from legacy `alpacaAccounts/snapshot` to `users/{targetUserId}/data/snapshot`
- Adds migration metadata (`migratedAt`, `migratedFrom`)
- Usage:
  ```javascript
  await functions.httpsCallable('migrate_legacy_data')({
    targetUserId: 'existing-user-uid'
  });
  ```

## Security Rules

### User-Scoped Access Control

All `users/{userId}/*` paths enforce:
```
function isOwner() {
  return signedIn() && request.auth.uid == userId;
}
```

This ensures:
- Users can only read/write their own data
- No cross-tenant data leakage
- Backend functions bypass rules via Admin SDK but still follow tenant scoping in application logic

### Secrets Collection

The `users/{userId}/secrets/*` collection:
- Is accessible by the owner only
- **Should be encrypted at rest** (use Firebase/GCP encryption)
- Consider migrating to **Google Cloud Secret Manager** for production

### Legacy Collections

Legacy collections (`alpacaAccounts`, `tradingSignals`) are now **read-only** for authenticated users during migration period.

## Migration Steps

### Step 1: Deploy New Functions

```bash
cd functions
firebase deploy --only functions
```

Deployed functions:
- `pulse` (scheduled, runs every minute)
- `generate_trading_signal` (callable, user-scoped)
- `onboard_user` (callable, initializes new users)
- `migrate_legacy_data` (callable, admin-only)

### Step 2: Deploy New Security Rules

```bash
firebase deploy --only firestore:rules
```

### Step 3: Onboard Existing Users

For each existing user:

```javascript
// 1. Call onboard_user
const result = await functions.httpsCallable('onboard_user')();

// 2. Manually add Alpaca API keys to Firestore
await db.collection('users').doc(userId).collection('secrets').doc('alpaca').set({
  key_id: 'YOUR_ALPACA_KEY_ID',
  secret_key: 'YOUR_ALPACA_SECRET_KEY',
  base_url: 'https://api.alpaca.markets' // or paper trading URL
});

// 3. Migrate legacy data (admin only)
await functions.httpsCallable('migrate_legacy_data')({
  targetUserId: userId
});

// 4. Enable trading
await db.collection('users').doc(userId).collection('status').doc('trading').update({
  enabled: true,
  message: 'Trading enabled'
});
```

### Step 4: Update Frontend

Update all Firestore queries to use user-scoped paths:

**Before:**
```javascript
const snapshot = await db.collection('alpacaAccounts').doc('snapshot').get();
```

**After:**
```javascript
const userId = auth.currentUser.uid;
const snapshot = await db.collection('users').doc(userId).collection('data').doc('snapshot').get();
```

### Step 5: Test Error Isolation

Create a test user with invalid API keys and verify:
1. The pulse function logs an error for that user
2. Other users continue to sync successfully
3. Error is stored in `users/{userId}/status/last_sync_error`

### Step 6: Monitor Ops Dashboard

Monitor the global sync status:
```javascript
db.collection('ops').doc('last_pulse')
  .onSnapshot(doc => {
    const { timestamp, success_count, error_count, skipped_count } = doc.data();
    console.log(`Pulse: ${success_count} success, ${error_count} errors, ${skipped_count} skipped`);
  });
```

## Architecture Verification Checklist

Based on the requirements:

- [x] **Verify that one user's failure does not stop the loop for other users**
  - Implemented via try-catch per user in the pulse function
  - Errors are logged and stored in user-specific `status/last_sync_error`
  - Loop continues to next user after error

- [x] **Ensure the kill-switch is now user-specific**
  - Path: `users/{userId}/status/trading`
  - Field: `enabled` (boolean)
  - Checked before each user's sync in pulse function
  - Default: `false` (disabled) for new users

- [x] **Database refactoring complete**
  - ✓ Migrated from `alpacaAccounts/snapshot` to `users/{userId}/data/snapshot`
  - ✓ Config at `users/{userId}/config/alpaca`
  - ✓ Secrets at `users/{userId}/secrets/alpaca`

- [x] **Backend scalability**
  - ✓ Pulse function queries all users
  - ✓ Fetches user-specific Alpaca keys
  - ✓ Syncs per-tenant data
  - ✓ Aggregates statistics to `ops/last_pulse`

- [x] **Security & Auth**
  - ✓ Security rules enforce `request.auth.uid == userId`
  - ✓ Tenant onboarding function (`onboard_user`)
  - ✓ User-scoped signal generation
  - ✓ Data migration helper (admin-only)

## Production Considerations

### 1. Secret Management

**Current**: Secrets stored in Firestore `users/{userId}/secrets/alpaca`

**Production Recommendation**: Migrate to Google Cloud Secret Manager
- Better encryption and key rotation
- Audit logging
- Integration with Cloud Functions

Example structure:
```
projects/{project-id}/secrets/alpaca-key-{userId}/versions/latest
projects/{project-id}/secrets/alpaca-secret-{userId}/versions/latest
```

### 2. Rate Limiting

Consider rate limiting per user:
- Alpaca API has rate limits (200 requests/minute)
- With many users, the pulse function may hit these limits
- Solution: Batch users, stagger syncs, or implement exponential backoff

### 3. Monitoring & Alerting

Set up Cloud Monitoring alerts for:
- High error rates in pulse function
- Users with consecutive sync failures
- Slow pulse execution times

### 4. Billing & Usage Tracking

Add to user documents:
```
users/{userId}/usage/
  └── {month}/
      ├── api_calls: number
      ├── signals_generated: number
      └── cost_usd: number
```

### 5. Testing Strategy

#### Unit Tests
- Test `_get_user_alpaca_keys` with missing/incomplete keys
- Test `_is_user_trading_enabled` with missing status doc
- Test error isolation in pulse function

#### Integration Tests
- Create test users with various configurations
- Verify pulse function handles errors gracefully
- Test onboarding flow end-to-end

#### Load Tests
- Simulate 100+ users
- Measure pulse function execution time
- Verify Firestore write patterns are efficient

## Frontend Integration

### Example: Subscribe to User's Account Snapshot

```typescript
import { useAuth } from '@/contexts/AuthContext';
import { useEffect, useState } from 'react';
import { db } from '@/firebase';

function useAccountSnapshot() {
  const { user } = useAuth();
  const [snapshot, setSnapshot] = useState(null);
  
  useEffect(() => {
    if (!user) return;
    
    const unsubscribe = db
      .collection('users')
      .doc(user.uid)
      .collection('data')
      .doc('snapshot')
      .onSnapshot(doc => {
        if (doc.exists) {
          setSnapshot(doc.data());
        }
      });
    
    return () => unsubscribe();
  }, [user]);
  
  return snapshot;
}
```

### Example: Toggle Trading Kill-Switch

```typescript
async function toggleTrading(enabled: boolean) {
  const userId = auth.currentUser.uid;
  
  await db
    .collection('users')
    .doc(userId)
    .collection('status')
    .doc('trading')
    .update({
      enabled,
      message: enabled ? 'Trading enabled' : 'Trading disabled',
      updatedAt: firebase.firestore.FieldValue.serverTimestamp()
    });
}
```

### Example: Generate Trading Signal

```typescript
import { functions } from '@/firebase';

async function generateSignal(marketConditions?: any) {
  const generateSignalFn = functions.httpsCallable('generate_trading_signal');
  
  const result = await generateSignalFn({
    marketConditions
  });
  
  return result.data; // { id, response, snapshotPath }
}
```

## Rollback Plan

If issues arise, you can rollback by:

1. **Revert functions**:
   ```bash
   firebase functions:log  # Check for errors
   firebase functions:config:clone --from <previous-version>
   ```

2. **Revert security rules**:
   ```bash
   git checkout HEAD~1 firestore.rules
   firebase deploy --only firestore:rules
   ```

3. **Keep legacy collections** accessible (already read-only for backward compatibility)

## Cost Estimates

### Firestore Writes
- Pulse function: 1 write/user/minute
- 100 users: 144,000 writes/day
- Cost: ~$0.26/day ($7.80/month)

### Cloud Functions
- Pulse invocations: 1,440/day
- Signal generations: Variable (user-initiated)
- Cost: Typically under $10/month for moderate usage

### Vertex AI (Gemini)
- Signal generations: Variable per user
- Cost: ~$0.00025 per request (Gemini 2.5 Flash)

## Support & Troubleshooting

### Common Issues

**Issue**: User's account not syncing
- Check: `users/{userId}/status/trading` → `enabled: true`?
- Check: `users/{userId}/secrets/alpaca` → Keys configured?
- Check: `users/{userId}/status/last_sync_error` → Recent errors?

**Issue**: "Authentication required" error
- Ensure user is signed in
- Verify ID token is not expired
- Check security rules are deployed

**Issue**: Pulse function timing out
- Too many users to sync in 60 seconds?
- Consider batching or increasing timeout
- Check Cloud Functions logs for slow API calls

## Next Steps

1. **Implement Google Cloud Secret Manager integration** for production-grade secret storage
2. **Add usage tracking and billing** (per-user API call limits, subscription tiers)
3. **Build admin dashboard** to monitor all users, view sync status, handle support tickets
4. **Add webhook support** for real-time trade notifications per user
5. **Implement rate limiting** to prevent abuse
6. **Add user settings page** in frontend to manage API keys and preferences

## Resources

- [Firebase Custom Claims](https://firebase.google.com/docs/auth/admin/custom-claims)
- [Firestore Security Rules](https://firebase.google.com/docs/firestore/security/get-started)
- [Google Cloud Secret Manager](https://cloud.google.com/secret-manager)
- [Cloud Functions Best Practices](https://cloud.google.com/functions/docs/bestpractices/tips)

---

**Migration Date**: December 30, 2025
**Version**: 2.0.0 (Multi-Tenant SaaS)
