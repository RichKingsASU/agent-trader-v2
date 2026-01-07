# Marketdata health contract (heartbeat)

Strategies **must refuse to run** if live marketdata is stale.

This repo implements the contract via a simple HTTP heartbeat:

- **Producer (marketdata service)**: exposes `GET /healthz` with `last_tick_epoch_seconds`
- **Consumers (strategy-engine + execution runtime)**: fetch `/healthz` and enforce a max age
- **Fail-safe**: any error fetching health (DNS, timeout, non-200, invalid JSON, missing tick) is treated as **stale** and execution is refused.

## Configuration

Shared env vars:

- **`MARKETDATA_HEALTH_URL`**: URL to the marketdata heartbeat endpoint.
  - Default: `http://127.0.0.1:8080/healthz`
- **`MARKETDATA_MAX_AGE_SECONDS`**: maximum allowed age of the heartbeat.
  - Default: `60`
- **`MARKETDATA_HEALTH_TIMEOUT_SECONDS`**: HTTP timeout for the consumer check.
  - Default: `2`

Marketdata-only test env var:

- **`MARKETDATA_FORCE_STALE`**: if true, `GET /healthz` returns 503 to simulate stale marketdata.

## Heartbeat endpoint

`GET /healthz` returns JSON like:

```json
{
  "service": "marketdata-mcp-server",
  "last_tick_epoch_seconds": 1730000000,
  "age_seconds": 1.2,
  "max_age_seconds": 60,
  "ok": true,
  "forced_stale": false
}
```

It returns:

- **200** when `ok=true`
- **503** when `ok=false` (stale / no tick / forced stale)

## How to test (simulate stale)

### 1) Force staleness on marketdata

Set on the marketdata service:

- `MARKETDATA_FORCE_STALE=true`

Then verify:

```bash
curl -i "$MARKETDATA_HEALTH_URL"
```

You should see **HTTP 503**.

### 2) Verify strategy-engine refuses to run

Run the strategy engine with a tight threshold:

```bash
export MARKETDATA_HEALTH_URL="http://127.0.0.1:8080/healthz"
export MARKETDATA_MAX_AGE_SECONDS=1
python -m backend.strategy_engine.driver
```

If marketdata is stale/unreachable, the process exits with a non-zero code and logs:

`[strategy_engine] Refusing to run: marketdata_stale ...`

### 3) Verify execution runtime refuses to execute

Call the execution service `/execute` while marketdata is stale.

Expected behavior:

- HTTP **503** with `detail="marketdata_stale"`

