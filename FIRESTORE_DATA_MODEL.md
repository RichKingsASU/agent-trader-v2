# Firestore data model for live market data

This document defines a **Firestore-only** schema optimized for **live market quote streaming**:

- **Small documents** (avoid unbounded arrays / growth)
- **Low write amplification** (coalesce/throttle “latest” writes)
- **Predictable query/indexing** (simple lookups + optional bounded history)

The canonical collections/docs requested are:

- `live_quotes/{symbol}`
- `ops/market_ingest`
- `trades/{id}` (optional)

> Note on existing code in this repo: some ingestion code writes “latest” quotes to a configurable collection (default `market_latest`). This doc standardizes on **`live_quotes`** as the canonical path for UI + ops tooling. If you keep `market_latest`, treat it as an alias and ensure the **same field names** exist in both.

---

## `live_quotes/{symbol}` (latest snapshot per symbol)

### Purpose
One small document per symbol representing the **latest known quote snapshot**. This is the primary UI subscription surface.

### Document ID
- `{symbol}`: e.g. `SPY`, `AAPL`

### Schema (recommended)
- **`symbol`**: `string` (redundant but convenient; should match doc id)
- **`bid`**: `number|null`
- **`ask`**: `number|null`
- **`bid_size`**: `number|null` (optional)
- **`ask_size`**: `number|null` (optional)
- **`price`**: `number|null` (optional “mid” or last trade, depending on source)
- **`last_update_ts`**: `timestamp` (**required**; server write time or “received time”)
- **`source_event_ts`**: `timestamp|null` (optional; upstream event timestamp if available)
- **`source`**: `string` (e.g. `alpaca`)
- **`ingest_instance`**: `string|null` (optional; helps debugging)
- **`seq`**: `number` (optional monotonic counter per symbol for debugging; avoid if not needed)

### Example document

```json
{
  "symbol": "SPY",
  "bid": 496.12,
  "ask": 496.14,
  "bid_size": 800,
  "ask_size": 600,
  "price": 496.13,
  "last_update_ts": "2025-12-29T16:04:12.531Z (Firestore Timestamp)",
  "source_event_ts": "2025-12-29T16:04:12.500Z (Firestore Timestamp)",
  "source": "alpaca",
  "ingest_instance": "ingest-us-central1-01"
}
```

### Write pattern (latest snapshot)
**Goal**: one “hot” doc per symbol, updated at a controlled cadence.

- **Coalesce** quote ticks in memory and write only the latest snapshot.
- **Throttle per symbol** to avoid hot-document contention:
  - Recommended: **≤ 1 write/second/symbol** to `live_quotes/{symbol}`.
  - If your upstream emits many updates/second, sample/throttle the “latest” doc and optionally store bounded history separately (see below).
- Prefer `set(..., merge=true)` so writers can add fields safely over time.
- Prefer storing `last_update_ts` as a **Firestore `timestamp`** for efficient `orderBy` / range queries.

### Optional bounded history (subcollection)

If you need short-term charting/debugging, keep **rolling history in a subcollection** with TTL expiration.

#### Recommended path
- `live_quotes/{symbol}/recent/{bucket_id}`

#### Bucket strategy (minimize write amplification)
Store **one doc per time bucket** (e.g. 1s or 5s) instead of per tick:

- `{bucket_id}`: e.g. `2025-12-29T16:04:12Z` (rounded to bucket)
- Write at most **1 write per bucket** (use merge/overwrite).

#### Schema (history doc)
- **`bucket_ts`**: `timestamp` (start of bucket)
- **`bid`**, **`ask`**, **`price`**: `number|null`
- **`source_event_ts`**: `timestamp|null`
- **`last_update_ts`**: `timestamp` (writer time)
- **`expires_at`**: `timestamp` (**required** for TTL)

#### TTL / retention
- Enable Firestore **TTL** on `expires_at`.
- Recommended retention for “recent” quotes: **5–30 minutes** (pick based on UI needs).

#### Example history doc

