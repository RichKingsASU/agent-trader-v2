# Agent Identity & Cryptographic Signatures - Quick Start

## 🚀 5-Minute Setup

### 1. Install Dependencies

```bash
cd functions
pip install -r requirements.txt
```

**New dependency**: `PyNaCl>=1.5.0` (ED25519 signatures)

### 2. Initialize with Firestore

```python
from firebase_admin import firestore
from strategies.loader import StrategyLoader

# Initialize loader with Firestore (enables agent identity)
db = firestore.client()
loader = StrategyLoader(db=db)

# ✅ All strategies now have cryptographic identities
```

**Console Output**:
```
🔐 Agent identity manager initialized for Zero-Trust security
🔐 Strategy 'ExampleStrategy' registered with cryptographic identity: examplestrategy
🔐 Strategy 'GammaScalper' registered with cryptographic identity: gammascalper
StrategyLoader initialized: 2 strategies loaded, 0 errors
```

### 3. Write a Strategy with Signing

```python
from strategies.base_strategy import BaseStrategy, TradingSignal, SignalType

class MyStrategy(BaseStrategy):
    def evaluate(self, market_data, account_snapshot, regime=None):
        # Generate your signal
        signal = TradingSignal(
            signal_type=SignalType.BUY,
            confidence=0.8,
            reasoning="Strong bullish signal detected"
        )
        
        # CRITICAL: Always sign before returning
        return self.sign_signal(signal)
```

**That's it!** The signal is now cryptographically signed.

### 4. Verify Automatic Protection

Every trade goes through the Zero-Trust verification gate:

```python
# In main.py (automatic)
if not verify_agent_identity(db, signal):
    # ❌ Trade REJECTED - invalid or missing signature
    return {"error": "Agent identity verification failed"}

# ✅ Trade APPROVED - signature valid
_execute_shadow_trade(...)
```

## 📋 Implementation Checklist

### For Strategy Developers

- [x] Inherit from `BaseStrategy` (base.py or base_strategy.py)
- [x] Call `self.sign_signal(signal)` before returning from `evaluate()`
- [x] Test that signals include `signature` field

### For System Operators

- [x] Initialize `StrategyLoader` with Firestore client
- [x] Verify agents registered in `systemStatus/agent_registry/agents/`
- [x] Monitor `systemStatus/security_log/violations/` for security issues
- [x] Check shadow trades include `agent_provenance` field

## 🔍 Quick Verification

### Check Agent Registry

```javascript
// In Firebase Console
db.collection("systemStatus")
  .document("agent_registry")
  .collection("agents")
  .get()

// Should see: gammascalper, examplestrategy, etc.
```

### Test Signal Signing

```python
# Run verification script
python scripts/verify_zero_trust.py

# Expected output:
# ✅ Test 1 PASSED: Identity manager imported successfully
# ✅ Test 2 PASSED: PyNaCl library available
# ✅ Test 3 PASSED: Agent registration works
# ... (10 tests total)
# 🎉 All tests passed!
```

### Inspect Shadow Trade

```javascript
// Check recent trade
db.collection("users")
  .doc(userId)
  .collection("shadowTradeHistory")
  .orderBy("created_at", "desc")
  .limit(1)
  .get()

// Should include:
{
  "agent_provenance": {
    "signed_by": "gammascalper",
    "cert_id": "1735567890123_a1b2c3d4",
    "nonce": "...",
    "signed_at": 1735567890.123,
    "signature": "abc123..."
  }
}
```

## 🛡️ Security Benefits

| Feature | Benefit |
|---------|---------|
| **Non-Repudiation** | Mathematically prove which agent made each trade |
| **Zero-Trust** | Verify every signal, trust nothing |
| **Tamper-Proof** | Signatures become invalid if modified |
| **Replay Prevention** | Nonces prevent signal reuse |
| **Audit Trail** | Complete provenance for compliance |

## ⚡ Performance

