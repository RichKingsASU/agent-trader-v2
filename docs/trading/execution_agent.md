## Execution Agent (Execution Pathway Skeleton — No Orders)

### Purpose

The **execution-agent** is the future institutional execution pathway for AgentTrader v2.
In this phase it is **paper-only and hard-gated**:

- It consumes **OrderProposals**
- It performs a deterministic safety + preflight decision
- It produces **ExecutionDecision** audit records (**APPROVE**/**REJECT**)
- It **does not place orders** and **does not call broker APIs**

### Hard gating conditions (refuses to start unless all are true)

Startup is strict and case-sensitive:

- `REPO_ID == "agent-trader-v2"`
- `AGENT_NAME == "execution-agent"`
- `AGENT_ROLE == "execution"`
- `AGENT_MODE == "EXECUTE"`
- `EXECUTION_AGENT_ENABLED == "true"`
- `BROKER_EXECUTION_ENABLED == "false"` (must be present and must be false)

If any condition fails, the process exits non-zero and emits a structured JSON log with `reason_codes`.

### Proposal ingestion (NDJSON file follow mode)

Preferred mode for now:

- Set `PROPOSALS_PATH=/path/to/proposals.ndjson`
- The agent follows the file (tail-style) and processes each line once per runtime.
- Dedupe is in-memory; to make restarts auditable the agent also seeds a set of proposal IDs from **today’s** existing decision artifact and logs `duplicate_seen=true` when applicable.

### Decision logic (safe stub)

Deterministic rules (REJECT-by-default posture):

- If kill switch is enabled → **REJECT**
- If marketdata is stale/missing → **REJECT**
- If `requires_human_approval` is true (defaults to true if missing) → **REJECT**
- If `valid_until_utc` is expired (or missing/unparseable) → **REJECT**
- Else → **APPROVE** (still **no execution**)

Every decision emits a JSON intent log with `intent_type="execution_decision"`.

### Where decisions are written

Decisions are written as NDJSON to:

`audit_artifacts/execution_decisions/<YYYY-MM-DD>/decisions.ndjson`

If the filesystem is not writable, the agent emits full decision JSON objects to stdout.

### Run locally against a sample proposals file

Create a sample proposals file:

```bash
mkdir -p /tmp/exec_agent && cat > /tmp/exec_agent/proposals.ndjson <<'EOF'
{"proposal_id":"p-1","valid_until_utc":"2099-01-01T00:00:00Z","requires_human_approval":true,"order":{"symbol":"SPY","side":"buy","qty":1}}
EOF
```

Run the agent (still safe: will only emit decisions):

```bash
export REPO_ID="agent-trader-v2"
export AGENT_NAME="execution-agent"
export AGENT_ROLE="execution"
export AGENT_MODE="EXECUTE"
export EXECUTION_AGENT_ENABLED="true"
export BROKER_EXECUTION_ENABLED="false"
export PROPOSALS_PATH="/tmp/exec_agent/proposals.ndjson"
export MARKETDATA_LAST_TS_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
python -m backend.execution_agent.main
```

Append another proposal line to see follow mode:

```bash
echo '{"proposal_id":"p-2","valid_until_utc":"2099-01-01T00:00:00Z","requires_human_approval":true,"order":{"symbol":"AAPL","side":"sell","qty":1}}' >> /tmp/exec_agent/proposals.ndjson
```

### Kubernetes deployment (scaled to 0; safe defaults)

The manifest sets:

- `replicas: 0`
- `AGENT_MODE=OFF`
- `EXECUTION_AGENT_ENABLED="false"`
- `BROKER_EXECUTION_ENABLED="false"`

So it won’t start even if scaled up accidentally.

### Verifying decisions

- Check container logs for `intent_type="execution_decision"`
- Check `audit_artifacts/execution_decisions/<date>/decisions.ndjson` for persisted decisions

