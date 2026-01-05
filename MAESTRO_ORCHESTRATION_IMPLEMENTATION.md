# Maestro Orchestration Layer - Implementation Summary

## 🎭 Overview

The **Maestro Orchestration Layer** is a sophisticated multi-agent coordination system that sits above the StrategyLoader to manage agent sprawl, dynamic capital allocation, and systemic risk detection. This implementation brings 2026 institutional standards to your agentic AI trading fund.

## ✨ Key Features

### 1. **Sharpe-Based Dynamic Allocation**
- Automatically calculates Annualized Sharpe Ratios from the last 30 days of performance
- Formula: `S = sqrt(252) × (mean(daily_returns) / std(daily_returns))`
- Dynamic allocation rules:
  - **Sharpe < 0.5**: Move to `SHADOW_MODE` (paper trading only)
  - **Sharpe < 1.0**: Reduce allocation by 50%
  - **Sharpe ≥ 1.0**: Full allocation maintained

### 2. **Systemic Risk Detection**
- Monitors all agent signals in real-time
- **Override Rule**: If 3+ agents signal SELL simultaneously, all BUY signals are overridden to HOLD
- Preserves liquidity during market stress
- Prevents cascading losses from coordinated negative signals

### 3. **Just-In-Time (JIT) Identity**
- Every execution signal includes:
  - `agent_id`: Unique identifier for the agent/strategy
  - `nonce`: 32-character hex nonce for uniqueness
  - `session_id`: Per-invocation session tracking
  - `timestamp`: ISO-8601 timestamp
- Prevents "Double Spend" where two bots try to use the same buying power
- Prevents "Agent Sprawl" with complete signal traceability

### 4. **Complete Auditability**
- All Maestro decisions logged to `systemStatus/orchestration_logs/{timestamp}_{session_id}`
- Includes:
  - Allocation decisions with reasoning
  - Sharpe Ratios and performance metrics
  - Systemic risk overrides
  - Signal modifications
  - AI-generated summaries

### 5. **AI-Powered Summaries**
- Uses Gemini 2.0 Flash to generate executive summaries
- Example: *"Maestro reduced Gamma Scalper allocation by 20% due to rising volatility and a 0.8 Sharpe decay."*
- Provides human-readable insights into complex orchestration decisions

## 📊 Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Maestro Controller                        │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  1. Sharpe-Based Weight Calculation                  │   │
│  │     - Fetch 30 days of performance                   │   │
│  │     - Calculate Annualized Sharpe Ratios             │   │
│  │     - Apply allocation rules                         │   │
│  └─────────────────────────────────────────────────────┘   │
│                          ↓                                   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  2. Systemic Risk Override                           │   │
│  │     - Count SELL signals                             │   │
│  │     - Override BUYs if threshold breached            │   │
│  └─────────────────────────────────────────────────────┘   │
│                          ↓                                   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  3. JIT Identity Enrichment                          │   │
│  │     - Generate unique agent_id + nonce               │   │
│  │     - Add session tracking                           │   │
│  └─────────────────────────────────────────────────────┘   │
│                          ↓                                   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  4. AI Summary Generation                            │   │
│  │     - Build decision summary                         │   │
│  │     - Generate Gemini insights                       │   │
│  └─────────────────────────────────────────────────────┘   │
│                          ↓                                   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  5. Auditability Logging                             │   │
│  │     - Log to Firestore                               │   │
│  │     - Complete decision trail                        │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                          ↓
        ┌─────────────────────────────────────┐
        │    Orchestrated Signals Output       │
        │  - Weighted allocations              │
        │  - Risk overrides applied            │
        │  - JIT Identity attached             │
        │  - Ready for execution               │
        └─────────────────────────────────────┘
```

## 🚀 Quick Start

### Basic Usage

```python
from firebase_admin import firestore
from functions.strategies.loader import StrategyLoader

# Initialize with Firestore client for Maestro orchestration
db = firestore.client()
loader = StrategyLoader(db=db, tenant_id="my-tenant", uid="user123")