```json
{
  "bucket_ts": "2025-12-29T16:04:12.000Z (Firestore Timestamp)",
  "bid": 496.12,
  "ask": 496.14,
  "price": 496.13,
  "source_event_ts": "2025-12-29T16:04:12.500Z (Firestore Timestamp)",
  "last_update_ts": "2025-12-29T16:04:12.531Z (Firestore Timestamp)",
  "expires_at": "2025-12-29T16:34:12.000Z (Firestore Timestamp)"
}
```

---

## `ops/market_ingest` (ingestion heartbeat + health)

### Purpose
A single operational “heartbeat” document used for **LIVEness/STALE** indicators and basic debugging.

### Document path
- Collection: `ops`
- Document: `market_ingest`

### Schema (recommended)
- **`last_heartbeat_at`**: `timestamp` (**required**)
- **`status`**: `string` (e.g. `running`, `degraded`, `stopped`)
- **`last_symbol`**: `string|null` (optional)
- **`dry_run`**: `boolean` (optional)
- **`ingest_instance`**: `string|null` (optional)
- **`counters`**: `map` (optional; keep small)
  - Example: `{"quotes_seen": 123456, "writes_ok": 120000, "writes_err": 12}`
- **`build`**: `map` (optional; keep small)
  - Example: `{"git_sha": "...", "version": "..." }`

### Example document

```json
{
  "last_heartbeat_at": "2025-12-29T16:04:15.000Z (Firestore Timestamp)",
  "status": "running",
  "last_symbol": "SPY",
  "dry_run": false,
  "ingest_instance": "ingest-us-central1-01",
  "counters": { "quotes_seen": 892341, "writes_ok": 12033, "writes_err": 0 }
}
```

### Write frequency guidance
- Recommended heartbeat cadence: **every 10–30 seconds**.
- Avoid writing much more frequently than that; this is a single “hot” document.

---

## `trades/{id}` (optional)

### Purpose
Optional storage for trade/order events (paper trades, executions, or strategy actions).

If trades become high-volume, prefer a model that avoids a single “hot” doc and avoids unbounded arrays (i.e. **one trade per document**, and **fills as subcollection** if needed).

### Document ID
- `{id}`: UUID/ULID or a stable hash of `(broker, account_id, client_order_id, event_ts)` depending on your idempotency needs.

### Schema (suggested minimal)
- **`created_at`**: `timestamp` (**required**)
- **`symbol`**: `string` (**required**)
- **`side`**: `string` (`buy`/`sell`)
- **`qty`**: `number`
- **`order_type`**: `string` (optional)
- **`limit_price`**: `number|null`
- **`status`**: `string` (e.g. `new`, `filled`, `canceled`)
- **`broker`**: `string` (optional)
- **`strategy_id`**: `string|null` (optional)
- **`source`**: `string` (optional; service name)

### Example document

```json
{
  "created_at": "2025-12-29T16:05:00.000Z (Firestore Timestamp)",
  "symbol": "AAPL",
  "side": "buy",
  "qty": 10,
  "order_type": "market",
  "limit_price": null,
  "status": "filled",
  "broker": "alpaca",
  "strategy_id": "delta_momentum_v1",
  "source": "strategy_engine"
}
```

### Optional fills subcollection
- `trades/{id}/fills/{fill_id}` with:
  - `fill_ts` (timestamp), `qty`, `price`, `venue`, etc.
  - TTL only if you truly don’t need long-term history.

---

## `userSettings/{uid}/allocation/{symbol}` (portfolio target allocations)

### Purpose
Stores user-defined target portfolio allocations for rebalancing. Each document represents the target percentage allocation for a specific ticker.

### Document ID
- `{symbol}`: e.g. `SPY`, `AAPL`, `TSLA`

### Schema (required fields)
- **`symbol`**: `string` (ticker symbol)
- **`target_percent`**: `number` (target allocation as percentage, e.g., 40 for 40%)
- **`created_at`**: `timestamp` (when allocation was set)
- **`updated_at`**: `timestamp` (last modification)
- **`enabled`**: `boolean` (whether this allocation is active)

### Example document

```json
{
  "symbol": "SPY",
  "target_percent": 40.0,
  "created_at": "2025-12-30T10:00:00.000Z (Firestore Timestamp)",
  "updated_at": "2025-12-30T10:00:00.000Z (Firestore Timestamp)",
  "enabled": true
}
```

