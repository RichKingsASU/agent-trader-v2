# Feature Flags (Production)

AgentTrader’s production deployment is currently **Alpaca-only**. Any prior multi-broker flags and references have been removed during production hardening to avoid dead/unused code paths.

## Configuration file

For local development, environment variables are typically set in `.env.local` (not tracked by Git). For Cloud Run Jobs, environment variables come from `agenttrader/scripts/env.yaml` plus Secret Manager mappings.

## Current flags

| Flag            | Description                                                                 | Values | Default |
| :-------------- | :-------------------------------------------------------------------------- | :----- | :------ |
| `ENABLE_ALPACA` | Enables Alpaca-dependent ingestion/execution paths where the flag is used. | `0`,`1` | `1`     |

If you introduce additional broker integrations in the future, add new flags at that time and document them here.