# Evaluate strategies with Maestro orchestration
market_data = {
    "SPY": {"price": 450.00, "volume": 1000000},
    "QQQ": {"price": 380.00, "volume": 800000}
}

account_snapshot = {
    "equity": "100000.00",
    "buying_power": "50000.00",
    "positions": []
}

# Get orchestrated signals
signals, maestro_decision = await loader.evaluate_all_strategies_with_maestro(
    market_data=market_data,
    account_snapshot=account_snapshot
)

# Signals now include:
# - Sharpe-based allocation adjustments
# - Systemic risk overrides
# - JIT Identity (agent_id, nonce, session_id)
# - Mode indicators (ACTIVE, REDUCED, SHADOW_MODE)

for strategy_name, signal in signals.items():
    print(f"{strategy_name}: {signal['action']} @ {signal['allocation']:.2%} allocation")
    print(f"  Agent ID: {signal['agent_id']}")
    print(f"  Nonce: {signal['nonce']}")
    print(f"  Mode: {signal['mode']}")
    
    if "override_reason" in signal:
        print(f"  ⚠️ Override: {signal['override_reason']}")

# View Maestro's AI summary
print(f"\n🎭 Maestro Summary:\n{maestro_decision.ai_summary}")
```

### Standalone Maestro Usage

```python
from functions.strategies.maestro_controller import MaestroController

# Initialize Maestro
maestro = MaestroController(
    db=firestore.client(),
    tenant_id="my-tenant",
    uid="user123"
)

# Calculate strategy weights
weights = await maestro.calculate_strategy_weights(strategies)

# Apply systemic risk override
signals, risk_detected, details = maestro.apply_systemic_risk_override(raw_signals)

# Generate JIT Identity
identity = maestro.generate_agent_identity("GammaScalper")
print(f"Agent ID: {identity.agent_id}")
print(f"Nonce: {identity.nonce}")

# Full orchestration
final_signals, decision = await maestro.orchestrate(
    signals=raw_signals,
    strategies=strategies
)
```

### Calculate Weights Only

```python
# Just get Sharpe-based weights without full orchestration
loader = StrategyLoader(db=firestore.client())

weights = await loader.calculate_strategy_weights()

for strategy_name, (weight, mode) in weights.items():
    print(f"{strategy_name}: {weight:.2%} allocation, Mode: {mode}")
```

## 📁 File Structure

```
functions/strategies/
├── maestro_controller.py       # Main Maestro implementation
├── loader.py                   # Enhanced StrategyLoader with Maestro
├── base.py                     # Base strategy interface
├── base_strategy.py            # Alternative base strategy
└── [strategy implementations]

systemStatus/
└── orchestration_logs/
    └── logs/
        └── {timestamp}_{session_id}   # Maestro decision logs
