# Multi-Tenant SaaS Functions

This document explains the multi-tenant architecture for Firebase Cloud Functions that powers the AgentTrader SaaS platform.

## Overview

The functions have been refactored to support multiple users with:
- **Isolated data**: Each user has their own Firestore paths
- **Private API keys**: User-specific Alpaca credentials
- **User-specific controls**: Individual kill-switches and settings
- **Error isolation**: One user's failure doesn't affect others

## Functions

### 1. `pulse` (Scheduled Function)

**Schedule**: Every 1 minute (`* * * * *`)

**Purpose**: Multi-tenant heartbeat that syncs Alpaca accounts for all users.

**Flow**:
1. Queries all users from `users` collection
2. For each user:
   - Checks kill-switch at `users/{userId}/status/trading`
   - Fetches API keys from `users/{userId}/secrets/alpaca`
   - Creates user-specific Alpaca client
   - Syncs account data to `users/{userId}/data/snapshot`
   - Isolates errors (one user's failure doesn't stop others)
3. Stores aggregated statistics in `ops/last_pulse`

**Error Handling**:
- Per-user try-catch blocks
- Errors logged and stored in `users/{userId}/status/last_sync_error`
- Loop continues to next user after error

**Monitoring**:
```javascript
// Subscribe to global pulse status
db.collection('ops').doc('last_pulse')
  .onSnapshot(doc => {
    const { timestamp, success_count, error_count, skipped_count } = doc.data();
    console.log(`Pulse: ${success_count} success, ${error_count} errors, ${skipped_count} skipped`);
  });
```

---

### 2. `generate_trading_signal` (Callable Function)

**Purpose**: Generate AI trading signals for authenticated users.

**Authentication**: Required (Firebase Auth)

**Input**:
```typescript
{
  marketConditions?: any  // Optional market context
}
```

**Output**:
```typescript
{
  id: string,              // Signal document ID
  response: string,        // AI-generated signal
  snapshotPath: string     // Source snapshot path
}
```

**Flow**:
1. Extracts `userId` from `request.auth.uid`
2. Reads snapshot from `users/{userId}/data/snapshot`
3. Calls Vertex AI (Gemini 2.5 Flash)
4. Stores signal in `users/{userId}/trading_signals/{signalId}`

**Usage**:
```typescript
import { functions } from '@/firebase';

async function generateSignal(marketConditions?: any) {
  const generateSignalFn = functions.httpsCallable('generate_trading_signal');
  
  try {
    const result = await generateSignalFn({ marketConditions });
    console.log('Signal:', result.data.response);
    return result.data;
  } catch (error) {
    console.error('Failed to generate signal:', error);
    throw error;
  }
}
```

---

### 3. `onboard_user` (Callable Function)

**Purpose**: Initialize Firestore structure for new users.

**Authentication**: Required (Firebase Auth)

**Creates**:
- `users/{userId}` - Root document with onboarded flag
- `users/{userId}/config/alpaca` - Configuration placeholder
- `users/{userId}/secrets/alpaca` - API keys placeholder
- `users/{userId}/status/trading` - Kill-switch (disabled by default)
- `users/{userId}/data/snapshot` - Empty snapshot placeholder

**Output**:
```typescript
{
  status: 'success' | 'already_onboarded',
  userId: string,
  message: string,
  next_steps?: string[]
}
```

**Usage**:
```typescript
import { functions } from '@/firebase';

async function onboardNewUser() {
  const onboardFn = functions.httpsCallable('onboard_user');
  
  try {
    const result = await onboardFn();
    console.log('Onboarding result:', result.data);
    
    if (result.data.status === 'success') {
      // Redirect user to API key setup page
      router.push('/settings/api-keys');
    }
  } catch (error) {
    console.error('Onboarding failed:', error);
  }
}
```

**Integration**: Call this function after user signs up via Firebase Auth.

---

### 4. `migrate_legacy_data` (Callable Function)

**Purpose**: Migrate data from legacy single-user structure to multi-tenant structure.

**Authentication**: Required (Firebase Auth + admin custom claim)

**Input**:
```typescript
{
  targetUserId: string  // User ID to migrate data to
}
```

**Output**:
```typescript
{
  status: 'success',
  targetUserId: string,
  message: string,
  migratedFields: string[]
}
```

**Usage** (Admin only):
```typescript
import { functions } from '@/firebase';

async function migrateLegacyData(targetUserId: string) {
  const migrateFn = functions.httpsCallable('migrate_legacy_data');
  
  try {
    const result = await migrateFn({ targetUserId });
    console.log('Migration result:', result.data);
  } catch (error) {
    if (error.code === 'permission-denied') {
      console.error('Admin access required');
    } else {
      console.error('Migration failed:', error);
    }
  }
}
```

