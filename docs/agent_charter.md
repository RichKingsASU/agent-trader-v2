# Agent Charter

## Authority boundary (order placement)

- **Single choke point**: All real order placement must flow through `backend.execution.engine.ExecutionEngine.execute_intent()` which enforces `require_live_mode(action="place_order")` before calling the broker.
- **Global mode switch**: `AGENT_MODE` is parsed from the environment with allowed values: `DISABLED`, `WARMUP`, `LIVE`, `HALTED`.
- **Fail-closed**: Any missing/unknown `AGENT_MODE` behaves as `DISABLED`.
- **Emergency stop**: `AGENT_MODE=HALTED` refuses trading even if other flags (like `EXEC_DRY_RUN=0`) would otherwise allow execution.
- **Runtime boundary**:
  - Non-execution workloads (e.g. strategy pods, MCP server) are deployed with `AGENT_MODE=DISABLED`.
  - Only the execution deployment is permitted to be configured to `AGENT_MODE=LIVE`.

## GUARD VERIFICATION

### Confirm env is set (K8s)

```bash
kubectl -n trading-floor get statefulset/gamma-strategy -o jsonpath='{.spec.template.spec.containers[0].env}' | tr -s ' ' '\n' | head
kubectl -n trading-floor get statefulset/whale-strategy -o jsonpath='{.spec.template.spec.containers[0].env}' | tr -s ' ' '\n' | head
kubectl -n trading-floor get deploy/marketdata-mcp-server -o jsonpath='{.spec.template.spec.containers[0].env}' | tr -s ' ' '\n' | head
```

Expected: `AGENT_MODE` is present and equals `DISABLED`.

### Confirm refusal behavior (execution engine)

- **When `AGENT_MODE!=LIVE`** and `EXEC_DRY_RUN=0`, the execution engine must refuse placement:

```bash
kubectl -n trading-floor logs deploy/execution-engine --tail=200 | rg "trading_refused|AGENT_MODE="
```

Expected: log lines showing refusal (HTTP 409) and a reason like `Refusing to place_order: AGENT_MODE=DISABLED` or `AGENT_MODE=HALTED`.

- **When `AGENT_MODE=LIVE`** and `EXEC_DRY_RUN=0`, broker placement is allowed and you should see an `exec.order_placed` audit log:

```bash
kubectl -n trading-floor logs deploy/execution-engine --tail=200 | rg "exec\\.order_placed|broker_order_id"
```

