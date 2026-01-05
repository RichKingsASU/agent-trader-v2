## UI component paths (where quotes render)

- **Dashboard page**: `frontend/agenttrader-ui/app/dashboard/page.tsx`
  - Renders `LiveQuotesWidget` (replaces the old `LiveTicker` slot).
- **Home page**: `frontend/agenttrader-ui/app/page.tsx`
  - Renders `LiveQuotesWidget`.
- **Quotes widget**: `frontend/agenttrader-ui/app/components/LiveQuotesWidget.tsx`
  - Displays **symbol**, **price or bid/ask**, and **last update time** per symbol.
  - Shows **LIVE / STALE / OFFLINE** badge (based on ops heartbeat freshness).

## Data wiring notes

### Firestore client

- **Client init**: `frontend/agenttrader-ui/app/lib/firestoreClient.ts`
- Uses public env vars and returns `null` (non-throwing) when not configured.
- **Required env vars**:
  - `NEXT_PUBLIC_FIREBASE_API_KEY`
  - `NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN`
  - `NEXT_PUBLIC_FIREBASE_PROJECT_ID`
  - `NEXT_PUBLIC_FIREBASE_APP_ID`
- **Optional env vars**:
  - `NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET`
  - `NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID`

### Live quotes subscription (Firestore)

- **Hook**: `frontend/agenttrader-ui/app/hooks/useLiveQuotes.ts`
- **Firestore path**: collection `live_quotes`
  - Each document is mapped to a `LiveQuote`.
  - `symbol` is taken from `doc.data().symbol` when present; otherwise falls back to `doc.id`.
- **Timestamp safety**:
  - `last_update_ts` is coerced safely from:
    - Firestore `Timestamp` (`toDate()`),
    - `Date`,
    - epoch millis `number`,
    - ISO string `string`.
  - Field fallback order: `last_update_ts` → `lastUpdateTs` → `updated_at`/`updatedAt` → `ts`.

### Heartbeat subscription (ops/market_ingest)

- **Hook**: `frontend/agenttrader-ui/app/hooks/useMarketIngestStatus.ts`
- **Firestore path**: document `ops/market_ingest`
- **Badge logic**:
  - **LIVE**: heartbeat age ≤ 30s
  - **STALE**: heartbeat age > 30s
  - **OFFLINE**: no heartbeat field (or Firestore not configured / subscription error)
- Heartbeat timestamp field is detected from common names:
  - `last_heartbeat_at`, `last_heartbeat`, `lastHeartbeatAt`, `lastHeartbeat`, `updated_at`, `updatedAt`, `ts`, `timestamp`

