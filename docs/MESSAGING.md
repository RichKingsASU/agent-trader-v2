# Messaging (NATS) Standard

This document defines the **canonical NATS subjects** and **JSON message schemas** used for internal service-to-service communication.

## Goals

- **Consistency**: every service publishes/subscribes using the same subject taxonomy.
- **Multi-tenancy**: every message is scoped by `tenant_id`.
- **Traceability**: every message is schema-validated and versioned.

## Subject conventions

### Format

- Subjects are **dot-delimited tokens**: `<domain>.<tenant_id>.<...>`
- Tokens MUST NOT include:
  - `.` (dot) — reserved token delimiter
  - `*` or `>` — wildcards are for subscriptions only
- Prefer stable identifiers and avoid high-cardinality tokens except where required (e.g., `symbol`, `account_id`).
- `tenant_id` is REQUIRED for all internal subjects.
- `symbol` is REQUIRED for all market + signal streams.

### Canonical subjects

These are the only approved subject shapes:

- **Market events**: `market.<tenant_id>.<symbol>`
- **Strategy signals**: `signals.<tenant_id>.<strategy_id>.<symbol>`
- **Order requests**: `orders.<tenant_id>.<account_id>`
- **Fills / executions**: `fills.<tenant_id>.<account_id>`
- **Ops / service events**: `ops.<tenant_id>.<service>`

### Wildcard subscriptions (examples)

- **All market events for a tenant**: `market.<tenant_id>.>`
- **All signals for a tenant/strategy**: `signals.<tenant_id>.<strategy_id>.>`
- **All order requests for an account**: `orders.<tenant_id>.<account_id>`
- **All fills for an account**: `fills.<tenant_id>.<account_id>`
- **All ops events for a tenant**: `ops.<tenant_id>.>`

## Message schema rules (JSON + versioning)

### Required envelope fields

Every message MUST include:

- `schema`: a stable schema name (e.g., `"market"`, `"order_request"`)
- `schema_version`: a **semantic** version string `"MAJOR.MINOR"` (e.g., `"1.0"`)
- `tenant_id`: tenant scope for routing/audit
- `ts`: ISO-8601 timestamp in UTC

Additional fields depend on the message type (see shared Pydantic models under `backend/common/schemas/`).

### Versioning policy

- **MAJOR**: breaking changes (field removed/renamed, meaning changes, type changes)
  - Publish on a **new MAJOR** and coordinate consumer migration.
- **MINOR**: backwards-compatible changes (new optional fields, relaxed constraints)
  - Consumers SHOULD tolerate unknown fields.
- Producers MUST set the correct `schema_version`.
- Consumers MUST validate incoming JSON against the expected schema and reject/dead-letter invalid messages.

## Examples

### Market event

- **Subject**: `market.acme.AAPL`
- **Payload (example)**:

```json
{
  "schema": "market",
  "schema_version": "1.0",
  "tenant_id": "acme",
  "symbol": "AAPL",
  "ts": "2025-12-29T12:00:00+00:00",
  "source": "alpaca-quotes",
  "data": {
    "bid": 150.2,
    "ask": 150.3,
    "price": 150.25
  }
}
```

### Signal event

- **Subject**: `signals.acme.delta_momentum.AAPL`
- **Payload (example)**:

```json
{
  "schema": "signal",
  "schema_version": "1.0",
  "tenant_id": "acme",
  "strategy_id": "delta_momentum",
  "symbol": "AAPL",
  "ts": "2025-12-29T12:00:01+00:00",
  "signal_type": "enter_long",
  "confidence": 0.82,
  "data": {
    "reason": "delta > threshold"
  }
}
```

### Order request

- **Subject**: `orders.acme.paper-account-1`
- **Payload (example)**:

```json
{
  "schema": "order_request",
  "schema_version": "1.0",
  "tenant_id": "acme",
  "account_id": "paper-account-1",
  "strategy_id": "delta_momentum",
  "user_id": "2385984e-0ae9-47f1-a82e-3c17e0dad510",
  "symbol": "AAPL",
  "ts": "2025-12-29T12:00:02+00:00",
  "side": "buy",
  "order_type": "market",
  "time_in_force": "day",
  "notional": 200.0,
  "quantity": 1,
  "raw_order": {
    "symbol": "AAPL",
    "side": "buy"
  },
  "meta": {
    "service_id": "delta-momentum-bot"
  }
}
```

