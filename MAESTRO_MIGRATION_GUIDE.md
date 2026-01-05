# Maestro Migration Guide

This guide helps you migrate your existing trading system to use the Maestro orchestration layer.

## Overview

Maestro enhances your existing system without requiring strategy rewrites. The migration can be done incrementally, allowing you to test each step before proceeding.

## Migration Phases

### Phase 1: Basic Integration (10 minutes)
Enable Maestro with minimal changes to existing code.

### Phase 2: Signal Handling (20 minutes)
Update execution logic to respect Maestro decisions.

### Phase 3: Monitoring Setup (15 minutes)
Add dashboards and alerts for orchestration insights.

### Phase 4: Production Optimization (30 minutes)
Tune thresholds and configure advanced features.

---

## Phase 1: Basic Integration

### Step 1.1: Update StrategyLoader Initialization

**Before:**
```python
from functions.strategies.loader import StrategyLoader

loader = StrategyLoader()
```

**After:**
```python
from firebase_admin import firestore
from functions.strategies.loader import StrategyLoader

db = firestore.client()
loader = StrategyLoader(
    db=db,
    tenant_id=tenant_id,  # Use your tenant ID
    uid=user_id           # Optional: for user-specific metrics
)
```

### Step 1.2: Update Strategy Evaluation Call

**Before:**
```python
signals = await loader.evaluate_all_strategies(
    market_data=market_data,
    account_snapshot=account_snapshot
)

# Process signals...
for strategy_name, signal in signals.items():
    execute_trade(signal)
```

**After:**
```python
# Get orchestrated signals
signals, maestro_decision = await loader.evaluate_all_strategies_with_maestro(
    market_data=market_data,
    account_snapshot=account_snapshot,
    regime=regime_data  # Optional
)

# Log Maestro summary
if maestro_decision and maestro_decision.ai_summary:
    logger.info(f"🎭 Maestro: {maestro_decision.ai_summary}")

# Process signals (next phase will update this)
for strategy_name, signal in signals.items():
    execute_trade(signal)
```

### Step 1.3: Verify Basic Integration

Run your system and check logs for:
```
INFO: MaestroController initialized: tenant=..., uid=...
INFO: 🎭 Maestro orchestration starting...
INFO: Strategy XYZ: Sharpe=1.23, Weight=1.00, Mode=ACTIVE
INFO: 🎭 Maestro orchestration complete
```

**✅ Phase 1 Complete**: Maestro is running and logging decisions.

---

## Phase 2: Signal Handling

### Step 2.1: Handle Shadow Mode

Update your execution logic to skip shadow mode strategies:

**Before:**
```python
for strategy_name, signal in signals.items():
    if signal["action"] == "BUY":
        execute_trade(signal)
```

**After:**
```python
for strategy_name, signal in signals.items():
    # Check mode before execution
    mode = signal.get("mode", "ACTIVE")
    
    if mode == "SHADOW_MODE":
        # Log to shadow P&L, don't execute
        logger.info(f"📝 {strategy_name}: SHADOW MODE - Paper trading only")
        log_shadow_trade(strategy_name, signal)
        continue
    
    if mode == "DISABLED":
        logger.info(f"🚫 {strategy_name}: DISABLED - Skipping")
        continue
    
    # Execute trade
    if signal["action"] == "BUY":
        execute_trade(signal)
```

### Step 2.2: Respect Maestro-Adjusted Allocations

**Before:**
```python
# Use original allocation from strategy
allocation = signal.get("allocation", 0.5)
trade_amount = buying_power * allocation
```

**After:**
```python
# Use Maestro-adjusted allocation
allocation = signal.get("allocation", 0.0)
original = signal.get("original_allocation", allocation)

if allocation < original:
    logger.info(
        f"⚠️ {strategy_name} allocation reduced by Maestro: "
        f"{original:.1%} → {allocation:.1%}"
    )

trade_amount = buying_power * allocation
```

### Step 2.3: Handle Systemic Risk Overrides

**Before:**
```python
for strategy_name, signal in signals.items():
    if signal["action"] == "BUY":
        execute_buy(signal)
```

