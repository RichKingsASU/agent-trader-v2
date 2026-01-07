## AgentTrader v2 — in-cluster service discovery (Kubernetes)

### Namespace + DNS suffix

All AgentTrader v2 workloads in this repo target the namespace:
- `trading-floor`

Kubernetes service DNS formats:
- **Short name (same namespace)**: `http://<service-name>`
- **Fully qualified**: `http://<service-name>.<namespace>.svc.cluster.local`

### Standardized ClusterIP Services (stable DNS)

Core services:
- **marketdata MCP server**: `http://agenttrader-marketdata-mcp-server`
  - FQDN: `http://agenttrader-marketdata-mcp-server.trading-floor.svc.cluster.local`
- **strategy engine (ops/management API)**: `http://agenttrader-strategy-engine`
  - FQDN: `http://agenttrader-strategy-engine.trading-floor.svc.cluster.local`
- **execution agent (execution engine API)**: `http://agenttrader-execution-agent`
  - FQDN: `http://agenttrader-execution-agent.trading-floor.svc.cluster.local`

Additional v2 workloads (if deployed):
- **gamma strategy runtime**: `http://agenttrader-gamma-strategy`
- **whale strategy runtime**: `http://agenttrader-whale-strategy`

### In-cluster curl checks (no port-forward, no pod IPs)

Create an ephemeral curl pod and hit service DNS names directly:

```bash
NS=trading-floor
kubectl -n "$NS" run tmp-curl --rm -i --restart=Never --image=curlimages/curl -- \
  sh -lc 'set -e; curl -fsS http://agenttrader-marketdata-mcp-server/healthz; echo; curl -fsS http://agenttrader-strategy-engine/healthz; echo'
```

Optional checks:

```bash
NS=trading-floor
kubectl -n "$NS" run tmp-curl --rm -i --restart=Never --image=curlimages/curl -- \
  sh -lc 'set -e; curl -fsS http://agenttrader-execution-agent/healthz; echo; curl -fsS http://agenttrader-strategy-engine/ops/status; echo'
```

### Service endpoints module (Python)

`backend/config/service_endpoints.py` provides env-overridable base URLs:
- `MARKETDATA_BASE_URL` (default `http://agenttrader-marketdata-mcp-server`)
- `STRATEGY_ENGINE_BASE_URL` (default `http://agenttrader-strategy-engine`)
- `EXECUTION_AGENT_BASE_URL` (default `http://agenttrader-execution-agent`)

Example: strategy-engine calling marketdata heartbeat:

```python
from backend.config.service_endpoints import MARKETDATA_BASE_URL

url = f"{MARKETDATA_BASE_URL}/healthz"
```

### Troubleshooting (selectors + DNS)

- **Service has no endpoints**:
  - Check selector vs pod labels:
    - `kubectl -n trading-floor get svc agenttrader-marketdata-mcp-server -o yaml`
    - `kubectl -n trading-floor get pods --show-labels`
  - Check endpoints:
    - `kubectl -n trading-floor get endpoints agenttrader-marketdata-mcp-server -o wide`
- **DNS not resolving**:
  - Verify CoreDNS is healthy:
    - `kubectl -n kube-system get pods -l k8s-app=kube-dns`
  - From a pod, run:
    - `nslookup agenttrader-marketdata-mcp-server`
    - `nslookup agenttrader-marketdata-mcp-server.trading-floor.svc.cluster.local`

