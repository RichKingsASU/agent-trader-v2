# Multi-Tenant API Reference

Quick reference guide for using the multi-tenant APIs in AgentTrader.

## Firestore Paths

### User Data Structure

```
users/{userId}/
├── (root document)           # User metadata
├── alpacaAccounts/
│   └── snapshot/            # Account snapshot with buying power
└── tradingSignals/
    └── {signalId}/          # Trading signals for this user
```

### Reading User Account Data

```python
from backend.persistence.firebase_client import get_firestore_client

db = get_firestore_client()

# Read user's account snapshot
user_id = "user123"
account_ref = (
    db.collection("users")
    .document(user_id)
    .collection("alpacaAccounts")
    .document("snapshot")
)
account_data = account_ref.get().to_dict()

print(f"Buying Power: ${account_data['buying_power']}")
print(f"Equity: ${account_data['equity']}")
print(f"Cash: ${account_data['cash']}")
```

### Writing Trading Signals

```python
from google.cloud import firestore

db = get_firestore_client()

signal_data = {
    "created_at": firestore.SERVER_TIMESTAMP,
    "symbol": "SPY",
    "action": "buy",
    "notional_usd": 1000.00,
    "reason": "Strong momentum signal",
    "status": "pending",
    "strategy_id": "delta_momentum_v1"
}

signal_ref = (
    db.collection("users")
    .document(user_id)
    .collection("tradingSignals")
    .document()  # Auto-generate ID
)
signal_ref.set(signal_data)
```

## Backend Helper Functions

### Generate Trading Signal (with Buying Power Check)

```python
from backend.alpaca_signal_trader import generate_signal_with_warm_cache

# Generate signal for specific user
signal = generate_signal_with_warm_cache(
    symbol="SPY",
    market_context="Market is trending upward with strong volume",
    user_id="user123"  # ⚠️ Required for multi-tenant
)

print(f"Action: {signal.action}")
print(f"Notional: ${signal.notional_usd}")
print(f"Reason: {signal.reason}")
```

### Get User Buying Power

```python
from backend.alpaca_signal_trader import get_warm_cache_buying_power_usd

# Get buying power for specific user
buying_power, snapshot = get_warm_cache_buying_power_usd(
    user_id="user123"  # ⚠️ Required for multi-tenant
)

print(f"Available Buying Power: ${buying_power:,.2f}")
```

### Sync User Account

```python
from backend.brokers.alpaca.account_sync import syncAlpacaAccount

# Sync account for specific user
# (API keys should be in Secret Manager)
payload = syncAlpacaAccount(
    user_id="user123",  # ⚠️ Required for multi-tenant
    alpaca_api_key="...",      # Optional: if not in env/Secret Manager
    alpaca_secret_key="...",   # Optional: if not in env/Secret Manager
)

print(f"Synced account: {payload['external_account_id']}")
```

## Secret Manager

### Secret Naming Convention

```
projects/{PROJECT_ID}/secrets/alpaca-keys-{USER_ID}/versions/latest
```

### Secret Payload Format

```json
{
  "key_id": "PKXXX...",
  "secret_key": "yyy..."
}
```

### Creating a User Secret

```bash
# Create JSON file with keys
cat > keys.json <<EOF
{
  "key_id": "YOUR_ALPACA_API_KEY",
  "secret_key": "YOUR_ALPACA_SECRET_KEY"
}
EOF

# Create secret
USER_ID="user123"
gcloud secrets create alpaca-keys-${USER_ID} \
  --data-file=keys.json \
  --replication-policy="automatic"

# Clean up
rm keys.json

# Grant access to Cloud Function service account
SERVICE_ACCOUNT="your-project@appspot.gserviceaccount.com"
gcloud secrets add-iam-policy-binding alpaca-keys-${USER_ID} \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/secretmanager.secretAccessor"
```

### Reading a Secret (Python)

```python
from google.cloud import secretmanager
import json
import os

def get_user_alpaca_keys(user_id: str) -> dict:
    """Fetch Alpaca API keys for a user from Secret Manager."""
    client = secretmanager.SecretManagerServiceClient()
    project_id = os.environ.get("GCP_PROJECT")
    
    secret_name = f"projects/{project_id}/secrets/alpaca-keys-{user_id}/versions/latest"
    response = client.access_secret_version(request={"name": secret_name})
    
    payload = response.payload.data.decode("UTF-8")
    keys = json.loads(payload)
    
    return keys  # {"key_id": "...", "secret_key": "..."}
```

