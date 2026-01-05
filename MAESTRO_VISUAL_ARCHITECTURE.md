# 🎭 Maestro Orchestration Layer - Visual Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          TRADING SYSTEM FLOW                            │
└─────────────────────────────────────────────────────────────────────────┘

   ┌──────────────┐
   │ Market Data  │────────┐
   │ • SPY Price  │        │
   │ • QQQ Price  │        │
   │ • VIX Level  │        │
   │ • GEX Data   │        │
   └──────────────┘        │
                           │
   ┌──────────────┐        │       ┌─────────────────────────────────┐
   │  Account     │────────┼──────>│   StrategyLoader                │
   │  Snapshot    │        │       │   ┌─────────────────────────┐   │
   │ • Equity     │        │       │   │  Strategy Discovery      │   │
   │ • Positions  │        │       │   │  • GammaScalper         │   │
   │ • Buy Power  │        │       │   │  • MomentumTrader       │   │
   └──────────────┘        │       │   │  • CongressionalAlpha   │   │
                           └──────>│   │  • [Auto-discovered]    │   │
   ┌──────────────┐                │   └─────────────────────────┘   │
   │ Regime Data  │────────────────│            │                     │
   │ • Volatility │                │            ▼                     │
   │ • Net GEX    │                │   ┌─────────────────────────┐   │
   └──────────────┘                │   │  Parallel Evaluation     │   │
                                   │   │  (asyncio.gather)        │   │
                                   │   └─────────────────────────┘   │
                                   └─────────────────────────────────┘
                                              │
                                              ▼
                                   ┌─────────────────────────────────┐
                                   │   Raw Signals (Unorchestrated)   │
                                   │   {                              │
                                   │     "GammaScalper": {            │
                                   │       action: "BUY",             │
                                   │       allocation: 0.5            │
                                   │     },                           │
                                   │     "MomentumTrader": {          │
                                   │       action: "SELL",            │
                                   │       allocation: 0.3            │
                                   │     }                            │
                                   │   }                              │
                                   └─────────────────────────────────┘
                                              │
                                              ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                       🎭 MAESTRO ORCHESTRATION LAYER                      │