```

## 🔍 Firestore Data Structures

### Performance Data (Input)
```
tenants/{tenant_id}/strategy_performance/{perf_id}
{
  "tenant_id": "default",
  "uid": "user123",
  "strategy_id": "GammaScalper",
  "period_start": "2025-12-01T00:00:00Z",
  "period_end": "2025-12-02T00:00:00Z",
  "realized_pnl": 150.50,
  "unrealized_pnl": 25.00,
  "computed_at": "2025-12-02T01:00:00Z",
  "source": "ledger_trades_fifo"
}
```

### Orchestration Logs (Output)
```
systemStatus/orchestration_logs/logs/{timestamp}_{session_id}
{
  "timestamp": "2025-12-30T12:00:00Z",
  "session_id": "maestro_1735560000000_a1b2c3d4",
  "allocation_decisions": [
    {
      "strategy_name": "GammaScalper",
      "original_allocation": 1.0,
      "final_allocation": 0.5,
      "mode": "REDUCED",
      "reasoning": "Sharpe Ratio 0.85 < 1.0. Reducing allocation by 50%.",
      "sharpe_ratio": 0.85,
      "timestamp": "2025-12-30T12:00:00Z"
    }
  ],
  "systemic_risk_detected": true,
  "systemic_risk_details": "Systemic risk threshold breached: 4 SELL signals. Overrode 2 BUY signals to HOLD.",
  "signals_modified": {
    "MomentumStrategy": "BUY->HOLD (systemic risk)"
  },
  "ai_summary": "Maestro reduced Gamma Scalper allocation by 50% due to 0.85 Sharpe ratio decay. Systemic risk override engaged as 4 strategies signaled SELL, protecting capital by converting 2 BUY signals to HOLD."
}
```

### Enriched Signal Format
```python
{
  "action": "BUY",
  "allocation": 0.25,           # 50% of original 0.5 allocation
  "original_allocation": 0.5,   # Original allocation before Maestro
  "weight_multiplier": 0.5,     # Applied weight (50% reduction)
  "mode": "REDUCED",            # ACTIVE, REDUCED, SHADOW_MODE, or DISABLED
  "ticker": "SPY",
  "reasoning": "Strong momentum detected",
  
  # JIT Identity
  "agent_id": "default_GammaScalper",
  "nonce": "a1b2c3d4e5f6789012345678901234567890abcdef01",
  "session_id": "maestro_1735560000000_a1b2c3d4",
  "identity_timestamp": "2025-12-30T12:00:00Z",
  
  # Risk Override (if applicable)
  "override_reason": "Maestro systemic risk override: 4 strategies signaling SELL",
  "original_action": "BUY"  # Only present if overridden
}
```

## 🎯 Agent Modes

| Mode | Description | Allocation | Use Case |
|------|-------------|------------|----------|
| **ACTIVE** | Full trading with complete allocation | 100% | Sharpe ≥ 1.0, healthy performance |
| **REDUCED** | Trading with reduced capital | 50% | 0.5 ≤ Sharpe < 1.0, marginal performance |
| **SHADOW_MODE** | Paper trading only, no execution | 0% | Sharpe < 0.5, retraining needed |
| **DISABLED** | Completely disabled | 0% | Manual override or critical issues |

## 🛡️ Systemic Risk Detection

### How It Works
1. Maestro counts SELL signals from all active strategies
2. If `sell_count >= 3`, systemic risk is detected
3. All BUY signals are immediately overridden to HOLD
4. Override reasoning is attached to each modified signal
5. Decision is logged with full details

### Example Scenario
```
Initial Signals:
  Strategy A: SELL
  Strategy B: SELL  
  Strategy C: SELL
  Strategy D: BUY   ← Will be overridden
  Strategy E: BUY   ← Will be overridden

After Maestro Override:
  Strategy A: SELL
  Strategy B: SELL
  Strategy C: SELL
  Strategy D: HOLD (overridden, reason: "systemic risk")
  Strategy E: HOLD (overridden, reason: "systemic risk")
```

## 🔐 JIT Identity System

### Purpose
Prevents:
- **Double Spend**: Two strategies trying to use the same buying power
- **Agent Sprawl**: Untracked or duplicate agent execution
- **Audit Gaps**: Missing signal attribution

### Components
```python
AgentIdentity(
    agent_id="default_GammaScalper",              # Unique per strategy
    strategy_name="GammaScalper",                  # Human-readable name
    nonce="a1b2c3...890abcdef",                   # 32-char hex (cryptographically random)
    timestamp="2025-12-30T12:00:00Z",             # ISO-8601 timestamp
    session_id="maestro_1735560000000_a1b2c3d4"  # Per-invocation session
)
```

### Verification
```python
# Check for duplicate nonces (should never happen)
seen_nonces = set()
for signal in signals.values():
    nonce = signal.get("nonce")
    assert nonce not in seen_nonces, "Duplicate nonce detected!"
    seen_nonces.add(nonce)
```

## 📈 Performance Metrics

### Sharpe Ratio Calculation
```python
# 1. Fetch daily P&L for last 30 days
# 2. Convert to percentage returns
daily_returns = [pnl / BASE_CAPITAL for pnl in daily_pnls]

