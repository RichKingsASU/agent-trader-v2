# AgentTrader v2 — Agent Charter (Production)

## Agent roles
- **marketdata-mcp-server**: Market data serving + MCP interface (NO trading authority).
- **marketdata**: Optional ingest/aggregation service (NO trading authority).
- **strategy-engine**: Orchestrator. Reads signals, schedules evaluations. (NO order placement).
- **strategy-runtime**: Execution-only runtime. Places orders ONLY when explicitly enabled.
- **strategy-gamma / strategy-whale**: Strategy workloads running on strategy-runtime image.

## Authority boundaries (hard rules)
1. `strategy-engine` must never place orders.
2. Only `strategy-runtime` may place orders.
3. `strategy-runtime` must refuse to trade unless `AGENT_MODE=LIVE`.

## Safety modes
- `AGENT_MODE=DISABLED`: start up, log, serve health, but do not trade.
- `AGENT_MODE=WARMUP`: connect and validate dependencies, still no trading.
- `AGENT_MODE=LIVE`: trading allowed.
- `AGENT_MODE=HALTED`: emergency stop; refuse all trading.

## Required startup log fields
Every agent must log:
- agent_name
- git_sha
- intent
- agent_mode
- env (prod/stage/dev)

## Degrade safely
If market data is stale or missing:
- strategy-engine must stop scheduling
- strategy-runtime must refuse execution