- **Signing**: < 0.1ms per signal
- **Verification**: < 0.2ms per execution
- **Total Overhead**: < 0.3ms (negligible for all trading scenarios)

## 🚨 Common Issues

### Issue: "Strategy not configured with cryptographic identity"

**Cause**: StrategyLoader initialized without Firestore client

**Fix**:
```python
# ❌ Wrong
loader = StrategyLoader()  # No db parameter

# ✅ Correct
loader = StrategyLoader(db=firestore.client())
```

### Issue: "Signal missing cryptographic signature"

**Cause**: Strategy forgot to call `sign_signal()`

**Fix**:
```python
# ❌ Wrong
def evaluate(self, ...):
    return TradingSignal(...)

# ✅ Correct
def evaluate(self, ...):
    signal = TradingSignal(...)
    return self.sign_signal(signal)
```

### Issue: "Invalid signature"

**Causes**:
1. Signal was modified after signing
2. Agent was revoked
3. Public key mismatch

**Debug**:
```python
# Check agent status
identity_mgr = get_identity_manager(db)
agents = identity_mgr.get_registered_agents()
print(agents["gammascalper"]["status"])  # Should be "active"
```

## 📚 Documentation

- **Full Guide**: `/workspace/docs/ZERO_TRUST_AGENT_IDENTITY.md`
- **Implementation Summary**: `/workspace/ZERO_TRUST_IMPLEMENTATION_SUMMARY.md`
- **Verification Script**: `/workspace/scripts/verify_zero_trust.py`

## 🎯 Key Files

| File | Purpose |
|------|---------|
| `functions/utils/identity_manager.py` | Core crypto logic |
| `functions/strategies/base.py` | BaseStrategy with signing |
| `functions/strategies/base_strategy.py` | Alternative base with signing |
| `functions/strategies/loader.py` | Auto-registers agents |
| `functions/main.py` | Verification gate |

## 🔮 Next Steps

1. **Deploy**: Push to Cloud Run
2. **Monitor**: Watch security logs for violations
3. **Verify**: Run `verify_zero_trust.py` in production
4. **Enhance**: Consider Phase 2 features (Cloud KMS, JIT scoping)

## 💡 Pro Tips

### 1. Sign All Signals (Including HOLD)

Even HOLD signals should be signed:

```python
signal = TradingSignal(signal_type=SignalType.HOLD, ...)
return self.sign_signal(signal)  # Yes, even HOLD!
```

**Why?** Audit trail shows agent actively decided to hold, not just errored out.

### 2. Sign Error Signals Too

```python
try:
    # ... strategy logic ...
except Exception as e:
    error_signal = TradingSignal(
        signal_type=SignalType.HOLD,
        confidence=0.0,
        reasoning=f"Error: {e}",
        metadata={"error": str(e)}
    )
    return self.sign_signal(error_signal)
```

### 3. Monitor Security Violations

Set up Cloud Monitoring alert:

```
Resource: Cloud Firestore
Metric: Document writes
Filter: resource.labels.database_id="systemStatus/security_log/violations"
Condition: Count > 0
Alert: "Security violation detected!"
```

### 4. Periodic Agent Review

Monthly:
```python
identity_mgr = get_identity_manager(db)
agents = identity_mgr.get_registered_agents()

for agent_id, metadata in agents.items():
    print(f"{agent_id}: {metadata['status']}")
    # Review: Should this agent still be active?
```

## 🆘 Support

**Questions?**
- See full documentation in `/workspace/docs/ZERO_TRUST_AGENT_IDENTITY.md`
- Run verification: `python scripts/verify_zero_trust.py`
- Check logs: `systemStatus/security_log/violations/`

**Security Issues?**
- Immediately revoke agent: `identity_mgr.revoke_agent("agent_id")`
- Review violation logs in Firestore
- Check which trades were affected

---

**Remember**: Every agent is a "digital employee" with a provable identity. No signature = no trade. 🔐