# 3. Calculate statistics
mean_return = sum(daily_returns) / len(daily_returns)
std_dev = sqrt(sum((r - mean_return)^2 for r in daily_returns) / len(daily_returns))

# 4. Calculate Sharpe Ratio
RISK_FREE_RATE = 0.04  # 4% annual
daily_rf_rate = RISK_FREE_RATE / 252
sharpe = ((mean_return - daily_rf_rate) / std_dev) * sqrt(252)
```

### Other Metrics Tracked
- **Annualized Return**: Compound annual growth rate
- **Total Return**: Cumulative return over period
- **Maximum Drawdown**: Peak-to-trough loss percentage
- **Volatility**: Annualized standard deviation of returns
- **Win Rate**: Percentage of profitable days

## 🤖 AI Summary Generation

### Prompt Structure
```python
prompt = f"""
You are the Maestro, an AI orchestrator for a multi-agent trading system.
Generate a concise, professional summary of this orchestration decision:

Session: {session_id}
Timestamp: {timestamp}

Allocation Decisions:
  - Strategy A: REDUCED (Sharpe: 0.85, Allocation: 100% → 50%)
    Reasoning: Sharpe Ratio 0.85 < 1.0. Reducing allocation by 50%.
  - Strategy B: SHADOW_MODE (Sharpe: 0.42, Allocation: 100% → 0%)
    Reasoning: Sharpe Ratio 0.42 < 0.5. Moving to SHADOW_MODE for re-training.

⚠️ SYSTEMIC RISK OVERRIDE:
  Systemic risk threshold breached: 4 SELL signals. Overrode 2 BUY signals to HOLD.

Provide a 2-3 sentence executive summary highlighting key actions 
and any risk management interventions.
"""
```

### Example Output
> *"Maestro reduced Gamma Scalper allocation by 50% due to 0.85 Sharpe ratio decay and moved Congressional Alpha to shadow mode for retraining (Sharpe: 0.42). Systemic risk override engaged as 4 strategies signaled SELL, protecting capital by converting 2 BUY signals to HOLD, preserving liquidity during market stress."*

## 🔄 Integration with Existing Systems

### With Strategy Loader
```python
# Old way (no Maestro)
loader = StrategyLoader()
signals = await loader.evaluate_all_strategies(market_data, account_snapshot)

# New way (with Maestro)
loader = StrategyLoader(db=firestore.client())
signals, decision = await loader.evaluate_all_strategies_with_maestro(
    market_data, account_snapshot
)
```

### With Execution Engine
```python
# After getting orchestrated signals
for strategy_name, signal in signals.items():
    # Check mode before execution
    if signal.get("mode") == "SHADOW_MODE":
        # Log to shadow P&L, don't execute
        log_shadow_trade(signal)
        continue
    
    # Check for overrides
    if "override_reason" in signal:
        logger.warning(f"Signal overridden: {signal['override_reason']}")
    
    # Execute with adjusted allocation
    allocation = signal.get("allocation", 0.0)
    if allocation > 0 and signal["action"] == "BUY":
        execute_trade(signal, allocation)
```

### With GEX Engine
```python
# Maestro integrates with existing regime data
regime_data = get_gex_regime()  # From systemStatus/market_regime

signals, decision = await loader.evaluate_all_strategies_with_maestro(
    market_data=market_data,
    account_snapshot=account_snapshot,
    regime=regime_data  # Passed to strategies, not Maestro directly
)
```

## 🧪 Testing

### Unit Tests
```python
import pytest
from functions.strategies.maestro_controller import MaestroController

@pytest.mark.asyncio
async def test_sharpe_based_allocation():
    maestro = MaestroController(db=mock_db)
    
    # Mock performance data
    mock_performance_with_low_sharpe()
    
    weights = await maestro.calculate_strategy_weights(strategies)
    
    # Strategy with Sharpe < 0.5 should be in shadow mode
    assert weights["BadStrategy"][0] == 0.0
    assert weights["BadStrategy"][1].value == "SHADOW_MODE"

