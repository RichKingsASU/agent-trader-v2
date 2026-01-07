# Execution Agent (Hard-Gated, Paper-Only Stub)

This directory contains the **execution-agent** skeleton for AgentTrader v2.

## What it does

- Reads **OrderProposals** from an **NDJSON** file (`PROPOSALS_PATH`) in follow mode
- Applies safety + preflight decision rules
- Emits **ExecutionDecision** audit records as NDJSON
- **Never calls broker APIs**
- **Never places orders** (paper or real)

## Hard startup gate (must pass or the process exits non-zero)

The agent refuses to start unless **all** are true (strict, case-sensitive):

- `REPO_ID == "agent-trader-v2"`
- `AGENT_NAME == "execution-agent"`
- `AGENT_ROLE == "execution"`
- `AGENT_MODE == "EXECUTE"`
- `EXECUTION_AGENT_ENABLED == "true"`
- `BROKER_EXECUTION_ENABLED == "false"` (**must be present and must be false**)

## Proposal input (NDJSON)

Each line should be a JSON object. Minimal supported fields:

- `proposal_id` (string; required for clean dedupe)
- `valid_until_utc` (ISO-8601; missing/unparseable => REJECT)
- `requires_human_approval` (missing defaults to `true` => REJECT)
- `order` (object; optional, used for `recommended_order` summary)

## Marketdata freshness input (stub)

This agent does **not** fetch market data. It uses:

- `MARKETDATA_LAST_TS_UTC`: ISO-8601 timestamp
- `MARKETDATA_STALE_THRESHOLD_S`: default `120`

If missing/stale => `marketdata_fresh=false` => REJECT.

## Decision output

Writes decisions to:

`audit_artifacts/execution_decisions/<YYYY-MM-DD>/decisions.ndjson`

If the filesystem is not writable, the agent emits full decision JSON objects to stdout
with `intent_type="decision_output_fallback_stdout"`.

