# Trading Floor Make Workflow (AgentTrader v2)

This repo standardizes day-to-day platform operations behind a single entrypoint: the root `Makefile`.

Design goals:
- **Deterministic and minimal**: common operations are reproducible and discoverable.
- **Safe by default**: **does not enable trading execution** and enforces the cluster kill-switch posture.
- **Graceful degradation**: when `kubectl`/cluster access is missing, targets print clear guidance.

## Day 0 setup (local)

- **Install prerequisites**
  - `bash`, `make`
  - `python3` (for `make report`, `make test`)
  - `kubectl` (for `make status/readiness/logs/scale/port-forward`)
  - Optional:
    - `ruff` (python formatting/lint)
    - `yamlfmt` / `yamllint` (yaml formatting/lint)
    - `docker` (for `make build`)

- **Set your cluster context + namespace**

By default the Makefile uses:
- `NAMESPACE=default`
- the **current** kubectl context

For AgentTrader v2 “Trading Floor”, typical values are:

```bash
export NAMESPACE=trading-floor
# optional:
export CONTEXT=<your-kube-context>
export MISSION_CONTROL_URL=http://agenttrader-mission-control
```

Then:

```bash
make help
```

## Common flows

- **Standard safe deploy flow**

```bash
make guard && make deploy && make report
```

- **Pre-market readiness**

```bash
make readiness
```

Notes:
- `make readiness` **fails** if:
  - `kubectl` is missing / the cluster is unreachable
  - workloads are not rolled out and ready
  - the cluster kill-switch (`configmap/agenttrader-kill-switch`) is missing or not set to `EXECUTION_HALTED=1`

- **Tail logs for a workload**

```bash
make logs AGENT=strategy-engine
```

## Troubleshooting

- **Wrong namespace**
  - Symptom: “not found” errors for workloads/services.
  - Fix:

```bash
make status NAMESPACE=trading-floor
```

- **Wrong kubectl context**
  - Symptom: cluster unreachable or shows unexpected workloads.
  - Fix: set `CONTEXT` (or switch your current kubectl context).

```bash
make status CONTEXT=<expected-context> NAMESPACE=trading-floor
```

- **Readiness fails due to kill-switch**
  - Symptom: `EXECUTION_HALTED` is not `1`.
  - Fix: restore the safe posture and re-apply the configmap (do **not** enable trading execution unintentionally).

## Reference

- `make help` lists all available targets and common overridable variables.