### Notes
- Total target_percent across all enabled allocations should sum to 100%
- The rebalancing function checks drift from these targets
- 5% drift threshold triggers automatic rebalancing

---

## `tenants/{tid}/ledger_trades/{trade_id}` (immutable, append-only)

### Purpose
An **immutable, append-only trade ledger** (one document per fill) used for **P&L attribution** and auditability.

### Document ID
- `{trade_id}`: UUID/ULID or deterministic hash for idempotent ingestion.

### Schema (required fields)
- **`uid`**: `string` (actor/user id; `"system"` for server-side fills if needed)
- **`strategy_id`**: `string`
- **`run_id`**: `string` (strategy run/session identifier)
- **`symbol`**: `string`
- **`side`**: `string` (`buy`/`sell`)
- **`qty`**: `number` (positive)
- **`price`**: `number` (positive)
- **`ts`**: `timestamp` (fill timestamp)
- **`fees`**: `number` (positive USD cost; can be `0`)

### Notes (immutability)
- Security rules allow **create + read**, and deny **update/delete** for clients.
- Backend ingestion should use Firestore `create()` to ensure the doc can’t be overwritten.

---

## Indexing needs (Firestore)

Firestore automatically maintains **single-field indexes** for most fields. You only need to create **composite indexes** when a query combines multiple fields (e.g. `where` on one field plus `orderBy` on another), or uses certain `in` + `orderBy` patterns.

### `live_quotes`
- **Direct doc reads / doc listeners** (`live_quotes/{symbol}`): no indexes needed.
- **Subscribe to entire collection** (no filters): no custom indexes needed (but can be expensive at scale; see cost notes).
- **Ops / freshness query patterns**:
  - `orderBy(last_update_ts desc).limit(1)`: uses the single-field index on `last_update_ts`.
  - `where(last_update_ts >= X)`: uses the single-field index on `last_update_ts`.
  - If you add `where(status == "running")` + `orderBy(last_update_ts desc)`: **composite index** on `(status, last_update_ts desc)` will be required.

### `live_quotes/{symbol}/recent`
- `orderBy(bucket_ts desc).limit(N)`: single-field index on `bucket_ts` (automatic).

### `trades`
Only create the composites you actually query:
- Common: `where(symbol == "SPY").orderBy(created_at desc).limit(50)`
  - Requires composite index on `(symbol, created_at desc)`.
- Common: `where(strategy_id == "...").orderBy(created_at desc)`
  - Requires composite index on `(strategy_id, created_at desc)`.

---

## Write frequency + scaling guidance

### Practical safe defaults
- **Latest snapshot** (`live_quotes/{symbol}`): **1 write/sec/symbol** (or less).
- **Heartbeat** (`ops/market_ingest`): **10–30 sec**.
- **History buckets** (`live_quotes/{symbol}/recent/{bucket}`): **1 write/bucket** (bucket = 1–5 sec).

### Why throttle “latest”
Firestore documents can become **hotspots** if written too frequently. Throttling “latest” also reduces:
- write costs
- index update work
- fan-out read costs for clients watching the doc/collection

---

## Cost notes (write-heavy streams)

### Writes are usually the smallest part; fan-out reads can dominate
If you have many clients subscribed, every update generates document-read events per client:

- **Best**: clients listen to **only the symbols they need** (doc listeners per symbol, or `where(documentId() in [...])` for small watchlists).
- **Avoid** at scale: listening to the entire `live_quotes` collection (every symbol update wakes every client).

### Keep docs small and stable
- Do not append to arrays in a “latest” doc (unbounded growth + larger index churn).
- Avoid embedding large nested blobs; store only what the UI needs for the “latest” view.
- For detailed tick data, prefer **bounded subcollections** with TTL.

### TTL helps you bound storage
For rolling history, set `expires_at` and enable Firestore TTL so old docs delete automatically without custom cleanup jobs.

---

## Multi-tenant user data

### `users/{userId}` (user root document)

#### Purpose
Stores user-specific metadata and configuration. This is the root document for all user-owned data.

