# Multi-Tenant Migration Guide

This document describes the migration from a single-tenant to multi-tenant architecture in the AgentTrader project.

## Overview

The project has been refactored to support multiple users, each with their own Alpaca accounts and trading signals. The key changes are:

1. **Firestore schema changes**: `alpacaAccounts` and `tradingSignals` are now nested under `users/{userId}`
2. **Cloud Function updates**: The `pulse` function now iterates through all users
3. **Secret Manager integration**: Each user's API keys are stored in Secret Manager
4. **Backward compatibility**: Legacy paths are still supported during migration

## Architecture Changes

### Before (Single-Tenant)

```
alpacaAccounts/
  snapshot/
    - equity
    - buying_power
    - cash

tenants/{tenantId}/
  accounts/
    primary/
```

### After (Multi-Tenant)

```
users/{userId}/
  - email
  - created_at
  - displayName
  
  alpacaAccounts/
    snapshot/
      - equity
      - buying_power
      - cash
      - encrypted_key_path
  
  tradingSignals/{signalId}/
    - symbol
    - action
    - notional_usd
    - reason
    - status

tenants/{tenantId}/
  accounts/
    primary/  (still maintained for backward compatibility)
```

## Migration Steps

### 1. Set Up Secret Manager for Users

For each user, create a secret in Google Cloud Secret Manager:

```bash
# Create secret for user
USER_ID="user123"
echo '{"key_id": "YOUR_ALPACA_KEY", "secret_key": "YOUR_ALPACA_SECRET"}' | \
  gcloud secrets create alpaca-keys-${USER_ID} \
    --data-file=- \
    --replication-policy="automatic"
```

The secret name pattern is: `alpaca-keys-{USER_ID}`

### 2. Grant Secret Access to Cloud Functions

```bash
# Get the service account email for your Cloud Function
PROJECT_ID="your-project-id"
SERVICE_ACCOUNT="your-project@appspot.gserviceaccount.com"

# Grant access to all user secrets (or specific ones)
gcloud secrets add-iam-policy-binding alpaca-keys-USER_ID \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/secretmanager.secretAccessor"
```

### 3. Create User Documents in Firestore

For each user that should be synced, create a document in the `users` collection:

```javascript
// Using Firebase Admin SDK
await db.collection('users').doc(userId).set({
  email: 'user@example.com',
  created_at: admin.firestore.FieldValue.serverTimestamp(),
  displayName: 'John Doe'
});
```

### 4. Deploy Updated Cloud Function

The `pulse` function in `functions/main.py` has been updated to:
- Iterate through all documents in the `users` collection
- Fetch each user's API keys from Secret Manager
- Sync their Alpaca account to `users/{userId}/alpacaAccounts/snapshot`

Deploy the function:

```bash
cd functions
firebase deploy --only functions:pulse
```

### 5. Update Backend Code

If you have backend services that read from `alpacaAccounts/snapshot`, update them to:

```python
# Old way (deprecated)
snapshot = db.collection("alpacaAccounts").document("snapshot").get()

# New way (multi-tenant)
snapshot = db.collection("users").document(user_id).collection("alpacaAccounts").document("snapshot").get()
```

The helper functions in `backend/alpaca_signal_trader.py` now support a `user_id` parameter:

```python
# Generate signal with user-specific buying power
signal = generate_signal_with_warm_cache(
    symbol="SPY",
    market_context="...",
    user_id=user_id  # Add this parameter
)
```

### 6. Update Firestore Security Rules

The security rules have been updated to allow users to:
- Read/write their own user document
- Read their own Alpaca accounts (writes are backend-only)
- Read/write their own trading signals

Deploy the updated rules:

```bash
firebase deploy --only firestore:rules
```

## Backward Compatibility

During the migration period, the system supports both models:

### Backend Code
- `backend/alpaca_signal_trader.py`: Falls back to legacy `alpacaAccounts/snapshot` if no `user_id` is provided
- `backend/brokers/alpaca/account_sync.py`: Writes to both tenant-scoped and user-scoped paths

### Legacy Paths (Deprecated)
These paths are still supported but will be removed in a future release:
- `alpacaAccounts/snapshot` - Global account snapshot
- Environment variables: `APCA_API_KEY_ID`, `APCA_API_SECRET_KEY`

## Testing

### 1. Test Secret Manager Access