**After:**
```python
for strategy_name, signal in signals.items():
    # Check for Maestro overrides
    if "override_reason" in signal:
        logger.warning(
            f"🚨 {strategy_name} overridden by Maestro: "
            f"{signal.get('original_action', '?')} → {signal['action']}"
        )
        logger.warning(f"   Reason: {signal['override_reason']}")
    
    # Execute with potentially modified action
    if signal["action"] == "BUY" and allocation > 0:
        execute_buy(signal)
```

### Step 2.4: Track JIT Identity

**Before:**
```python
def execute_trade(signal):
    order = alpaca_api.submit_order(
        symbol=signal["ticker"],
        side=signal["action"],
        qty=calculate_qty(signal["allocation"])
    )
```

**After:**
```python
def execute_trade(signal):
    # Extract JIT Identity
    agent_id = signal.get("agent_id")
    nonce = signal.get("nonce")
    session_id = signal.get("session_id")
    
    # Log with identity
    logger.info(
        f"Executing trade with identity: "
        f"agent={agent_id}, nonce={nonce[:8]}..."
    )
    
    # Submit order
    order = alpaca_api.submit_order(
        symbol=signal["ticker"],
        side=signal["action"],
        qty=calculate_qty(signal["allocation"])
    )
    
    # Log trade with identity for audit trail
    log_trade_execution(
        order_id=order.id,
        agent_id=agent_id,
        nonce=nonce,
        session_id=session_id,
        signal=signal
    )
```

### Step 2.5: Implement Shadow Trade Logging

Add a function to log shadow mode trades:

```python
async def log_shadow_trade(strategy_name: str, signal: Dict[str, Any]) -> None:
    """Log shadow mode trade for paper trading tracking."""
    try:
        shadow_log = {
            "timestamp": firestore.SERVER_TIMESTAMP,
            "strategy_name": strategy_name,
            "action": signal["action"],
            "ticker": signal.get("ticker", "UNKNOWN"),
            "mode": "SHADOW_MODE",
            "reasoning": signal.get("reasoning", ""),
            
            # JIT Identity
            "agent_id": signal.get("agent_id"),
            "nonce": signal.get("nonce"),
            "session_id": signal.get("session_id"),
            
            # Metadata
            "sharpe_ratio": signal.get("sharpe_ratio", 0.0),
            "confidence": signal.get("confidence", 0.0)
        }
        
        db.collection("tenants") \
            .document(tenant_id) \
            .collection("shadow_pnl") \
            .add(shadow_log)
            
    except Exception as e:
        logger.error(f"Failed to log shadow trade: {e}")
```

**✅ Phase 2 Complete**: Your system now respects all Maestro decisions.

---

## Phase 3: Monitoring Setup

### Step 3.1: Create Orchestration Dashboard

```python
async def get_orchestration_summary(hours: int = 24) -> Dict[str, Any]:
    """Get summary of Maestro decisions over last N hours."""
    from datetime import datetime, timedelta, timezone
    
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    
    logs = db.collection("systemStatus") \
        .document("orchestration_logs") \
        .collection("logs") \
        .where("timestamp", ">=", cutoff) \
        .stream()
    
    summary = {
        "total_decisions": 0,
        "systemic_risk_events": 0,
        "strategies_reduced": set(),
        "strategies_shadowed": set(),
        "mode_distribution": {"ACTIVE": 0, "REDUCED": 0, "SHADOW_MODE": 0}
    }
    
    for log in logs:
        data = log.to_dict()
        summary["total_decisions"] += 1
        
        if data.get("systemic_risk_detected"):
            summary["systemic_risk_events"] += 1
        
        for decision in data.get("allocation_decisions", []):
            mode = decision["mode"]
            summary["mode_distribution"][mode] += 1
            
            if mode == "REDUCED":
                summary["strategies_reduced"].add(decision["strategy_name"])
            elif mode == "SHADOW_MODE":
                summary["strategies_shadowed"].add(decision["strategy_name"])
    
    # Convert sets to lists
    summary["strategies_reduced"] = list(summary["strategies_reduced"])
    summary["strategies_shadowed"] = list(summary["strategies_shadowed"])
    
    return summary
```