def test_systemic_risk_override():
    maestro = MaestroController(db=mock_db)
    
    signals = {
        "A": {"action": "SELL"},
        "B": {"action": "SELL"},
        "C": {"action": "SELL"},
        "D": {"action": "BUY"},
    }
    
    modified, detected, _ = maestro.apply_systemic_risk_override(signals)
    
    assert detected is True
    assert modified["D"]["action"] == "HOLD"
    assert "override_reason" in modified["D"]

def test_jit_identity_uniqueness():
    maestro = MaestroController(db=mock_db)
    
    # Generate multiple identities
    identities = [
        maestro.generate_agent_identity("Strategy1")
        for _ in range(100)
    ]
    
    # All nonces should be unique
    nonces = [i.nonce for i in identities]
    assert len(set(nonces)) == len(nonces)
```

## 📊 Monitoring & Observability

### Key Metrics to Monitor
1. **Orchestration Latency**: Time taken for Maestro to process signals
2. **Override Frequency**: How often systemic risk overrides occur
3. **Mode Distribution**: Count of strategies in each mode (ACTIVE/REDUCED/SHADOW)
4. **Sharpe Decay Events**: Strategies moving from ACTIVE to REDUCED/SHADOW
5. **Nonce Collisions**: Should be zero, log alerts if any

### Logging
```python
# Maestro logs at INFO level for normal operations
logger.info("🎭 Maestro orchestration starting...")
logger.info("Strategy XYZ: Sharpe=0.85, Weight=0.50, Mode=REDUCED")

# WARNING level for risk events
logger.warning("🚨 SYSTEMIC RISK DETECTED: 4 agents signaling SELL")

# ERROR level for failures
logger.error("Maestro orchestration failed: {error}")
```

### Firestore Queries
```python
# Get recent orchestration decisions
logs = db.collection("systemStatus") \
    .document("orchestration_logs") \
    .collection("logs") \
    .order_by("timestamp", direction=firestore.Query.DESCENDING) \
    .limit(10) \
    .stream()

# Find systemic risk events
risk_events = db.collection("systemStatus") \
    .document("orchestration_logs") \
    .collection("logs") \
    .where("systemic_risk_detected", "==", True) \
    .stream()
```

## 🏛️ The MAESTRO Infrastructure Layer

| Pillar | 2026 Institutional Standard | Implementation |
|--------|----------------------------|----------------|
| **Multi-Agent** | Coordinated ecosystems, not lone bots | StrategyLoader with weighted signals |
| **Environment** | Awareness of news, VIX, and GEX | Macro-Event Scraper integration |
| **Security** | Identity-based agent tracking | JIT Identity and nonces for every signal |
| **Risk** | Real-time Sharpe-based throttling | MaestroController capital allocation |
| **Outcome** | Automated journaling and grading | AI Post-Game analysis module |

## 🚀 Next Steps

1. **Deploy to Cloud Functions**: Update your Cloud Function to use `evaluate_all_strategies_with_maestro()`
2. **Monitor Performance**: Set up alerts on Firestore orchestration logs
3. **Tune Thresholds**: Adjust `SHARPE_THRESHOLD_REDUCE` and `SHARPE_THRESHOLD_SHADOW` based on your risk tolerance
4. **Add Strategies**: Drop new strategy files in `functions/strategies/` - Maestro will orchestrate them automatically
5. **Integrate with Execution**: Update your trade executor to respect Maestro's allocations and overrides

## 📚 Additional Resources

- [Strategy Development Guide](functions/strategies/README.md)
- [GEX Engine Integration](functions/GEX_ENGINE_QUICKSTART.md)
- [Multi-Tenancy Guide](TENANCY_MODEL.md)
- [Risk Management](PHASE3_RISK_MANAGEMENT_VERIFICATION.md)

---

**Built with ❤️ for 2026 Institutional Standards**
