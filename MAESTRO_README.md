# 🎭 Maestro Orchestration Layer

> **The Intelligent Multi-Agent Coordinator for Your Agentic AI Trading Fund**

Maestro is a sophisticated orchestration system that sits above your trading strategies to manage agent sprawl, dynamically allocate capital based on performance, detect systemic risk, and provide complete auditability with AI-powered insights.

## 🚀 Quick Links

- **[Quick Start Guide](functions/strategies/MAESTRO_QUICKSTART.md)** - Get running in 5 minutes
- **[Full Implementation Guide](MAESTRO_ORCHESTRATION_IMPLEMENTATION.md)** - Complete documentation
- **[Visual Architecture](MAESTRO_VISUAL_ARCHITECTURE.md)** - Flow diagrams and examples
- **[Example Integration](functions/strategies/example_maestro_integration.py)** - Production-ready code
- **[Tests](tests/test_maestro_orchestration.py)** - Comprehensive test suite

## ✨ What Does Maestro Do?

### 1. **Dynamic Capital Allocation** 📊
Automatically adjusts strategy allocations based on 30-day Sharpe Ratios:
- **Sharpe ≥ 1.0**: Full allocation (100%)
- **0.5 ≤ Sharpe < 1.0**: Reduced allocation (50%)
- **Sharpe < 0.5**: Shadow mode (0% - paper trading only)

### 2. **Systemic Risk Detection** 🚨
Monitors all strategies for coordinated sell-offs:
- If **3+ strategies signal SELL** simultaneously → Override ALL BUY signals to HOLD
- Preserves liquidity during market stress
- Prevents cascading losses

### 3. **Just-In-Time Identity** 🔐
Every signal gets a unique identity to prevent:
- ❌ **Double-spend**: Two strategies using the same buying power
- ❌ **Agent sprawl**: Untracked duplicate executions
- ❌ **Audit gaps**: Missing attribution
- ✅ Complete signal traceability with `agent_id`, `nonce`, and `session_id`

### 4. **AI-Powered Summaries** 🤖
Gemini generates human-readable insights:
> *"Maestro reduced Gamma Scalper allocation by 50% due to 0.85 Sharpe decay. Systemic risk override engaged as 4 strategies signaled SELL, protecting capital."*

### 5. **Complete Auditability** 📝
Every decision logged to Firestore:
- Allocation adjustments with reasoning
- Sharpe Ratios and performance metrics
- Systemic risk events
- Signal modifications
- Timestamps and session tracking

## 🎯 Why Use Maestro?

| Without Maestro | With Maestro |
|----------------|--------------|
| 😰 Strategies compete for capital | 🎭 Coordinated allocation based on performance |
| 🔥 Poorly performing strategies drain capital | 📊 Automatic reduction/shadow mode for underperformers |
| 💥 Multiple strategies can trigger sell-offs | 🛡️ Systemic risk detection prevents cascades |
| 🕵️ No visibility into why signals changed | 📝 Complete audit trail with AI explanations |
| 🐛 Risk of double-spend bugs | 🔐 JIT Identity prevents duplicate executions |

## 📦 Installation

### Prerequisites
```bash
pip install firebase-admin google-cloud-firestore vertexai
```

### File Structure
```
functions/strategies/
├── maestro_controller.py       # Core orchestration logic ✨ NEW
├── loader.py                   # Enhanced with Maestro integration ✨ UPDATED
├── base.py                     # Strategy interface
└── [your strategies]
```

## 🏁 3-Step Integration

### Step 1: Initialize with Firestore

```python
from firebase_admin import firestore
from functions.strategies.loader import StrategyLoader

# OLD: Basic loader (no Maestro)
# loader = StrategyLoader()

# NEW: Maestro-enabled loader
db = firestore.client()
loader = StrategyLoader(
    db=db,
    tenant_id="my-tenant",  # Your tenant ID
    uid="user123"           # Optional: user-specific metrics
)
```

### Step 2: Use Orchestrated Evaluation

```python
# Evaluate with Maestro orchestration
signals, maestro_decision = await loader.evaluate_all_strategies_with_maestro(
    market_data=market_data,
    account_snapshot=account_snapshot,
    regime=gex_regime_data  # Optional
)

# View AI summary
print(f"🎭 {maestro_decision.ai_summary}")
```

### Step 3: Handle Orchestrated Signals

```python
for strategy_name, signal in signals.items():
    # Check mode
    if signal.get("mode") == "SHADOW_MODE":
        log_shadow_trade(signal)  # Paper trade only
        continue
    
    # Check for overrides
    if "override_reason" in signal:
        print(f"⚠️ Overridden: {signal['override_reason']}")
    
    # Execute with Maestro-adjusted allocation
    allocation = signal.get("allocation", 0.0)
    if signal["action"] == "BUY" and allocation > 0:
        execute_trade(
            signal=signal,
            allocation=allocation,
            agent_id=signal["agent_id"],  # JIT Identity
            nonce=signal["nonce"]
        )
```

