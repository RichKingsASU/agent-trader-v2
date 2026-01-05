# Maestro Orchestration - Quick Start Guide

## 🎯 What is Maestro?

Maestro is an intelligent orchestration layer that manages your multi-agent trading system by:
- **Dynamically allocating capital** based on Sharpe Ratios
- **Detecting systemic risk** and overriding dangerous signals
- **Tracking every signal** with JIT Identity to prevent double-spend
- **Generating AI summaries** of orchestration decisions

## ⚡ Quick Integration (3 Steps)

### Step 1: Update Your Strategy Loader Initialization

```python
# OLD: Basic StrategyLoader
from functions.strategies.loader import StrategyLoader

loader = StrategyLoader()

# NEW: Maestro-Enabled StrategyLoader
from firebase_admin import firestore
from functions.strategies.loader import StrategyLoader

db = firestore.client()
loader = StrategyLoader(
    db=db,
    tenant_id="my-tenant",  # Your tenant ID
    uid="user123"           # Optional: user ID for user-specific metrics
)
```

### Step 2: Use Maestro-Orchestrated Evaluation

```python
# OLD: Raw strategy evaluation
signals = await loader.evaluate_all_strategies(
    market_data=market_data,
    account_snapshot=account_snapshot
)

# NEW: Maestro-orchestrated evaluation
signals, maestro_decision = await loader.evaluate_all_strategies_with_maestro(
    market_data=market_data,
    account_snapshot=account_snapshot,
    regime=regime_data  # Optional: market regime from GEX
)

# View AI summary
if maestro_decision and maestro_decision.ai_summary:
    print(f"🎭 Maestro: {maestro_decision.ai_summary}")
```

### Step 3: Handle Orchestrated Signals

```python
for strategy_name, signal in signals.items():
    # Check agent mode
    mode = signal.get("mode", "ACTIVE")
    
    if mode == "SHADOW_MODE":
        # Paper trade only - log but don't execute
        log_shadow_pnl(strategy_name, signal)
        continue
    
    # Check for systemic risk overrides
    if "override_reason" in signal:
        logger.warning(f"{strategy_name} overridden: {signal['override_reason']}")
        # Signal action has been changed to HOLD
    
    # Use Maestro-adjusted allocation
    allocation = signal.get("allocation", 0.0)
    original = signal.get("original_allocation", allocation)
    
    if allocation < original:
        logger.info(f"{strategy_name} allocation reduced: {original:.1%} → {allocation:.1%}")
    
    # Execute with JIT Identity tracking
    if signal["action"] == "BUY" and allocation > 0:
        execute_trade(
            strategy=strategy_name,
            signal=signal,
            allocation=allocation,
            agent_id=signal["agent_id"],
            nonce=signal["nonce"]
        )
```

## 🎛️ Configuration

### Adjust Sharpe Thresholds

```python
from functions.strategies.maestro_controller import MaestroController

# Default thresholds
MaestroController.SHARPE_THRESHOLD_REDUCE = 1.0  # Reduce allocation by 50%
MaestroController.SHARPE_THRESHOLD_SHADOW = 0.5  # Move to shadow mode

# More conservative (earlier intervention)
MaestroController.SHARPE_THRESHOLD_REDUCE = 1.5
MaestroController.SHARPE_THRESHOLD_SHADOW = 1.0

# More aggressive (let strategies run longer)
MaestroController.SHARPE_THRESHOLD_REDUCE = 0.5
MaestroController.SHARPE_THRESHOLD_SHADOW = 0.0
```

### Adjust Systemic Risk Threshold

```python
# Default: 3+ SELL signals trigger override
MaestroController.SYSTEMIC_SELL_THRESHOLD = 3

# More sensitive (trigger on 2 SELLs)
MaestroController.SYSTEMIC_SELL_THRESHOLD = 2

# Less sensitive (require 4+ SELLs)
MaestroController.SYSTEMIC_SELL_THRESHOLD = 4
```

### Adjust Performance Lookback