**Note**: This function requires an admin custom claim. Set it via:
```javascript
// Backend (Admin SDK)
await admin.auth().setCustomUserClaims(uid, { admin: true });
```

---

## Firestore Structure

### User Documents

```
users/
  └── {userId}/
      ├── onboarded: boolean
      ├── onboardedAt: timestamp
      ├── email: string
      │
      ├── config/
      │   └── alpaca/
      │       ├── configured: boolean
      │       ├── createdAt: timestamp
      │       └── instructions: string
      │
      ├── secrets/
      │   └── alpaca/
      │       ├── key_id: string
      │       ├── secret_key: string
      │       └── base_url: string
      │
      ├── status/
      │   ├── trading/
      │   │   ├── enabled: boolean (kill-switch)
      │   │   ├── message: string
      │   │   └── createdAt: timestamp
      │   └── last_sync_error/
      │       ├── error: string
      │       └── timestamp: timestamp
      │
      ├── data/
      │   └── snapshot/
      │       ├── syncedAt: timestamp
      │       ├── account: object
      │       ├── equity: string
      │       ├── buying_power: string
      │       └── cash: string
      │
      └── trading_signals/
          └── {signalId}/
              ├── createdAt: timestamp
              ├── userId: string
              ├── response: string
              ├── prompt: string
              └── vertex: object
```

### Ops Documents

```
ops/
  └── last_pulse/
      ├── timestamp: timestamp
      ├── success_count: number
      ├── error_count: number
      └── skipped_count: number
```

---

## Setup Guide

### 1. Deploy Functions

```bash
cd functions
pip install -r requirements.txt
firebase deploy --only functions
```

### 2. Set Up Vertex AI (Optional, for AI signals)

```bash
# Set environment variables
firebase functions:config:set \
  vertex.project_id="YOUR_GCP_PROJECT_ID" \
  vertex.location="us-central1" \
  vertex.model_id="gemini-2.5-flash"

# Redeploy
firebase deploy --only functions
```

### 3. Configure Security Rules

```bash
firebase deploy --only firestore:rules
```

### 4. Onboard First User

```javascript
// Frontend (after user signs up)
import { auth, functions } from '@/firebase';

// User signs up
await auth.createUserWithEmailAndPassword(email, password);

// Onboard user (creates Firestore structure)
const onboardFn = functions.httpsCallable('onboard_user');
await onboardFn();

// User adds API keys via settings page
await db.collection('users').doc(auth.currentUser.uid)
  .collection('secrets').doc('alpaca').set({
    key_id: 'YOUR_ALPACA_KEY_ID',
    secret_key: 'YOUR_ALPACA_SECRET_KEY',
    base_url: 'https://paper-api.alpaca.markets'
  });

// Enable trading
await db.collection('users').doc(auth.currentUser.uid)
  .collection('status').doc('trading').update({
    enabled: true,
    message: 'Trading enabled'
  });
```

---

## Testing

### Manual Testing

Use the test script:

```bash
cd functions
python test_multitenancy.py
```

**Options**:
1. Create test users (with different configurations)
2. Verify error isolation (after pulse runs)
3. Cleanup test users
4. Run all (automated)

### Unit Tests

```bash
cd /workspace
pytest tests/test_pulse_multitenancy.py
```

### Integration Tests

```bash
pytest tests/test_integration_multitenancy.py
```

---

## Monitoring

### Cloud Monitoring Dashboard

**Recommended Metrics**:
- Function invocations (pulse, generate_trading_signal, onboard_user)
- Function errors
- Function execution time (P50, P95, P99)
- Firestore read/write operations

### Alerts

Set up alerts for:
1. **High error rate**: If `error_count / (success_count + error_count)` > 0.1
2. **Function timeout**: If execution time > 45 seconds
3. **API key issues**: If multiple users have consecutive sync failures

### Logs

```bash
# View pulse function logs
firebase functions:log --only pulse

# View all function logs
firebase functions:log

# Filter by user
firebase functions:log | grep "User user_123"
```

---

## Troubleshooting

### Issue: Pulse function timing out

**Symptoms**: Function execution time > 60 seconds

**Solutions**:
1. Increase function timeout:
   ```python
   @scheduler_fn.on_schedule(
       schedule="* * * * *",
       timeout_sec=300  # 5 minutes
   )
   ```

2. Batch users across multiple invocations

3. Optimize Alpaca API calls (use bulk endpoints if available)