## 📊 Real Example

### Input: 4 Strategies with Different Performance

```python
Strategies Performance (30-day Sharpe):
  GammaScalper: 1.52       # ✓ Healthy
  MomentumTrader: 0.82     # ⚠️ Declining  
  CongressionalAlpha: 0.35 # 🚫 Failing
  OptionsArbitrage: 1.21   # ✓ Healthy

Raw Signals:
  GammaScalper: SELL
  MomentumTrader: SELL
  CongressionalAlpha: BUY
  OptionsArbitrage: SELL
```

### Maestro Processing

```python
1️⃣ Sharpe-Based Allocation:
  ✓ GammaScalper: 50% → 50% (ACTIVE, Sharpe 1.52)
  ⚠️ MomentumTrader: 30% → 15% (REDUCED by 50%, Sharpe 0.82)
  🚫 CongressionalAlpha: 40% → 0% (SHADOW_MODE, Sharpe 0.35)
  ✓ OptionsArbitrage: 30% → 30% (ACTIVE, Sharpe 1.21)

2️⃣ Systemic Risk Detection:
  🚨 3 SELL signals detected → SYSTEMIC RISK
  Override: CongressionalAlpha BUY → HOLD

3️⃣ JIT Identity:
  ✅ Added agent_id, nonce, session_id to all signals

4️⃣ AI Summary:
  "Maestro reduced Momentum Trader by 50% due to 0.82 Sharpe decay
   and moved Congressional Alpha to shadow mode. Systemic risk
   override engaged as 3 strategies signaled SELL."
```

### Output: Orchestrated Signals

```python
{
  "GammaScalper": {
    "action": "SELL",
    "allocation": 0.50,
    "mode": "ACTIVE",
    "agent_id": "prod_GammaScalper",
    "nonce": "a1b2c3d4e5f6..."
  },
  
  "MomentumTrader": {
    "action": "SELL",
    "allocation": 0.15,  ← Reduced from 0.30
    "mode": "REDUCED",
    "agent_id": "prod_MomentumTrader",
    "nonce": "b2c3d4e5f6g7..."
  },
  
  "CongressionalAlpha": {
    "action": "HOLD",  ← Overridden from BUY
    "allocation": 0.0,  ← Shadow mode
    "mode": "SHADOW_MODE",
    "override_reason": "Maestro systemic risk override",
    "agent_id": "prod_CongressionalAlpha",
    "nonce": "c3d4e5f6g7h8..."
  },
  
  "OptionsArbitrage": {
    "action": "SELL",
    "allocation": 0.30,
    "mode": "ACTIVE",
    "agent_id": "prod_OptionsArbitrage",
    "nonce": "d4e5f6g7h8i9..."
  }
}
```

## 🎛️ Configuration

### Adjust Sharpe Thresholds

```python
from functions.strategies.maestro_controller import MaestroController

# Default
MaestroController.SHARPE_THRESHOLD_REDUCE = 1.0
MaestroController.SHARPE_THRESHOLD_SHADOW = 0.5

# More conservative (earlier intervention)
MaestroController.SHARPE_THRESHOLD_REDUCE = 1.5
MaestroController.SHARPE_THRESHOLD_SHADOW = 1.0

# More aggressive (longer runway)
MaestroController.SHARPE_THRESHOLD_REDUCE = 0.5
MaestroController.SHARPE_THRESHOLD_SHADOW = 0.0
```

### Adjust Risk Sensitivity

```python
# Default: 3+ SELL signals trigger override
MaestroController.SYSTEMIC_SELL_THRESHOLD = 3

# More sensitive
MaestroController.SYSTEMIC_SELL_THRESHOLD = 2

# Less sensitive
MaestroController.SYSTEMIC_SELL_THRESHOLD = 4
```

## 📈 Monitoring

### View Recent Decisions

```python
# Get orchestration logs
logs = db.collection("systemStatus") \
    .document("orchestration_logs") \
    .collection("logs") \
    .order_by("timestamp", direction=firestore.Query.DESCENDING) \
    .limit(10) \
    .stream()

for log in logs:
    data = log.to_dict()
    print(f"🎭 {data['timestamp']}: {data['ai_summary']}")
```

### Track Systemic Risk Events

```python
# Query for risk overrides
risk_events = db.collection("systemStatus") \
    .document("orchestration_logs") \
    .collection("logs") \
    .where("systemic_risk_detected", "==", True) \
    .stream()

for event in risk_events:
    data = event.to_dict()
    print(f"🚨 {data['timestamp']}: {data['systemic_risk_details']}")
```

## 🧪 Testing