### Step 3.2: Add Alerts for Critical Events

```python
async def check_maestro_alerts() -> List[str]:
    """Check for critical Maestro events requiring attention."""
    alerts = []
    
    # Check for recent systemic risk events
    recent = datetime.now(timezone.utc) - timedelta(hours=1)
    risk_events = db.collection("systemStatus") \
        .document("orchestration_logs") \
        .collection("logs") \
        .where("timestamp", ">=", recent) \
        .where("systemic_risk_detected", "==", True) \
        .limit(1) \
        .stream()
    
    for event in risk_events:
        data = event.to_dict()
        alerts.append(
            f"🚨 SYSTEMIC RISK: {data['systemic_risk_details']}"
        )
    
    # Check for strategies moved to shadow mode
    recent_decisions = db.collection("systemStatus") \
        .document("orchestration_logs") \
        .collection("logs") \
        .where("timestamp", ">=", recent) \
        .order_by("timestamp", direction=firestore.Query.DESCENDING) \
        .limit(1) \
        .stream()
    
    for log in recent_decisions:
        data = log.to_dict()
        for decision in data.get("allocation_decisions", []):
            if decision["mode"] == "SHADOW_MODE":
                alerts.append(
                    f"⚠️ {decision['strategy_name']} moved to SHADOW_MODE "
                    f"(Sharpe: {decision['sharpe_ratio']:.2f})"
                )
    
    return alerts
```

### Step 3.3: Daily Summary Report

```python
async def generate_daily_maestro_report() -> str:
    """Generate daily summary of Maestro activity."""
    summary = await get_orchestration_summary(hours=24)
    
    report = [
        "=" * 80,
        "🎭 MAESTRO DAILY SUMMARY",
        "=" * 80,
        "",
        f"Total Orchestration Decisions: {summary['total_decisions']}",
        f"Systemic Risk Events: {summary['systemic_risk_events']}",
        "",
        "Strategy Mode Distribution:",
        f"  • ACTIVE: {summary['mode_distribution']['ACTIVE']}",
        f"  • REDUCED: {summary['mode_distribution']['REDUCED']}",
        f"  • SHADOW_MODE: {summary['mode_distribution']['SHADOW_MODE']}",
        "",
    ]
    
    if summary["strategies_reduced"]:
        report.append("Strategies with Reduced Allocation:")
        for name in summary["strategies_reduced"]:
            report.append(f"  • {name}")
        report.append("")
    
    if summary["strategies_shadowed"]:
        report.append("Strategies in Shadow Mode:")
        for name in summary["strategies_shadowed"]:
            report.append(f"  • {name}")
        report.append("")
    
    # Get recent AI summaries
    recent_logs = db.collection("systemStatus") \
        .document("orchestration_logs") \
        .collection("logs") \
        .order_by("timestamp", direction=firestore.Query.DESCENDING) \
        .limit(3) \
        .stream()
    
    report.append("Recent Maestro Decisions:")
    for log in recent_logs:
        data = log.to_dict()
        if data.get("ai_summary"):
            report.append(f"  • {data['ai_summary']}")
    
    report.append("=" * 80)
    
    return "\n".join(report)
```

**✅ Phase 3 Complete**: You have monitoring and alerting in place.

---

## Phase 4: Production Optimization

### Step 4.1: Tune Sharpe Thresholds

Based on your backtesting and risk tolerance:

```python
from functions.strategies.maestro_controller import MaestroController

# Conservative (earlier intervention)
MaestroController.SHARPE_THRESHOLD_REDUCE = 1.5
MaestroController.SHARPE_THRESHOLD_SHADOW = 1.0

# Moderate (default)
MaestroController.SHARPE_THRESHOLD_REDUCE = 1.0
MaestroController.SHARPE_THRESHOLD_SHADOW = 0.5

# Aggressive (longer runway)
MaestroController.SHARPE_THRESHOLD_REDUCE = 0.5
MaestroController.SHARPE_THRESHOLD_SHADOW = 0.0
```

### Step 4.2: Adjust Risk Sensitivity

