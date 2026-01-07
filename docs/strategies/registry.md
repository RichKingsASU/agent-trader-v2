# Strategy Config Registry (Git-native, versioned, auditable)

AgentTrader v2 uses a **repo-native Strategy Config Registry** to control which strategies can run and in what mode.  
This is designed to be **safe-by-default**, auditable, and compatible with GitOps (and future UI).

## Filesystem layout

Strategy configs live here:

- `configs/strategies/`

Each strategy is a **single YAML file** (preferred) with a stable `strategy_id`:

- `configs/strategies/gamma.yaml`
- `configs/strategies/whale.yaml`
- `configs/strategies/naive_flow_trend.yaml`

Override directory at runtime:

- `STRATEGY_CONFIG_DIR` (default: `configs/strategies`)

## Schema (high level)

Each config maps to `backend/strategies/registry/models.py::StrategyConfig`:

- **strategy_id**: stable unique id (string)
- **strategy_name**: display name
- **strategy_type**: e.g. `gamma`, `whale`, `utbot`, `rsi`
- **enabled**: boolean, default `false`
- **mode**: `EVAL_ONLY | PROPOSE_ONLY | EXECUTE` (default `EVAL_ONLY`)
- **symbols**: list of tickers (default `["SPY","IWM"]` if omitted)
- **parameters**: dict (strategy-specific knobs; must be JSON-serializable)
- **risk**: dict (minimal limits are OK)
- **schedule**: optional dict
- **version**: `{ config_version, git_sha }` (`git_sha` injected at load time if available)
- **approvals**: `{ requires_human_approval, approved_by, approved_at_utc }`

## Safe defaults / fail-closed behavior

- **Disabled by default**: if `enabled` is omitted, it is treated as `false`.
- **Execution is gated**:
  - Even if a config sets `mode: EXECUTE`, the runtime will not allow effective execution unless:
    - `AGENT_MODE=LIVE`, and
    - `ALLOW_STRATEGY_EXECUTION=true` (stub allow flag), and
    - the strategy is `enabled: true`
- **If `AGENT_MODE` is not LIVE** (`DISABLED`, `WARMUP`, or `HALTED`), the registry forces `effective_mode=EVAL_ONLY`.

## Symbol allowlist (optional)

If you define an allowlist, it will be enforced:

- `STRATEGY_SYMBOL_ALLOWLIST="SPY,IWM,QQQ"`
  - OR add `configs/strategies/symbol_allowlist.txt` (one symbol per line)

## Adding a new strategy config (GitOps)

- Create `configs/strategies/<strategy_id>.yaml`
- Keep it safe initially:
  - `enabled: false`
  - `mode: EVAL_ONLY`
- Commit via PR for auditability.

## Read-only API endpoints

If running the Strategy Service:

- `GET /strategies/configs`
- `GET /strategies/configs/{strategy_id}`

Responses include `effective_mode`, computed from `AGENT_MODE` and safety gating.