```python
# Default: 30 days of performance data
MaestroController.PERFORMANCE_LOOKBACK_DAYS = 30

# Shorter window (more responsive to recent changes)
MaestroController.PERFORMANCE_LOOKBACK_DAYS = 14

# Longer window (more stable, less reactive)
MaestroController.PERFORMANCE_LOOKBACK_DAYS = 60
```

## 📊 Example Scenarios

### Scenario 1: Healthy Strategy (Sharpe = 1.5)
```python
Input:
  Strategy: "GammaScalper"
  Sharpe Ratio: 1.52
  Original Allocation: 0.5 (50% of buying power)

Maestro Action:
  ✅ Mode: ACTIVE
  ✅ Final Allocation: 0.5 (no change)
  ✅ Reasoning: "Sharpe Ratio 1.52 >= 1.0. Full allocation maintained."
```

### Scenario 2: Declining Strategy (Sharpe = 0.8)
```python
Input:
  Strategy: "MomentumTrader"
  Sharpe Ratio: 0.82
  Original Allocation: 0.3 (30% of buying power)

Maestro Action:
  ⚠️ Mode: REDUCED
  ⚠️ Final Allocation: 0.15 (reduced by 50%)
  ⚠️ Reasoning: "Sharpe Ratio 0.82 < 1.0. Reducing allocation by 50%."
```

### Scenario 3: Failing Strategy (Sharpe = 0.3)
```python
Input:
  Strategy: "OptionsScalper"
  Sharpe Ratio: 0.32
  Original Allocation: 0.4 (40% of buying power)

Maestro Action:
  🚫 Mode: SHADOW_MODE
  🚫 Final Allocation: 0.0 (paper trading only)
  🚫 Reasoning: "Sharpe Ratio 0.32 < 0.5. Moving to SHADOW_MODE for re-training."
```

### Scenario 4: Systemic Risk Override
```python
Input:
  Signals from 5 strategies:
    - Strategy A: SELL
    - Strategy B: SELL
    - Strategy C: SELL
    - Strategy D: BUY
    - Strategy E: BUY

Maestro Action:
  🚨 Systemic Risk Detected: 3 SELL signals
  🚨 Overrides Applied:
    - Strategy D: BUY → HOLD (override: "systemic risk")
    - Strategy E: BUY → HOLD (override: "systemic risk")
  
  AI Summary: "Maestro detected systemic risk with 3 concurrent SELL signals. 
  Overrode 2 BUY orders to HOLD to preserve liquidity during market stress."
```

## 🔍 Monitoring Your Maestro

### View Recent Decisions

```python
from firebase_admin import firestore

db = firestore.client()

# Get last 10 orchestration decisions
logs = db.collection("systemStatus") \
    .document("orchestration_logs") \
    .collection("logs") \
    .order_by("timestamp", direction=firestore.Query.DESCENDING) \
    .limit(10) \
    .stream()

for log in logs:
    data = log.to_dict()
    print(f"\n🎭 Decision: {log.id}")
    print(f"   Time: {data['timestamp']}")
    print(f"   Summary: {data.get('ai_summary', 'N/A')}")
    
    if data.get('systemic_risk_detected'):
        print(f"   ⚠️ RISK: {data['systemic_risk_details']}")
```

### Track Strategy Performance Over Time

```python
# Get allocation history for a specific strategy
strategy_name = "GammaScalper"

logs = db.collection("systemStatus") \
    .document("orchestration_logs") \
    .collection("logs") \
    .order_by("timestamp") \
    .stream()

for log in logs:
    data = log.to_dict()
    for decision in data.get("allocation_decisions", []):
        if decision["strategy_name"] == strategy_name:
            print(f"{data['timestamp']}: "
                  f"Sharpe={decision['sharpe_ratio']:.2f}, "
                  f"Mode={decision['mode']}, "
                  f"Allocation={decision['final_allocation']:.0%}")
```

### Alert on Systemic Risk Events

```python
# Query for recent systemic risk events
risk_events = db.collection("systemStatus") \
    .document("orchestration_logs") \
    .collection("logs") \
    .where("systemic_risk_detected", "==", True) \
    .order_by("timestamp", direction=firestore.Query.DESCENDING) \
    .limit(5) \
    .stream()

for event in risk_events:
    data = event.to_dict()
    print(f"🚨 ALERT: Systemic risk at {data['timestamp']}")
    print(f"   Details: {data['systemic_risk_details']}")
    print(f"   Overrides: {len(data.get('signals_modified', {}))}")
```

