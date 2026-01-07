## AgentTrader v2 — Deployment Report

- **Generated (UTC)**: 2026-01-07T00:39:17Z
- **kubectl context**: `UNKNOWN`
- **cluster**: `UNKNOWN`
- **user**: `UNKNOWN`
- **namespace**: `trading-floor`
- **cluster access**: **no** (report degraded: kubectl -n trading-floor get deployments -o json -l app.kubernetes.io/part-of=agent-trader-v2 failed (rc=127): [Errno 2] No such file or directory: 'kubectl')

## Executive summary

- **Workloads found**: 0 (Deployments=0, StatefulSets=0, Jobs=0)
- **Healthy (sampled)**: 0
- **Degraded**: 0
- **Halted / not allowed**: 0

## LIVE vs OFF

| Workload | Kind | Allowed to run | Reason | Replicas ready |
| --- | --- | --- | --- | --- |

## Top Issues

- _None detected (based on current sampling)._

## Recommended Actions

- Ensure kubectl is installed and configured to reach the cluster (context + RBAC).

## Workloads