│                                                                           │
│  ╔═══════════════════════════════════════════════════════════════════╗  │
│  ║  Step 1: Sharpe-Based Weight Calculation                          ║  │
│  ╚═══════════════════════════════════════════════════════════════════╝  │
│                                                                           │
│    ┌─────────────────────────────────────────────────────────────┐      │
│    │ Fetch Performance Data (Last 30 Days)                        │      │
│    │ Path: tenants/{tid}/strategy_performance/                    │      │
│    │                                                               │      │
│    │ For each strategy:                                           │      │
│    │   • Get daily P&L                                            │      │
│    │   • Calculate returns: pnl / BASE_CAPITAL                    │      │
│    │   • Calculate Sharpe: sqrt(252) × mean / std                 │      │
│    │   • Apply allocation rules:                                  │      │
│    │                                                               │      │
│    │     Sharpe >= 1.0 → ACTIVE (100% allocation)                │      │
│    │     0.5 ≤ Sharpe < 1.0 → REDUCED (50% allocation)           │      │
│    │     Sharpe < 0.5 → SHADOW_MODE (0% allocation)              │      │
│    └─────────────────────────────────────────────────────────────┘      │
│                           ▼                                              │
│  ╔═══════════════════════════════════════════════════════════════════╗  │
│  ║  Step 2: Apply Allocation Adjustments                             ║  │
│  ╚═══════════════════════════════════════════════════════════════════╝  │
│                                                                           │
│    Weighted Signals = {                                                  │
│      "GammaScalper": {                                                   │
│        action: "BUY",                                                    │
│        allocation: 0.25,  ← 0.5 × 0.5 (reduced by 50%)                  │
│        mode: "REDUCED",                                                  │
│        sharpe_ratio: 0.85                                                │
│      },                                                                  │
│      "CongressionalAlpha": {                                             │
│        action: "BUY",                                                    │
│        allocation: 0.0,  ← Shadow mode                                  │
│        mode: "SHADOW_MODE",                                              │
│        sharpe_ratio: 0.32                                                │
│      }                                                                   │
│    }                                                                     │
│                           ▼                                              │
│  ╔═══════════════════════════════════════════════════════════════════╗  │
│  ║  Step 3: Systemic Risk Detection & Override                       ║  │
│  ╚═══════════════════════════════════════════════════════════════════╝  │
│                                                                           │
│    Count SELL signals across all strategies                             │
│    │                                                                     │
│    ├─ SELL count < 3 → No override, proceed                            │
│    │                                                                     │
│    └─ SELL count ≥ 3 → 🚨 SYSTEMIC RISK DETECTED                       │
│                         Override ALL BUY signals to HOLD                │
│                         Preserve liquidity                              │
│                           ▼                                              │
│  ╔═══════════════════════════════════════════════════════════════════╗  │
│  ║  Step 4: JIT Identity Enrichment                                  ║  │
│  ╚═══════════════════════════════════════════════════════════════════╝  │
│                                                                           │
│    For each signal, add:                                                 │
│      • agent_id: "{tenant}_{strategy}"                                  │
│      • nonce: 32-char hex (cryptographically random)                    │
│      • session_id: "maestro_{timestamp}_{random}"                       │
│      • identity_timestamp: ISO-8601 timestamp                           │
│                                                                           │
│    Prevents:                                                             │
│      ✓ Double-spend (same nonce can't be reused)                        │
│      ✓ Agent sprawl (complete signal traceability)                      │
│      ✓ Audit gaps (full identity chain)                                 │
│                           ▼                                              │
│  ╔═══════════════════════════════════════════════════════════════════╗  │
│  ║  Step 5: AI Summary Generation (Gemini)                           ║  │
│  ╚═══════════════════════════════════════════════════════════════════╝  │
│                                                                           │
│    Build prompt with:                                                    │
│      • All allocation decisions                                          │
│      • Sharpe ratios and reasoning                                       │
│      • Systemic risk events                                              │
│      • Signal overrides                                                  │
│                                                                           │
│    Generate 2-3 sentence executive summary                               │
│                           ▼                                              │
│  ╔═══════════════════════════════════════════════════════════════════╗  │
│  ║  Step 6: Log to Firestore                                         ║  │
│  ╚═══════════════════════════════════════════════════════════════════╝  │
│                                                                           │
│    Path: systemStatus/orchestration_logs/logs/{timestamp}_{session}     │
│    Contains:                                                             │
│      • Complete MaestroDecision object                                   │
│      • All allocation adjustments                                        │
│      • Systemic risk details                                             │
│      • AI summary                                                        │
│      • Timestamp and session ID                                          │
│                                                                           │
└───────────────────────────────────────────────────────────────────────────┘
                                   ▼
                      ┌────────────────────────────┐
                      │  Orchestrated Signals      │
                      │  • Weighted allocations    │
                      │  • Risk overrides applied  │
                      │  • JIT Identity attached   │
                      │  • Ready for execution     │
                      └────────────────────────────┘
                                   ▼
                      ┌────────────────────────────┐
                      │   Trade Execution Engine   │
                      │   • Respect modes          │
                      │   • Handle overrides       │
                      │   • Track identities       │
                      │   • Execute via Alpaca     │
                      └────────────────────────────┘
```

## Data Flow Detail

### 1. Performance Data Collection

```
Daily Trading Loop (every 5 minutes)
  │
  ├─> Execute trades
  │
  ├─> Log to ledger_trades
  │     • Fill-level tracking
  │     • FIFO cost basis
  │     • Fees and slippage
  │
  └─> Monthly aggregation (scheduled)
        │
        ├─> Calculate realized P&L
        │
        ├─> Calculate unrealized P&L
        │
        └─> Write to strategy_performance
              Path: tenants/{tid}/strategy_performance/{perf_id}
              Format: {uid}_{strategy_id}_{year}_{month}
```

### 2. Sharpe Ratio Calculation

```
Input: Last 30 days of performance snapshots

For each strategy:
  ┌─────────────────────────────────────────────────┐
  │ 1. Fetch daily P&L values                       │
  │    [100, 120, 110, 130, 125, ...]              │
  └─────────────────────────────────────────────────┘
           │
           ▼
  ┌─────────────────────────────────────────────────┐
  │ 2. Convert to percentage returns                │
  │    daily_returns = pnl / BASE_CAPITAL           │
  │    [0.01, 0.012, 0.011, 0.013, ...]            │
  └─────────────────────────────────────────────────┘
           │
           ▼
  ┌─────────────────────────────────────────────────┐
  │ 3. Calculate statistics                         │
  │    mean_return = sum(returns) / len(returns)    │
  │    std_dev = sqrt(variance)                     │
  └─────────────────────────────────────────────────┘
           │
           ▼
  ┌─────────────────────────────────────────────────┐
  │ 4. Calculate Sharpe Ratio                       │
  │    RISK_FREE = 0.04 / 252  (daily rate)         │
  │    sharpe = (mean - rf) / std_dev               │
  │    sharpe_annual = sharpe × sqrt(252)           │
  └─────────────────────────────────────────────────┘
           │
           ▼
  ┌─────────────────────────────────────────────────┐
  │ 5. Apply allocation rules                       │
  │                                                  │
  │    if sharpe >= 1.0:                            │
  │        mode = ACTIVE, weight = 1.0              │
  │    elif sharpe >= 0.5:                          │
  │        mode = REDUCED, weight = 0.5             │
  │    else:                                         │
  │        mode = SHADOW_MODE, weight = 0.0         │
  └─────────────────────────────────────────────────┘
```

### 3. Systemic Risk Detection

```
For all evaluated signals:

┌────────────────────────────────┐
│ Count by action:               │
│   SELL: 4                      │   ┌──> ≥ 3 SELLs: SYSTEMIC RISK
│   BUY: 3                       │   │
│   HOLD: 2                      │   │
└────────────────────────────────┘   │
                │                     │
                ▼                     │
         ┌──────────────┐            │
         │ SELL >= 3?   │────────────┘
         └──────────────┘
                │ Yes
                ▼
    ┌─────────────────────────────────────┐
    │ Override Logic:                     │
    │   For each signal:                  │
    │     if action == "BUY":             │
    │         action = "HOLD"             │
    │         confidence = 0.0            │
    │         add override_reason         │
    │     else:                           │
    │         keep original action        │
    └─────────────────────────────────────┘
                │
                ▼
    ┌─────────────────────────────────────┐
    │ Log systemic risk event:            │
    │   • Count of SELL signals           │
    │   • Number of overrides applied     │
    │   • Modified strategies list        │
    │   • Reason for intervention         │
    └─────────────────────────────────────┘
```

### 4. JIT Identity System

```
For each signal:

┌─────────────────────────────────────────────┐
│ Generate AgentIdentity:                     │
│                                             │
│   agent_id = f"{tenant}_{strategy}"        │
│   ├─> Example: "prod_GammaScalper"        │
│   │                                         │
│   nonce = secrets.token_hex(16)            │
│   ├─> 32-char hex: "a1b2c3d4e5f6..."     │
│   │    Cryptographically random             │
│   │    Probability of collision ≈ 0        │
│   │                                         │
│   session_id = f"maestro_{ts}_{random}"   │
│   ├─> Example: "maestro_1735560000_x9y8"  │
│   │    Unique per invocation                │
│   │                                         │
│   timestamp = datetime.now(UTC)            │
│   └─> ISO-8601: "2025-12-30T12:00:00Z"    │
│                                             │
└─────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────┐
│ Attach to signal:                           │
│   {                                         │
│     "action": "BUY",                        │
│     "allocation": 0.5,                      │
│     "agent_id": "prod_GammaScalper",       │
│     "nonce": "a1b2c3d4e5f6...",            │
│     "session_id": "maestro_1735560000...",  │
│     "identity_timestamp": "2025-12-30..."   │
│   }                                         │
└─────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────┐
│ Prevention guarantees:                      │
│                                             │
│   ✓ No duplicate nonces within session     │
│   ✓ Complete audit trail via agent_id      │
│   ✓ Session-level grouping                 │
│   ✓ Timestamp ordering                     │
│   ✓ Can detect double-spend attempts       │
│                                             │
└─────────────────────────────────────────────┘
```

## Real-World Example

### Scenario: Market Downturn with Multiple Strategies

**Initial State (9:30 AM)**
```
Market:
  SPY: $450.00 (-2.5% pre-market)
  VIX: 32 (elevated)
  Net GEX: -$500M (negative, bearish)

Strategies Performance (30-day Sharpe):
  GammaScalper: 1.52  ✓ Healthy
  MomentumTrader: 0.82  ⚠️ Declining
  CongressionalAlpha: 0.35  🚫 Failing
  OptionsArbitrage: 1.21  ✓ Healthy
```

**Step 1: Strategy Evaluation**
```
Raw Signals:
  GammaScalper: SELL (bearish GEX)
  MomentumTrader: SELL (downtrend)
  CongressionalAlpha: BUY (delayed Congress data)
  OptionsArbitrage: SELL (IV spike)
```

**Step 2: Maestro Allocation Adjustment**
```
Sharpe-Based Weighting:
  GammaScalper:
    Original: 50% allocation
    Sharpe: 1.52 → ACTIVE
    Final: 50% allocation ✓

  MomentumTrader:
    Original: 30% allocation
    Sharpe: 0.82 → REDUCED
    Final: 15% allocation (50% reduction)

  CongressionalAlpha:
    Original: 40% allocation
    Sharpe: 0.35 → SHADOW_MODE
    Final: 0% allocation (paper trading only)

  OptionsArbitrage:
    Original: 30% allocation
    Sharpe: 1.21 → ACTIVE
    Final: 30% allocation ✓
```

**Step 3: Systemic Risk Detection**
```
Count signals:
  SELL: 3 (GammaScalper, MomentumTrader, OptionsArbitrage)
  BUY: 1 (CongressionalAlpha)

🚨 SYSTEMIC RISK DETECTED (3 SELL signals)

Override:
  CongressionalAlpha: BUY → HOLD
  Reason: "Maestro systemic risk override: 3 strategies signaling SELL"
```

**Step 4: Final Orchestrated Signals**
```
{
  "GammaScalper": {
    "action": "SELL",
    "allocation": 0.50,
    "mode": "ACTIVE",
    "agent_id": "prod_GammaScalper",
    "nonce": "a1b2c3d4...",
    "session_id": "maestro_1735560000_xyz"
  },
  
  "MomentumTrader": {
    "action": "SELL",
    "allocation": 0.15,  ← Reduced from 0.30
    "original_allocation": 0.30,
    "weight_multiplier": 0.5,
    "mode": "REDUCED",
    "agent_id": "prod_MomentumTrader",
    "nonce": "b2c3d4e5...",
    "session_id": "maestro_1735560000_xyz"
  },
  
  "CongressionalAlpha": {
    "action": "HOLD",  ← Overridden from BUY
    "original_action": "BUY",
    "allocation": 0.0,  ← Shadow mode
    "mode": "SHADOW_MODE",
    "override_reason": "Maestro systemic risk override: 3 strategies signaling SELL",
    "confidence": 0.0,
    "agent_id": "prod_CongressionalAlpha",
    "nonce": "c3d4e5f6...",
    "session_id": "maestro_1735560000_xyz"
  },
  
  "OptionsArbitrage": {
    "action": "SELL",
    "allocation": 0.30,
    "mode": "ACTIVE",
    "agent_id": "prod_OptionsArbitrage",
    "nonce": "d4e5f6g7...",
    "session_id": "maestro_1735560000_xyz"
  }
}
```

**Step 5: AI Summary**
```
🎭 Maestro Summary:

"Maestro reduced Momentum Trader allocation by 50% due to 0.82 Sharpe decay 
and moved Congressional Alpha to shadow mode (Sharpe: 0.35). Systemic risk 
override engaged as 3 strategies signaled SELL, protecting capital by preventing 
Congressional Alpha's delayed BUY signal during market downturn."
```

**Outcome**
- ✅ Protected capital by reducing exposure to declining strategy
- ✅ Prevented poor-performing strategy from executing trades
- ✅ Detected systemic risk and overrode counter-trend signal
- ✅ Complete audit trail with JIT Identity
- ✅ Human-readable AI explanation of decisions

## File Locations

```
functions/
├── strategies/
│   ├── __init__.py                      # Exports MaestroController
│   ├── loader.py                        # Enhanced with Maestro
│   ├── maestro_controller.py            # Main orchestration logic
│   ├── base.py                          # Strategy base class
│   ├── example_maestro_integration.py   # Complete example
│   ├── MAESTRO_QUICKSTART.md           # Quick start guide
│   │
│   └── [Your strategies here]
│       ├── gamma_scalper.py
│       ├── momentum_trader.py
│       └── congressional_alpha.py

MAESTRO_ORCHESTRATION_IMPLEMENTATION.md  # Full documentation
MAESTRO_VISUAL_ARCHITECTURE.md           # This file
tests/test_maestro_orchestration.py      # Comprehensive tests
```

## Firestore Collections

```
firestore/
├── tenants/{tenant_id}/
│   ├── strategy_performance/
│   │   └── {perf_id}                    # Input: Daily P&L
│   │       • realized_pnl
│   │       • unrealized_pnl
│   │       • period_start/end
│   │
│   ├── trade_log/
│   │   └── {trade_id}                   # Output: Executed trades
│   │       • agent_id
│   │       • nonce
│   │       • session_id
│   │       • allocation
│   │
│   └── shadow_pnl/
│       └── {shadow_id}                  # Shadow mode tracking
│           • strategy_name
│           • mode: "SHADOW_MODE"
│
└── systemStatus/
    └── orchestration_logs/
        └── logs/
            └── {timestamp}_{session}     # Output: Maestro decisions
                • allocation_decisions
                • systemic_risk_detected
                • ai_summary
```

---

**Built for 2026 Institutional Standards**
- Multi-Agent Coordination ✓
- Environment Awareness ✓
- Identity-Based Security ✓
- Real-Time Risk Management ✓
- Automated Journaling & Grading ✓