```python
from google.cloud import secretmanager
import json

client = secretmanager.SecretManagerServiceClient()
secret_name = "projects/PROJECT_ID/secrets/alpaca-keys-USER_ID/versions/latest"
response = client.access_secret_version(request={"name": secret_name})
keys = json.loads(response.payload.data.decode("UTF-8"))
print(f"Retrieved keys: {keys['key_id']}")
```

### 2. Test User Sync

Manually trigger the pulse function and check logs:

```bash
# View function logs
gcloud functions logs read pulse --limit 50
```

Expected output:
```
Syncing Alpaca account for user user123
Successfully synced Alpaca account for user user123
Completed multi-tenant sync: 1 successful, 0 errors
```

### 3. Verify Firestore Data

Check that data is being written to the correct paths:

```javascript
// Check user's account snapshot
const snapshot = await db
  .collection('users')
  .doc(userId)
  .collection('alpacaAccounts')
  .doc('snapshot')
  .get();

console.log('Equity:', snapshot.data().equity);
console.log('Buying Power:', snapshot.data().buying_power);
```

## Troubleshooting

### Error: "Missing GCP_PROJECT or GCLOUD_PROJECT environment variable"

Set the project ID in your Cloud Function environment:

```bash
gcloud functions deploy pulse --set-env-vars GCP_PROJECT=your-project-id
```

### Error: "Could not retrieve Alpaca keys for user X"

1. Verify the secret exists:
   ```bash
   gcloud secrets describe alpaca-keys-USER_ID
   ```

2. Verify service account has access:
   ```bash
   gcloud secrets get-iam-policy alpaca-keys-USER_ID
   ```

3. Check the secret payload format (must be valid JSON with `key_id` and `secret_key`)

### No Users Being Synced

1. Verify users exist in Firestore:
   ```javascript
   const users = await db.collection('users').get();
   console.log(`Found ${users.size} users`);
   ```

2. Check function logs for errors:
   ```bash
   gcloud functions logs read pulse --limit 100
   ```

## Security Considerations

### Secret Manager Best Practices

1. **Principle of Least Privilege**: Grant Secret Manager access only to service accounts that need it
2. **Secret Rotation**: Implement a process to rotate Alpaca API keys periodically
3. **Audit Logging**: Enable Cloud Audit Logs for Secret Manager access
4. **Secret Naming**: Use consistent naming pattern: `alpaca-keys-{USER_ID}`

### Firestore Security Rules

The updated rules ensure:
- Users can only access their own data
- Alpaca account writes are backend-only (Admin SDK)
- Trading signals can be read/written by the owning user
- No cross-user data access is possible

### API Key Storage

**Never store API keys in Firestore**. Always use Secret Manager:
- ✅ Store in Secret Manager: API keys, secret keys, passwords
- ✅ Store in Firestore: Account metadata, public configuration
- ❌ Never in Firestore: Credentials, private keys, tokens

## Performance Considerations

### Scaling

The `pulse` function iterates through all users sequentially. For better performance with many users:

1. **Batch Processing**: Process users in parallel batches
2. **Conditional Sync**: Only sync users with active strategies
3. **Distributed Processing**: Use Cloud Tasks or Pub/Sub for fan-out

Example optimization:

```python
import concurrent.futures

def pulse(event):
    users = list(db.collection("users").stream())
    
    # Process users in parallel (max 10 at a time)
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [
            executor.submit(_sync_user_account, db, user.id, project_id)
            for user in users
        ]
        concurrent.futures.wait(futures)
```

### Cost Optimization

- **Firestore Reads**: Each sync reads one document per user
- **Secret Manager Access**: Billed per access (consider caching for short periods)
- **Alpaca API Calls**: Rate limited to 200/minute (consider staggering syncs)

## Next Steps

1. **Frontend Updates**: Update React components to use user-scoped paths
2. **Strategy Engine**: Update to support per-user signal generation
3. **Monitoring**: Add metrics for per-user sync success/failure rates
4. **Data Migration**: Script to copy existing data to new user-scoped paths
5. **Cleanup**: Remove legacy global `alpacaAccounts/snapshot` after full migration

## References

- [Firestore Data Model](./FIRESTORE_DATA_MODEL.md)
- [Tenancy Model](./TENANCY_MODEL.md)
- [Secret Manager Documentation](https://cloud.google.com/secret-manager/docs)
- [Firebase Functions Documentation](https://firebase.google.com/docs/functions)