## 🧪 Testing Your Integration

### 1. Test Basic Orchestration

```python
import asyncio
from firebase_admin import firestore
from functions.strategies.loader import StrategyLoader

async def test_maestro():
    db = firestore.client()
    loader = StrategyLoader(db=db, tenant_id="test")
    
    # Mock market data
    market_data = {
        "SPY": {"price": 450.00, "volume": 1000000},
    }
    
    account_snapshot = {
        "equity": "100000.00",
        "buying_power": "50000.00",
        "positions": []
    }
    
    # Run orchestration
    signals, decision = await loader.evaluate_all_strategies_with_maestro(
        market_data=market_data,
        account_snapshot=account_snapshot
    )
    
    # Verify
    assert decision is not None, "Maestro decision should not be None"
    assert len(signals) > 0, "Should have signals"
    
    for signal in signals.values():
        if isinstance(signal, dict):
            assert "agent_id" in signal, "Should have agent_id"
            assert "nonce" in signal, "Should have nonce"
            assert "mode" in signal, "Should have mode"
    
    print("✅ Maestro test passed!")
    print(f"🎭 Summary: {decision.ai_summary}")

asyncio.run(test_maestro())
```

### 2. Test Systemic Risk Override

```python
from functions.strategies.maestro_controller import MaestroController

def test_systemic_risk():
    db = firestore.client()
    maestro = MaestroController(db=db)
    
    # Create signals with 3+ SELLs
    signals = {
        "Strategy1": {"action": "SELL", "allocation": 0.3},
        "Strategy2": {"action": "SELL", "allocation": 0.3},
        "Strategy3": {"action": "SELL", "allocation": 0.3},
        "Strategy4": {"action": "BUY", "allocation": 0.2},
        "Strategy5": {"action": "BUY", "allocation": 0.2},
    }
    
    # Apply override
    modified, detected, details = maestro.apply_systemic_risk_override(signals)
    
    # Verify
    assert detected is True, "Should detect systemic risk"
    assert modified["Strategy4"]["action"] == "HOLD", "Should override BUY to HOLD"
    assert modified["Strategy5"]["action"] == "HOLD", "Should override BUY to HOLD"
    assert "override_reason" in modified["Strategy4"], "Should have override reason"
    
    print("✅ Systemic risk test passed!")
    print(f"🚨 Details: {details}")

test_systemic_risk()
```

### 3. Test JIT Identity Uniqueness

```python
def test_jit_identity():
    db = firestore.client()
    maestro = MaestroController(db=db)
    
    # Generate 100 identities
    identities = [
        maestro.generate_agent_identity(f"Strategy{i}")
        for i in range(100)
    ]
    
    # Check uniqueness
    nonces = [id.nonce for id in identities]
    assert len(set(nonces)) == len(nonces), "All nonces should be unique"
    
    agent_ids = [id.agent_id for id in identities]
    print(f"✅ Generated {len(identities)} unique identities")
    print(f"   Unique nonces: {len(set(nonces))}")
    print(f"   Sample nonce: {nonces[0]}")

test_jit_identity()
```

## 🚨 Troubleshooting

### Issue: "Maestro not initialized"
```python
# Solution: Pass Firestore client to StrategyLoader
db = firestore.client()
loader = StrategyLoader(db=db)  # ✅ Correct
# NOT: loader = StrategyLoader()  # ❌ Wrong - Maestro requires db
```

### Issue: "Insufficient data for Sharpe calculation"
```python
# Solution: Ensure you have at least 5 days of performance data
# Check Firestore: tenants/{tenant_id}/strategy_performance/

# You can temporarily disable Maestro for new strategies:
if decision and decision.allocation_decisions:
    for alloc in decision.allocation_decisions:
        if "Insufficient historical data" in alloc.reasoning:
            # New strategy - will use default allocation
            pass
```

