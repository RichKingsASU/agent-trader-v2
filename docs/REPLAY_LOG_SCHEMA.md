# Replay log schema (post-mortem decision reconstruction)

This repo emits **single-line JSON replay events** that can be extracted from service logs (including `kubectl logs` dumps) and turned into an **ordered decision timeline**.

## Schema version

- `replay_schema`: **`agenttrader.replay.v1`**

## Top-level fields

All replay events are JSON objects with these common fields:

- `replay_schema` *(string, required)*: schema identifier.
- `ts` *(string, required)*: ISO-8601 timestamp (UTC recommended).
- `event` *(string, required)*: one of:
  - `startup`
  - `state_transition`
  - `decision_checkpoint`
  - `order_intent`
- `trace_id` *(string, required)*: correlation id used to group timelines (prefer request/run id).
- `agent_name` *(string, required)*: the agent/service producing the event (e.g. `execution-engine`, or a `strategy_id`).
- `component` *(string, optional)*: module/subsystem identifier.
- `run_id` *(string, optional)*: additional run correlation (if different from `trace_id`).
- `data` *(object, optional)*: event-specific payload, **sanitized** (see “No secrets”).
- `meta` *(object, required)*: operational metadata (pid/host/monotonic clock) to assist ordering/debugging.

## Event types

### `startup`

Use for process/service start, or construction of key components.

Recommended `data`:
- `service` *(string)*: service name (e.g. `execution-engine`)
- `version` *(string)*: git sha or build version (if available)
- `config` *(object)*: safe non-secret configuration flags (booleans/thresholds)

Example (single line):

```json
{"replay_schema":"agenttrader.replay.v1","ts":"2026-01-06T01:02:03+00:00","event":"startup","trace_id":"...","agent_name":"execution-engine","component":"backend.execution.engine","data":{"dry_run":true},"meta":{"pid":123,"host":"pod-abc","mono_ms":123456}}
```

### `state_transition`

Use when the agent transitions between lifecycle states (e.g., `risk_pending → rejected`).

Recommended `data`:
- `from_state` *(string, required)*
- `to_state` *(string, required)*
- `reason` *(string, optional)*
- any safe identifiers relevant to the transition (e.g., `symbol`, `strategy_id`)

### `decision_checkpoint`

Use at “decision boundaries” where you’d want to later answer “why did it do that?”.

Recommended `data`:
- `checkpoint` *(string, required)*: short name (e.g., `risk`, `smart_routing`)
- `inputs_summary` *(object, optional)*: safe, minimal inputs
- `outputs_summary` *(object, optional)*: safe, minimal outputs
- `reason` *(string, optional)*

### `order_intent`

Use for **intent** lifecycle (received/validated/accepted/placed), even if no broker placement happens.

Recommended `data`:
- `stage` *(string, required)*: e.g. `received`, `dry_run`, `broker_placed`
- `intent` *(object, optional)*: safe representation (symbol/side/qty/type/ids)

## No secrets policy (redaction)

Replay events must not contain secrets. The current implementation:
- **redacts** keys containing fragments like `secret`, `token`, `password`, `authorization`, `api_key`, `cookie`, etc.
- **truncates** very large strings/containers to avoid accidental dumps of long payloads.

## Tooling

See `scripts/replay_from_logs.py` to generate a grouped markdown timeline from log files or stdin.

### Usage

- **From a saved `kubectl logs` dump**:

```bash
python3 scripts/replay_from_logs.py /path/to/kubectl-logs.txt -o replay.md
```

- **Directly from `kubectl logs`**:

```bash
kubectl logs deploy/execution-engine -n agenttrader --since=24h | python3 scripts/replay_from_logs.py -o replay.md
```

- **Include verbose raw JSON (per group)**:

```bash
python3 scripts/replay_from_logs.py /path/to/logs.txt --verbose -o replay.md
```

- **Also parse microVM protocol order intents (`protocol=v1`)**:

```bash
python3 scripts/replay_from_logs.py /path/to/logs.txt --include-protocol-intents -o replay.md
```

