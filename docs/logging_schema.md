# Structured Logging Schema (JSON)

This document defines a **structured JSON logging schema** designed for **Google Cloud Logging**. It standardizes core fields (correlation, classification, ownership, and severity) and provides a **field-to-Cloud-Logging mapping** so logs are queryable, traceable, and compatible with best practices.

## Goals

- **Consistent**: all services emit the same core fields.
- **Queryable**: key dimensions are first-class and stable.
- **Correlatable**: logs join to traces, spans, and events.
- **Compatible**: maps cleanly to Cloud Logging `LogEntry` conventions.

## Envelope and format

- Each log entry is a single **JSON object**.
- Timestamp should be emitted using an RFC3339/ISO-8601 string (or rely on platform ingestion timestamps).
- In Cloud Logging, these objects are typically stored under `jsonPayload` (unless your logger writes to `textPayload`).

## Required fields

These fields MUST be present in every log entry:

- `traceId`
- `eventId`
- `eventType`
- `service`
- `version`
- `severity`

### Required field definitions

| Field | Type | Constraints | Purpose |
|---|---|---|---|
| `traceId` | string | Hex string; prefer 32 lowercase hex chars (Trace ID). If unknown, emit empty string and set `trace.sampled=false`. | Correlate logs to distributed traces. |
| `eventId` | string | UUIDv4 or ULID (stable, unique per event). | De-duplicate and reference a specific event. |
| `eventType` | string | Stable taxonomy (e.g., `trade.order_submitted`, `risk.limit_breached`). | Classify event semantics for querying/alerts. |
| `service` | string | Short service identifier (e.g., `execution-engine`). | Identify producing service. |
| `version` | string | Build/version identifier (e.g., semver `1.8.3`, git SHA). | Identify software version emitting the log. |
| `severity` | string | One of: `DEBUG`, `INFO`, `NOTICE`, `WARNING`, `ERROR`, `CRITICAL`, `ALERT`, `EMERGENCY`. | Log severity aligned to Cloud Logging. |

## Recommended fields (strongly suggested)

These fields improve operations and should be included whenever available:

### Correlation / context

| Field | Type | Notes |
|---|---|---|
| `timestamp` | string | RFC3339, e.g. `2026-01-08T17:20:34.123Z`. |
| `spanId` | string | 16-hex span ID when available. |
| `parentEventId` | string | Links causal chains for event-sourcing style flows. |
| `operationId` | string | Correlate multi-step workflows (e.g., `rebalance-20260108-001`). |
| `requestId` | string | Request-scoped ID (API gateway / load balancer / app). |
| `sessionId` | string | User session correlation (if applicable). |

### Identity / tenancy

| Field | Type | Notes |
|---|---|---|
| `tenantId` | string | Multi-tenant boundary key. |
| `userId` | string | Stable user identifier (avoid email in logs). |
| `actor` | object | Optional structured actor metadata (service account, user, system). |

### Diagnostics

| Field | Type | Notes |
|---|---|---|
| `message` | string | Human-readable summary. Keep short and stable. |
| `error` | object | Structured error details (see below). |
| `labels` | object | Small key/value dimensions (strings) for filtering. |
| `sourceLocation` | object | File/line/function for language runtimes that support it. |

### Performance / HTTP / RPC (when relevant)

| Field | Type | Notes |
|---|---|---|
| `durationMs` | number | Latency for the unit of work. |
| `httpRequest` | object | Use Cloud Logging-compatible keys (see mapping). |
| `rpc` | object | gRPC/service-to-service details if applicable. |

### Domain payload

| Field | Type | Notes |
|---|---|---|
| `data` | object | Domain-specific payload for the event. Keep bounded; prefer IDs over full objects. |

## Error object (recommended shape)

When `severity` is `ERROR` or higher, include an `error` object:

| Field | Type | Notes |
|---|---|---|
| `error.type` | string | Exception class or error type identifier. |
| `error.message` | string | Short error message (safe for logs). |
| `error.stack` | string | Stack trace (multi-line allowed). |
| `error.code` | string \| number | Application or upstream error code. |
| `error.cause` | object | Optional nested error cause. |

## JSON Schema (contract)