### Issue: "AI summary generation failed"
```python
# Solution: Ensure Vertex AI is configured
from backend.common.vertex_ai import init_vertex_ai_or_log

if not init_vertex_ai_or_log():
    # Vertex AI not available - Maestro will use text fallback
    # Check environment variables:
    # - FIREBASE_PROJECT_ID or VERTEX_AI_PROJECT_ID
    # - VERTEX_AI_MODEL_ID (default: gemini-2.0-flash-exp)
    pass
```

### Issue: "Performance data not found"
```python
# Solution: Ensure strategy_performance snapshots are being written
# Check if you're running the monthly performance snapshot script:

# Run manually:
from backend.marketplace.strategy_performance_snapshots import (
    compute_monthly_strategy_performance_from_firestore,
    write_strategy_performance_snapshots
)

snapshots = compute_monthly_strategy_performance_from_firestore(
    db=db,
    tenant_id="my-tenant",
    year=2025,
    month=12
)

write_strategy_performance_snapshots(
    db=db,
    tenant_id="my-tenant",
    snapshots_by_perf_id=snapshots
)
```

## 🎓 Advanced Usage

### Custom Maestro Controller

```python
from functions.strategies.maestro_controller import MaestroController

class CustomMaestro(MaestroController):
    """Custom Maestro with modified thresholds."""
    
    # More aggressive allocation reduction
    SHARPE_THRESHOLD_REDUCE = 1.5
    SHARPE_THRESHOLD_SHADOW = 1.0
    
    # More sensitive systemic risk
    SYSTEMIC_SELL_THRESHOLD = 2
    
    async def custom_risk_check(self, signals):
        """Add custom risk logic."""
        # Example: Check VIX levels
        vix_data = self.db.collection("systemStatus") \
            .document("market_data") \
            .get() \
            .to_dict()
        
        vix = float(vix_data.get("vix", 20))
        
        if vix > 30:  # High volatility
            # Reduce all allocations by 50%
            for signal in signals.values():
                if isinstance(signal, dict):
                    signal["allocation"] *= 0.5
        
        return signals

# Use custom maestro
maestro = CustomMaestro(db=firestore.client())
signals, decision = await maestro.orchestrate(raw_signals, strategies)
```

### Integration with Cloud Functions

```python
from firebase_functions import scheduler_fn
from firebase_admin import firestore
from functions.strategies.loader import StrategyLoader

@scheduler_fn.on_schedule(schedule="*/5 * * * *")  # Every 5 minutes
async def orchestrated_trading(event: scheduler_fn.ScheduledEvent):
    """Cloud Function with Maestro orchestration."""
    
    db = firestore.client()
    loader = StrategyLoader(db=db, tenant_id="prod")
    
    # Fetch market data
    market_data = fetch_market_data()
    account_snapshot = fetch_account_snapshot()
    
    # Run Maestro orchestration
    signals, decision = await loader.evaluate_all_strategies_with_maestro(
        market_data=market_data,
        account_snapshot=account_snapshot
    )
    
    # Log summary
    if decision and decision.ai_summary:
        logger.info(f"🎭 {decision.ai_summary}")
    
    # Execute trades
    for strategy_name, signal in signals.items():
        if signal.get("mode") == "SHADOW_MODE":
            continue
        
        if signal["action"] in ["BUY", "SELL"]:
            execute_trade_with_identity(
                signal=signal,
                agent_id=signal["agent_id"],
                nonce=signal["nonce"]
            )
    
    return {"status": "success", "session_id": decision.session_id}
```

## 📚 Next Steps

1. **Read Full Documentation**: See [MAESTRO_ORCHESTRATION_IMPLEMENTATION.md](../MAESTRO_ORCHESTRATION_IMPLEMENTATION.md)
2. **Add Strategies**: Drop new `.py` files in `functions/strategies/`
3. **Monitor Performance**: Set up dashboard on Firestore data
4. **Tune Thresholds**: Adjust based on your risk tolerance
5. **Integrate Execution**: Update trade executor to respect Maestro decisions

---

**Questions?** Check the [full implementation guide](../MAESTRO_ORCHESTRATION_IMPLEMENTATION.md) or review the [architecture docs](../ARCHITECTURE_VERIFICATION_CHECKLIST.md).