### Issue: User's account not syncing

**Diagnosis**:
1. Check kill-switch: `users/{userId}/status/trading` → `enabled: true`?
2. Check API keys: `users/{userId}/secrets/alpaca` → Keys configured?
3. Check errors: `users/{userId}/status/last_sync_error` → Recent errors?

**Solutions**:
- Enable kill-switch if disabled
- Verify API keys are valid (test in Alpaca dashboard)
- Check Alpaca API status (may be down)

### Issue: "Authentication required" error

**Diagnosis**:
- User not signed in
- ID token expired
- Security rules not deployed

**Solutions**:
- Ensure user is signed in via Firebase Auth
- Refresh ID token: `await auth.currentUser.getIdToken(true)`
- Redeploy security rules: `firebase deploy --only firestore:rules`

### Issue: Permission denied on secrets collection

**Diagnosis**:
- Security rules not allowing access
- Wrong user ID in path

**Solutions**:
- Verify security rules are deployed
- Ensure path uses correct user ID: `users/{auth.currentUser.uid}/secrets/alpaca`

---

## Performance Optimization

### Reduce Firestore Costs

1. **Throttle pulse frequency** (if real-time sync not needed):
   ```python
   # Change from every minute to every 5 minutes
   @scheduler_fn.on_schedule(schedule="*/5 * * * *")
   ```

2. **Batch reads/writes** (future enhancement):
   - Use Firestore batched writes
   - Reduce individual document writes

3. **Cache API keys** (future enhancement):
   - Cache user API keys in Cloud Memorystore
   - Reduce Firestore reads

### Reduce Alpaca API Calls

1. **Skip users with no positions** (future enhancement):
   - Check if user has open positions before syncing
   - Reduce unnecessary API calls

2. **Use webhooks** (future enhancement):
   - Subscribe to Alpaca account webhooks
   - Only sync on actual changes

---

## Security Best Practices

### API Key Storage

**Current**: Stored in Firestore `users/{userId}/secrets/alpaca`

**Production**: Migrate to Google Cloud Secret Manager
```python
from google.cloud import secretmanager

def _get_user_alpaca_keys_from_secret_manager(project_id: str, user_id: str):
    client = secretmanager.SecretManagerServiceClient()
    
    key_name = f"projects/{project_id}/secrets/alpaca-key-{user_id}/versions/latest"
    secret_name = f"projects/{project_id}/secrets/alpaca-secret-{user_id}/versions/latest"
    
    key_response = client.access_secret_version(request={"name": key_name})
    secret_response = client.access_secret_version(request={"name": secret_name})
    
    return {
        "key_id": key_response.payload.data.decode("UTF-8"),
        "secret_key": secret_response.payload.data.decode("UTF-8"),
        "base_url": "https://api.alpaca.markets"
    }
```

### Rate Limiting

**Prevent abuse** (future enhancement):
- Limit AI signal generation to N requests per user per day
- Track usage in `users/{userId}/usage/{month}`
- Implement quota enforcement

### Audit Logging

**Track sensitive operations** (future enhancement):
- Log API key changes
- Log kill-switch toggles
- Log large trades

---

## Migration from Single-User

If you have existing data in the legacy structure:

1. **Identify your primary user**:
   - The user whose data is currently in `alpacaAccounts/snapshot`

2. **Set admin claim** (backend):
   ```javascript
   await admin.auth().setCustomUserClaims(uid, { admin: true });
   ```

3. **Run migration**:
   ```typescript
   const migrateFn = functions.httpsCallable('migrate_legacy_data');
   await migrateFn({ targetUserId: 'your-user-id' });
   ```

4. **Verify**:
   - Check `users/{userId}/data/snapshot` has data
   - Wait for next pulse cycle
   - Confirm account is syncing

---

## Future Enhancements

1. **Google Cloud Secret Manager integration** for secure API key storage
2. **Usage tracking and billing** (per-user API call limits)
3. **Admin dashboard** to monitor all users
4. **Webhook support** for real-time trade notifications
5. **Rate limiting** to prevent abuse
6. **Batch processing** for 500+ users
7. **Caching layer** (Redis/Memorystore) for API keys and config

---

## Support

For issues or questions:
- Check logs: `firebase functions:log`
- Review security rules: `firestore.rules`
- Run test script: `python test_multitenancy.py`
- See architecture docs: `SAAS_MIGRATION_GUIDE.md`, `SAAS_ARCHITECTURE_VERIFICATION.md`

---

**Version**: 2.0.0 (Multi-Tenant SaaS)
**Last Updated**: December 30, 2025