#### Document ID
- `{userId}`: Firebase Auth UID

#### Schema (recommended)
- **`email`**: `string` (optional)
- **`created_at`**: `timestamp` (**required**)
- **`updated_at`**: `timestamp` (optional)
- **`displayName`**: `string|null` (optional)
- **`tenant_id`**: `string|null` (optional; for backward compatibility with tenant-based model)

#### Example document

```json
{
  "email": "user@example.com",
  "created_at": "2025-12-30T00:00:00.000Z (Firestore Timestamp)",
  "displayName": "John Doe"
}
```

---

### `users/{userId}/alpacaAccounts/{accountId}` (user-scoped Alpaca accounts)

#### Purpose
Stores Alpaca account snapshots for each user. Each user can have multiple broker accounts.

#### Document ID
- `{accountId}`: typically `"snapshot"` or `"primary"` for the main account, or UUID for additional accounts

#### Schema (required fields)
- **`broker`**: `string` (e.g. `"alpaca"`)
- **`external_account_id`**: `string|null` (Alpaca's account ID)
- **`status`**: `string` (e.g. `"ACTIVE"`)
- **`equity`**: `number`
- **`buying_power`**: `number`
- **`cash`**: `number`
- **`updated_at`**: `timestamp` (Firestore SERVER_TIMESTAMP)
- **`updated_at_iso`**: `string` (ISO 8601 timestamp)
- **`raw`**: `map` (optional; full Alpaca response for debugging)
- **`encrypted_key_path`**: `string|null` (optional; Secret Manager path for encrypted API keys)

#### Example document

```json
{
  "broker": "alpaca",
  "external_account_id": "abc123",
  "status": "ACTIVE",
  "equity": 10000.50,
  "buying_power": 8500.25,
  "cash": 5000.00,
  "updated_at": "2025-12-30T12:00:00.000Z (Firestore Timestamp)",
  "updated_at_iso": "2025-12-30T12:00:00Z",
  "encrypted_key_path": "projects/PROJECT_ID/secrets/alpaca-keys-USER_ID/versions/latest"
}
```

#### Notes
- API keys should be stored in Google Cloud Secret Manager, not in Firestore
- The `encrypted_key_path` field references the Secret Manager path
- Secret should contain JSON: `{"key_id": "...", "secret_key": "..."}`

---

### `users/{userId}/tradingSignals/{signalId}` (user-scoped trading signals)

#### Purpose
Stores trading signals generated for each user.

#### Document ID
- `{signalId}`: UUID/ULID or timestamp-based ID

#### Schema (required fields)
- **`created_at`**: `timestamp` (**required**)
- **`symbol`**: `string` (**required**)
- **`action`**: `string` (`"buy"` | `"sell"` | `"flat"`)
- **`notional_usd`**: `number` (0 if flat)
- **`reason`**: `string`
- **`status`**: `string` (e.g. `"pending"`, `"executed"`, `"rejected"`)
- **`strategy_id`**: `string|null` (optional)
- **`raw_model_output`**: `map` (optional)

#### Example document

```json
{
  "created_at": "2025-12-30T12:05:00.000Z (Firestore Timestamp)",
  "symbol": "SPY",
  "action": "buy",
  "notional_usd": 1000.00,
  "reason": "Strong momentum signal",
  "status": "pending",
  "strategy_id": "delta_momentum_v1",
  "raw_model_output": {
    "confidence": 0.85
  }
}
```

---

## Multi-tenancy migration notes

### Legacy global collections
The following collections are deprecated in favor of user-scoped paths:

- `alpacaAccounts/snapshot` → `users/{userId}/alpacaAccounts/snapshot`
- `tradingSignals/{signalId}` → `users/{userId}/tradingSignals/{signalId}`

### Secret Manager key storage
Each user's Alpaca API credentials should be stored in Google Cloud Secret Manager with the following pattern:

```
projects/{PROJECT_ID}/secrets/alpaca-keys-{USER_ID}/versions/latest
```

Secret payload should be JSON:
```json
{
  "key_id": "ALPACA_API_KEY_ID",
  "secret_key": "ALPACA_SECRET_KEY"
}
```