```python
# High sensitivity (trigger on 2 SELLs)
MaestroController.SYSTEMIC_SELL_THRESHOLD = 2

# Default (trigger on 3 SELLs)
MaestroController.SYSTEMIC_SELL_THRESHOLD = 3

# Low sensitivity (trigger on 4+ SELLs)
MaestroController.SYSTEMIC_SELL_THRESHOLD = 4
```

### Step 4.3: Configure Performance Lookback

```python
# Short window (more responsive)
MaestroController.PERFORMANCE_LOOKBACK_DAYS = 14

# Default (balanced)
MaestroController.PERFORMANCE_LOOKBACK_DAYS = 30

# Long window (more stable)
MaestroController.PERFORMANCE_LOOKBACK_DAYS = 60
```

### Step 4.4: Enable Performance Tracking

Ensure strategy_performance snapshots are being written:

```python
from firebase_functions import scheduler_fn

@scheduler_fn.on_schedule(schedule="0 0 1 * *")  # Monthly
async def monthly_performance_snapshot(event):
    """Calculate monthly strategy performance."""
    from backend.marketplace.strategy_performance_snapshots import (
        compute_monthly_strategy_performance_from_firestore,
        write_strategy_performance_snapshots
    )
    
    db = firestore.client()
    year = datetime.now().year
    month = datetime.now().month - 1  # Previous month
    
    snapshots = compute_monthly_strategy_performance_from_firestore(
        db=db,
        tenant_id=tenant_id,
        year=year,
        month=month
    )
    
    write_strategy_performance_snapshots(
        db=db,
        tenant_id=tenant_id,
        snapshots_by_perf_id=snapshots
    )
    
    logger.info(f"Wrote {len(snapshots)} performance snapshots")
```

**✅ Phase 4 Complete**: Your system is production-ready with Maestro!

---

## Rollback Plan

If you need to temporarily disable Maestro:

### Option 1: Use Traditional Evaluation

```python
# Maestro-enabled (default)
signals, decision = await loader.evaluate_all_strategies_with_maestro(
    market_data, account_snapshot
)

# Disable Maestro (fallback)
signals = await loader.evaluate_all_strategies(
    market_data, account_snapshot
)
```

### Option 2: Initialize Without DB

```python
# Without Maestro
loader = StrategyLoader()  # No db parameter

# With Maestro
loader = StrategyLoader(db=firestore.client())
```

---

## Testing Checklist

- [ ] Maestro initializes without errors
- [ ] All strategies are discovered and loaded
- [ ] Orchestration decisions are logged to Firestore
- [ ] Shadow mode strategies don't execute trades
- [ ] Reduced allocations are applied correctly
- [ ] Systemic risk override works with 3+ SELLs
- [ ] JIT Identity is unique per signal
- [ ] AI summaries are generated (if Vertex AI configured)
- [ ] Dashboard shows accurate orchestration data
- [ ] Alerts fire for critical events

---

## Common Issues

### Issue: "Maestro not initialized"
**Solution**: Pass `db` parameter to StrategyLoader:
```python
loader = StrategyLoader(db=firestore.client())
```

### Issue: "Insufficient data for Sharpe calculation"
**Solution**: 
1. Check that strategy_performance snapshots exist in Firestore
2. Wait for at least 5 days of data
3. Maestro will use default allocation until data is available

### Issue: "AI summary generation failed"
**Solution**: 
1. Check Vertex AI configuration
2. Ensure `FIREBASE_PROJECT_ID` is set
3. Maestro will use text fallback summaries

### Issue: Shadow mode trades still executing
**Solution**: Add mode check before execution:
```python
if signal.get("mode") == "SHADOW_MODE":
    continue
```

---

## Next Steps

1. ✅ Complete all 4 migration phases
2. 📊 Review first week of orchestration data
3. 🎛️ Tune thresholds based on results
4. 📈 Set up dashboards and alerts
5. 🚀 Enjoy intelligent multi-agent orchestration!

---

**Questions?** See:
- [Quick Start Guide](functions/strategies/MAESTRO_QUICKSTART.md)
- [Full Documentation](MAESTRO_ORCHESTRATION_IMPLEMENTATION.md)
- [Visual Architecture](MAESTRO_VISUAL_ARCHITECTURE.md)
