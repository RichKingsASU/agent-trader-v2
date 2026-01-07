# Agent identity + intent logging

All agent runtimes should emit **one JSON log line at process startup** via:

- `backend.common.agent_boot.configure_startup_logging(agent_name, intent)`

## Required fields

- **`ts`**: RFC3339/ISO8601 UTC timestamp for the startup log line
- **`agent_name`**: stable agent/service identifier (e.g. `execution-engine`)
- **`intent`**: one-sentence description of what this process is doing
- **`git_sha`**: git commit SHA (set via `GIT_SHA` env var; falls back to common CI vars)
- **`agent_mode`**: `dry_run` / `live` / `unknown` (or explicitly set via `AGENT_MODE`)
- **`environment`**: deployment environment (e.g. `prod`, `staging`, `dev`)

## Optional fields (included when available)

- **`service`**: Cloud Run service name (`K_SERVICE`) or explicit `SERVICE`
- **`workload`**: Kubernetes workload/pod name, or explicit `WORKLOAD`

## Example startup log line

```json
{"ts":"2026-01-06T12:34:56.789012+00:00","agent_name":"execution-engine","intent":"Serve the execution API; validate config and execute broker order intents.","git_sha":"a2466ec","agent_mode":"dry_run","environment":"prod","service":"execution-engine","workload":"execution-engine-7f7b6c7b6d-abcde"}
```

