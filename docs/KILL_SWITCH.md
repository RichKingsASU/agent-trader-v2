# Global Kill Switch (Execution Halt)

Standard name: **`EXECUTION_HALTED`**

When enabled, **execution agents refuse trading** (no broker order placement). Non-execution services keep running but **log that the kill switch is active**.

## How it works

- **Env var**: `EXECUTION_HALTED=1` enables the kill switch.
- **Kubernetes recommended**: mount a ConfigMap key as a file and set:
  - `EXECUTION_HALTED_FILE=/etc/agenttrader/kill-switch/EXECUTION_HALTED`
  - File contents: `1` (halt) / `0` (allow)
  - ConfigMap volume mounts update in-place, so agents see changes **without restarting pods**.

Back-compat (deprecated but still honored): `EXEC_KILL_SWITCH=1`.

## KILL SWITCH DRILL (Kubernetes)

Assumptions:
- Namespace: `trading-floor`
- ConfigMap: `agenttrader-kill-switch`
- Workloads already mount the ConfigMap at `/etc/agenttrader/kill-switch/EXECUTION_HALTED`

### 0) Verify current state

```bash
kubectl -n trading-floor get configmap agenttrader-kill-switch -o jsonpath='{.data.EXECUTION_HALTED}{"\n"}'
```

Expected output:
- `0` (execution allowed), or
- `1` (execution halted)

### 1) Enable kill switch (halt execution)

```bash
kubectl -n trading-floor patch configmap agenttrader-kill-switch --type merge -p '{"data":{"EXECUTION_HALTED":"1"}}'
```

Expected behavior:
- Execution agents begin rejecting trade execution **immediately** (as soon as they re-check the file, typically within seconds).
- Non-execution services continue serving but will show a startup/runtime log warning.

### 2) Expected logs (examples)

- **Execution service** (`backend/services/execution_service`):
  - Startup (if active at boot):
    - `kill_switch_active enabled=true source=file:/etc/agenttrader/kill-switch/EXECUTION_HALTED`
  - Any execute request will result in a rejection (HTTP 409) with risk reason `kill_switch_enabled`.

- **Strategy service** (`backend/strategy_service`):
  - Startup:
    - `kill_switch_active enabled=true source=file:/etc/agenttrader/kill-switch/EXECUTION_HALTED`
  - If a request tries the non-shadow “LIVE” path, it is blocked with HTTP 409 and detail `{"error":"kill_switch_enabled", ...}`.

- **Marketdata MCP server** (`mcp/server/index.js`):
  - Startup:
    - `[mcp] kill_switch_active enabled=true source=file:/etc/agenttrader/kill-switch/EXECUTION_HALTED`

### 3) Disable kill switch (resume execution)

```bash
kubectl -n trading-floor patch configmap agenttrader-kill-switch --type merge -p '{"data":{"EXECUTION_HALTED":"0"}}'
```

Expected behavior:
- Execution agents stop rejecting new broker-side actions (subject to other risk controls).

### 4) Emergency alternative (env var rollout)

If you can’t rely on the ConfigMap volume update, force the env var and restart the workload:

```bash
kubectl -n trading-floor set env statefulset/gamma-strategy EXECUTION_HALTED=1
kubectl -n trading-floor set env statefulset/whale-strategy EXECUTION_HALTED=1
kubectl -n trading-floor rollout restart deployment/marketdata-mcp-server
```

Note: env var changes require a rollout/restart to take effect in running pods.