## Firestore Security Rules

### User Data Access

Users can only access their own data:

```javascript
// ✅ Allowed: User reading their own data
match /users/{userId}/alpacaAccounts/{accountId} {
  allow read: if request.auth.uid == userId;
}

// ❌ Denied: User trying to read another user's data
// Rules automatically prevent this

// ✅ Allowed: User writing their own signals
match /users/{userId}/tradingSignals/{signalId} {
  allow write: if request.auth.uid == userId;
}

// ❌ Denied: User writing Alpaca accounts (backend only)
match /users/{userId}/alpacaAccounts/{accountId} {
  allow write: if false;  // Only Admin SDK can write
}
```

### Querying User Data (Client SDK)

```javascript
// ✅ Frontend example (React)
import { collection, doc, getDoc, query, where, getDocs } from 'firebase/firestore';

// Get authenticated user's ID
const userId = auth.currentUser.uid;

// Read account snapshot
const accountRef = doc(db, 'users', userId, 'alpacaAccounts', 'snapshot');
const accountSnap = await getDoc(accountRef);
console.log('Buying Power:', accountSnap.data().buying_power);

// Query user's trading signals
const signalsRef = collection(db, 'users', userId, 'tradingSignals');
const q = query(signalsRef, where('status', '==', 'pending'));
const querySnapshot = await getDocs(q);
querySnapshot.forEach((doc) => {
  console.log('Signal:', doc.data());
});
```

## Cloud Functions

### Setting Up Environment Variables

```bash
# Deploy with project ID
gcloud functions deploy pulse \
  --set-env-vars GCP_PROJECT=your-project-id
```

### Function Structure

The `pulse` function runs every minute and syncs all users:

```python
@scheduler_fn.on_schedule(schedule="* * * * *")
def pulse(event):
    db = _get_firestore()
    project_id = os.environ.get("GCP_PROJECT")
    
    # Get all users
    users = db.collection("users").stream()
    
    for user_doc in users:
        user_id = user_doc.id
        try:
            # Fetch keys from Secret Manager
            keys = _get_user_alpaca_keys(user_id, project_id)
            
            # Create Alpaca client with user's keys
            api = tradeapi.REST(
                key_id=keys["key_id"],
                secret_key=keys["secret_key"]
            )
            
            # Fetch account
            account = api.get_account()
            
            # Write to user's Firestore path
            db.collection("users").document(user_id).collection("alpacaAccounts").document("snapshot").set(payload)
        except Exception as e:
            logger.error(f"Error syncing user {user_id}: {e}")
            continue  # Continue with other users
```

## Migration from Legacy Code

### Before (Single-Tenant)

```python
# ❌ Old way - global path
from backend.alpaca_signal_trader import generate_signal_with_warm_cache

signal = generate_signal_with_warm_cache(
    symbol="SPY",
    market_context="..."
)  # Uses alpacaAccounts/snapshot (deprecated)
```

### After (Multi-Tenant)

```python
# ✅ New way - user-scoped
from backend.alpaca_signal_trader import generate_signal_with_warm_cache

signal = generate_signal_with_warm_cache(
    symbol="SPY",
    market_context="...",
    user_id="user123"  # Add this parameter
)  # Uses users/user123/alpacaAccounts/snapshot
```

## Common Patterns

### Pattern 1: Process All Users

```python
def process_all_users():
    """Process trading logic for all users."""
    db = get_firestore_client()
    users = db.collection("users").stream()
    
    for user_doc in users:
        user_id = user_doc.id
        try:
            process_user(user_id)
        except Exception as e:
            logger.error(f"Error processing user {user_id}: {e}")
            continue
```

### Pattern 2: User Context Manager

```python
from contextlib import contextmanager

@contextmanager
def user_context(user_id: str):
    """Provide a context with user-specific resources."""
    db = get_firestore_client()
    user_ref = db.collection("users").document(user_id)
    
    yield {
        "db": db,
        "user_ref": user_ref,
        "account_ref": user_ref.collection("alpacaAccounts").document("snapshot"),
        "signals_ref": user_ref.collection("tradingSignals")
    }

# Usage
with user_context("user123") as ctx:
    account = ctx["account_ref"].get().to_dict()
    print(f"Buying Power: {account['buying_power']}")
```

