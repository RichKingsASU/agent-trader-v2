# AgentTrader v2 — Agents

## Minimal viable trading floor (today)
- marketdata-mcp-server (must be healthy)
- strategy-engine (must be healthy)
- strategies scaled to 0 until validated

## Operational commands
```bash
kubectl -n trading-floor get pods -o wide
kubectl -n trading-floor logs deploy/marketdata-mcp-server --tail=200
kubectl -n trading-floor logs deploy/strategy-engine --tail=200
```