Run the comprehensive test suite:

```bash
pytest tests/test_maestro_orchestration.py -v
```

Test coverage includes:
- ✅ JIT Identity generation and uniqueness
- ✅ Sharpe Ratio calculation
- ✅ Allocation decision logic
- ✅ Systemic risk detection
- ✅ Signal enrichment
- ✅ Full orchestration flow
- ✅ Integration with StrategyLoader

## 🏗️ Architecture

```
┌─────────────────┐
│ Market Data     │──┐
│ Account State   │  │
│ Regime Data     │  ├──> StrategyLoader
└─────────────────┘  │        │
                     │        ▼
                     │   Parallel Evaluation
                     │        │
                     │        ▼
                     │   Raw Signals
                     │        │
                     │        ▼
                     └──> 🎭 MAESTRO
                              │
                    ┌─────────┴─────────┐
                    │                   │
               Sharpe-Based        Systemic Risk
               Weighting           Detection
                    │                   │
                    └─────────┬─────────┘
                              │
                         JIT Identity
                              │
                         AI Summary
                              │
                          Logging
                              │
                              ▼
                    Orchestrated Signals
                              │
                              ▼
                      Trade Execution
```

## 📚 Documentation

- **[Quick Start](functions/strategies/MAESTRO_QUICKSTART.md)**: 5-minute integration guide
- **[Full Implementation](MAESTRO_ORCHESTRATION_IMPLEMENTATION.md)**: Complete technical documentation
- **[Visual Architecture](MAESTRO_VISUAL_ARCHITECTURE.md)**: Diagrams and flow charts
- **[Example Integration](functions/strategies/example_maestro_integration.py)**: Production-ready code
- **[API Reference](functions/strategies/maestro_controller.py)**: Source code with docstrings

## 🤝 Integration with Existing Systems

### Works With
- ✅ **GEX Engine**: Maestro respects market regime data
- ✅ **Multi-Tenancy**: Full tenant isolation and user-specific metrics
- ✅ **Risk Management**: Integrates with existing kill-switches
- ✅ **Backtesting**: Can simulate Maestro decisions historically
- ✅ **Shadow Mode**: Test new strategies without capital risk

### Backwards Compatible
- ✅ Existing strategies work without changes
- ✅ Can disable Maestro by omitting `db` parameter
- ✅ Falls back to traditional evaluation if Maestro unavailable

## 🎓 Learn More

### Core Concepts
1. **Sharpe Ratio**: Risk-adjusted return metric
2. **FIFO Accounting**: First-in-first-out P&L calculation
3. **JIT Identity**: Just-in-time agent identification
4. **Systemic Risk**: Coordinated market stress detection

### Best Practices
1. **Performance Tracking**: Ensure strategy_performance snapshots are current
2. **Threshold Tuning**: Adjust Sharpe thresholds based on your risk tolerance
3. **Shadow Mode**: Use for new strategies before going live
4. **Monitoring**: Set up alerts on orchestration logs
5. **Audit Trail**: Leverage JIT Identity for complete traceability

## 🚀 Next Steps

1. ✅ Follow [Quick Start Guide](functions/strategies/MAESTRO_QUICKSTART.md)
2. 📊 Ensure performance data is being collected
3. 🎛️ Tune thresholds for your risk profile
4. 📈 Set up monitoring dashboards
5. 🧪 Run tests to verify integration
6. 🚢 Deploy to production!

## 🏆 Results

With Maestro, you get:
- **Capital Efficiency**: Automatically reduce exposure to underperformers
- **Risk Protection**: Systemic risk detection prevents coordinated losses
- **Complete Auditability**: Every decision traceable with JIT Identity
- **AI Insights**: Human-readable summaries of complex decisions
- **Institutional Grade**: 2026 standards for multi-agent coordination

## 🙋 FAQ

**Q: Do I need to modify my existing strategies?**  
A: No! Maestro works with existing strategies without any changes.

**Q: What if I don't have 30 days of performance data?**  
A: Maestro defaults to full allocation (ACTIVE mode) for new strategies.

**Q: Can I disable Maestro temporarily?**  
A: Yes, use `evaluate_all_strategies()` instead of `evaluate_all_strategies_with_maestro()`.

**Q: Does Maestro work with backtesting?**  
A: Yes! You can simulate Maestro decisions on historical data.

**Q: What if Vertex AI is not available?**  
A: Maestro falls back to text summaries without Gemini.

**Q: Is Maestro tenant-aware?**  
A: Yes! Full multi-tenancy support with per-tenant orchestration.

## 📝 License

Part of the AgentTrader platform. See main repository for license details.

---

**Built with ❤️ for 2026 Institutional Standards**

*Questions? Issues? Check the [full documentation](MAESTRO_ORCHESTRATION_IMPLEMENTATION.md) or open an issue.*