This is a **draft-07 JSON Schema** representing the log shape. Services may add additional fields, but SHOULD avoid changing meanings of existing keys.

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "StructuredLogEntry",
  "type": "object",
  "additionalProperties": true,
  "required": ["traceId", "eventId", "eventType", "service", "version", "severity"],
  "properties": {
    "timestamp": { "type": "string", "format": "date-time" },

    "traceId": { "type": "string", "minLength": 1 },
    "spanId": { "type": "string" },
    "trace": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "sampled": { "type": "boolean" }
      }
    },

    "eventId": { "type": "string", "minLength": 1 },
    "parentEventId": { "type": "string" },
    "eventType": { "type": "string", "minLength": 1 },

    "service": { "type": "string", "minLength": 1 },
    "version": { "type": "string", "minLength": 1 },
    "environment": { "type": "string" },
    "region": { "type": "string" },

    "severity": {
      "type": "string",
      "enum": ["DEBUG", "INFO", "NOTICE", "WARNING", "ERROR", "CRITICAL", "ALERT", "EMERGENCY"]
    },

    "message": { "type": "string" },

    "operationId": { "type": "string" },
    "requestId": { "type": "string" },
    "sessionId": { "type": "string" },

    "tenantId": { "type": "string" },
    "userId": { "type": "string" },
    "actor": { "type": "object", "additionalProperties": true },

    "labels": {
      "type": "object",
      "additionalProperties": { "type": "string" }
    },

    "durationMs": { "type": "number", "minimum": 0 },

    "httpRequest": {
      "type": "object",
      "additionalProperties": true,
      "properties": {
        "requestMethod": { "type": "string" },
        "requestUrl": { "type": "string" },
        "status": { "type": "integer" },
        "responseSize": { "type": "string" },
        "userAgent": { "type": "string" },
        "remoteIp": { "type": "string" },
        "referer": { "type": "string" },
        "latency": { "type": "string" },
        "protocol": { "type": "string" }
      }
    },

    "sourceLocation": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "file": { "type": "string" },
        "line": { "type": "integer" },
        "function": { "type": "string" }
      }
    },

    "error": {
      "type": "object",
      "additionalProperties": true,
      "properties": {
        "type": { "type": "string" },
        "message": { "type": "string" },
        "stack": { "type": "string" },
        "code": {}
      }
    },

    "data": { "type": "object", "additionalProperties": true }
  }
}
```

## Cloud Logging mapping (best practices)

Google Cloud Logging stores entries as a `LogEntry` with top-level fields like `severity`, `trace`, `spanId`, `httpRequest`, plus a payload (`jsonPayload`).

### Direct mappings (preferred)

| Our field | Cloud Logging target | Notes |
|---|---|---|
| `severity` | `severity` | Use Cloud Logging’s canonical severities. |
| `timestamp` | `timestamp` | Optional; ingestion timestamp is used if omitted. |
| `httpRequest` | `httpRequest` | Use Cloud Logging `httpRequest` object keys. |
| `sourceLocation` | `sourceLocation` | Enables source-aware error views. |
| `traceId` | `trace` | In Cloud Logging, `trace` expects a full resource name: `projects/PROJECT_ID/traces/TRACE_ID`. If you only log a bare `traceId`, keep it in payload and (where possible) also populate `trace`. |
| `spanId` | `spanId` | Cloud Logging supports `spanId` alongside `trace`. |
| `labels` | `labels` | Cloud Logging labels are indexed dimensions; keep cardinality bounded. |

### Payload fields (stored under `jsonPayload`)

| Our field | Cloud Logging location | Notes |
|---|---|---|
| `eventId` | `jsonPayload.eventId` | Stable event identity (query + de-dupe). |
| `eventType` | `jsonPayload.eventType` | Primary semantic classifier; use for alert routing. |
| `service` | `jsonPayload.service` | Often redundant with resource labels, but valuable cross-platform. |
| `version` | `jsonPayload.version` | Useful for release correlation. |
| `message` | `jsonPayload.message` | Keep concise; avoid embedding huge JSON strings. |
| `data` | `jsonPayload.data` | Domain payload; keep size bounded. |

### Resource & environment (strongly recommended)

Cloud Logging also uses `resource.type` and `resource.labels.*` (e.g., Cloud Run service name, revision, instance ID). Prefer letting the platform set these automatically; do not duplicate high-cardinality resource labels in `labels`.

## Taxonomy guidance (`eventType`)

Use a stable dotted namespace:

- `domain.action` (simple): `orders.submitted`
- `domain.subdomain.action` (preferred at scale): `trade.orders.submitted`
- Use past tense for completion events (`submitted`, `filled`, `failed`) and imperative for intent (`submit_requested`) if you distinguish them.

## Cardinality & privacy rules

- **Avoid high-cardinality labels**: do not put order IDs, trace IDs, user IDs into `labels`. Keep those in `jsonPayload`.
- **No secrets**: never log API keys, OAuth tokens, private keys, or raw credentials.
- **Minimize PII**: prefer `userId` over email/phone; if you must log PII, hash/tokenize and document retention.

## Example log lines

### 1) Normal event (INFO)

```json
{
  "timestamp": "2026-01-08T17:20:34.123Z",
  "severity": "INFO",
  "service": "execution-engine",
  "version": "1.14.2",
  "environment": "prod",
  "region": "us-central1",
  "traceId": "4bf92f3577b34da6a3ce929d0e0e4736",
  "spanId": "00f067aa0ba902b7",
  "eventId": "01HKB1Q8WQ1J9GZ8A8ZKQ2X7C3",
  "eventType": "trade.order_submitted",
  "message": "Order submitted to broker",
  "operationId": "rebalance-20260108-001",
  "requestId": "req-2f1f8d0a0e8b",
  "tenantId": "tnt_9c3f2d",
  "labels": {
    "component": "orders",
    "assetClass": "equities"
  },
  "data": {
    "broker": "alpaca",
    "symbol": "AAPL",
    "side": "buy",
    "qty": 10,
    "orderType": "market"
  }
}
```

### 2) Warning (business/risk signal)

```json
{
  "timestamp": "2026-01-08T17:21:10.447Z",
  "severity": "WARNING",
  "service": "risk-engine",
  "version": "3.2.0",
  "environment": "prod",
  "traceId": "4bf92f3577b34da6a3ce929d0e0e4736",
  "eventId": "b8d1f55c-6d70-4d9c-9ee9-1bdbb4e9d7f5",
  "eventType": "risk.limit_breached",
  "message": "Max position size exceeded",
  "labels": {
    "limitType": "position_size",
    "scope": "account"
  },
  "data": {
    "symbol": "TSLA",
    "attemptedNotionalUsd": 125000,
    "maxNotionalUsd": 100000
  }
}
```

### 3) Error with stack trace (ERROR)

```json
{
  "timestamp": "2026-01-08T17:22:03.001Z",
  "severity": "ERROR",
  "service": "market-ingest",
  "version": "0.9.7",
  "environment": "prod",
  "traceId": "0af7651916cd43dd8448eb211c80319c",
  "eventId": "01HKB1S7MZ1YNTK3KJZQ5E5W1Q",
  "eventType": "marketdata.ingest_failed",
  "message": "Failed to decode provider payload",
  "labels": {
    "provider": "polygon",
    "topic": "quotes"
  },
  "error": {
    "type": "DecodeError",
    "message": "Unexpected field 'px'",
    "stack": "Traceback (most recent call last):\n  File \"ingest.py\", line 88, in handle\n    ...\nDecodeError: Unexpected field 'px'"
  },
  "data": {
    "symbol": "NVDA",
    "payloadSizeBytes": 8421
  }
}
```

### 4) HTTP request log (INFO) using Cloud Logging `httpRequest`

```json
{
  "timestamp": "2026-01-08T17:23:44.892Z",
  "severity": "INFO",
  "service": "ops-dashboard",
  "version": "2.0.1",
  "environment": "prod",
  "traceId": "3f9e0b2b8c7f4a6e9c1d2e3f4a5b6c7d",
  "eventId": "b0dbf8c2-6c7c-4b06-98e7-3a9c3e0f8a21",
  "eventType": "http.request_completed",
  "message": "Request completed",
  "durationMs": 37.4,
  "httpRequest": {
    "requestMethod": "GET",
    "requestUrl": "/api/v1/health",
    "status": 200,
    "userAgent": "GoogleHC/1.0",
    "remoteIp": "35.191.0.1",
    "latency": "0.037400s",
    "protocol": "HTTP/1.1"
  }
}
```