### Pattern 3: Batch Write User Signals

```python
def write_signals_batch(user_id: str, signals: list):
    """Write multiple signals for a user in a batch."""
    db = get_firestore_client()
    batch = db.batch()
    
    signals_ref = db.collection("users").document(user_id).collection("tradingSignals")
    
    for signal_data in signals:
        signal_ref = signals_ref.document()  # Auto-generate ID
        batch.set(signal_ref, signal_data)
    
    batch.commit()
```

## Testing

### Unit Test with Mock User

```python
import pytest
from unittest.mock import MagicMock, patch

def test_generate_signal_for_user():
    """Test signal generation for a specific user."""
    mock_db = MagicMock()
    
    # Mock Firestore response
    mock_snapshot = MagicMock()
    mock_snapshot.exists = True
    mock_snapshot.to_dict.return_value = {
        "buying_power": "10000.00",
        "equity": "15000.00",
        "updated_at_iso": "2025-12-30T12:00:00Z"
    }
    
    with patch("backend.alpaca_signal_trader.get_firestore_client", return_value=mock_db):
        mock_db.collection.return_value.document.return_value.collection.return_value.document.return_value.get.return_value = mock_snapshot
        
        signal = generate_signal_with_warm_cache(
            symbol="SPY",
            market_context="Test context",
            user_id="test_user",
            db=mock_db
        )
        
        assert signal is not None
        assert signal.symbol == "SPY"
```

### Integration Test

```python
def test_user_sync_integration():
    """Integration test for user account sync."""
    user_id = "test_user"
    
    # 1. Create user document
    db = get_firestore_client()
    db.collection("users").document(user_id).set({
        "email": "test@example.com",
        "created_at": firestore.SERVER_TIMESTAMP
    })
    
    # 2. Sync account (requires Secret Manager setup)
    payload = syncAlpacaAccount(user_id=user_id)
    
    # 3. Verify data written
    account_ref = db.collection("users").document(user_id).collection("alpacaAccounts").document("snapshot")
    account_data = account_ref.get().to_dict()
    
    assert account_data is not None
    assert "buying_power" in account_data
    assert "equity" in account_data
```

## Troubleshooting

### Error: "Missing warm-cache snapshot"

```python
# Problem: No account snapshot exists for user
# Solution: Run sync first or check user_id
from backend.brokers.alpaca.account_sync import syncAlpacaAccount

syncAlpacaAccount(user_id="user123")
```

### Error: "Could not retrieve Alpaca keys for user X"

```bash
# Problem: Secret doesn't exist or no access
# Solution: Check secret exists and has correct IAM

# List secrets
gcloud secrets list --filter="name:alpaca-keys-"

# Check IAM policy
gcloud secrets get-iam-policy alpaca-keys-user123

# Add accessor role if missing
gcloud secrets add-iam-policy-binding alpaca-keys-user123 \
  --member="serviceAccount:YOUR_SA@appspot.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

### Error: "User ID not provided"

```python
# Problem: Calling multi-tenant function without user_id
# Solution: Always pass user_id for multi-tenant APIs

# ❌ Wrong
signal = generate_signal_with_warm_cache(symbol="SPY", market_context="...")

# ✅ Correct
signal = generate_signal_with_warm_cache(
    symbol="SPY", 
    market_context="...",
    user_id="user123"
)
```

## Best Practices

1. **Always pass `user_id`** to multi-tenant functions
2. **Never store API keys in Firestore** - use Secret Manager
3. **Handle user iteration errors gracefully** - don't fail entire batch
4. **Log user context** in error messages for debugging
5. **Use Admin SDK** for backend writes (bypasses security rules)
6. **Validate user_id** before processing (check user exists)
7. **Consider rate limits** when iterating through many users
8. **Use batch operations** when writing multiple documents

## Quick Links

- [Migration Guide](../MULTI_TENANT_MIGRATION.md)
- [Refactoring Summary](../MULTI_TENANT_REFACTORING_SUMMARY.md)
- [Firestore Data Model](../FIRESTORE_DATA_MODEL.md)
- [Tenancy Model](../TENANCY_MODEL.md)
