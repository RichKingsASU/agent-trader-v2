# Mission 1 — Repo-Wide Sanity + Contract Audit (SAFE)

Scope constraints honored:
- **No runtime behavior changes** (only type-level changes made; see “Fixes applied”)
- **No infrastructure/deployment file edits** (issues may still be *reported* if found)

Focus areas covered:
- `packages/shared-types`
- TypeScript/JS code that handles “event-like” payloads (WebSocket / dashboard)
- “dashboard ingestion” code in `frontend/src/lib` + `frontend/src/hooks`
- “VM ingest” / Pub/Sub payload references (**none found in TS/JS; see notes**)

---

## Executive summary

### High severity
- **Broken import / build break** in `frontend/ops-ui/vite.config.ts`: `path` is referenced but not imported.
- **Internal contract mismatch hidden by `any`**: `frontend/src/contexts/DataStreamContext.tsx` provides a context value that does **not** match what consumers expect (likely runtime failures; TypeScript doesn’t catch it because the context is `any`).

### Medium severity
- **Duplicate schemas / drift risk** for Mission Control contracts:
  - `packages/shared-types/src/mission-control.ts` (minimal permissive types)
  - `frontend/shared/ops-api-contract/src/index.ts` (richer “single source of truth” contract)
  - These disagree on `OpsState` (fixed type-only in `shared-types`; see below).
- **Widespread `any` at ingestion boundaries** (WebSocket / realtime stream plumbing, auth claims, UI state blobs). This blocks detection of mismatched payload shapes.

### Low severity
- Localized `any` usages in UI components and pages (state blobs, chart libraries, formatter callbacks) that are not directly contract-bound.

---

## Issues found (with affected files + severity)

### 1) Broken import (build-time failure)
- **Severity**: **HIGH**
- **Issue**: `path` is used but never imported.
- **Files affected**:
  - `frontend/ops-ui/vite.config.ts`
- **Why it matters**: The ops UI build/dev server config will fail to evaluate.
- **Notes**: Per instructions, I did **not** modify this file (it’s build tooling / deployment-adjacent). This is report-only.

---

### 2) Duplicate Mission Control schemas (drift + mismatched state unions)
- **Severity**: **MEDIUM** (can become **HIGH** when endpoints/UI expectations drift)
- **Issue**: Two competing “Mission Control” type sources exist, with overlapping but not identical types:
  - `packages/shared-types/src/mission-control.ts`
  - `frontend/shared/ops-api-contract/src/index.ts`
- **Concrete mismatch**:
  - `OpsState` in `shared-types` previously omitted `"MARKET_CLOSED"` while `ops-api-contract` includes it.
- **Files affected / evidence**:
  - `packages/shared-types/src/mission-control.ts`
  - `frontend/shared/ops-api-contract/src/index.ts`
  - `apps/ops-dashboard/src/api/types.ts` (re-exports from `@agenttrader/shared-types`)
  - `frontend/ops-ui/src/api/types.ts` (re-exports from `@ops-contract`)
  - `apps/ops-dashboard/src/pages/OverviewPage.tsx` (does **not** normalize `MARKET_CLOSED`)
  - `frontend/ops-ui/src/pages/OverviewPage.tsx` (does normalize `MARKET_CLOSED`)
- **Why it matters**:
  - Contract drift creates “it works in one dashboard but not the other” situations.
  - Type widening/narrowing can hide real runtime states.

---

### 3) Internal “DataStream” contract mismatch masked by `any`
- **Severity**: **HIGH**
- **Issue**: `DataStreamContext` is typed as `any` and supplies only a small subset of methods, but consumers assume a richer API.
- **Files affected**:
  - Provider (source of mismatch):
    - `frontend/src/contexts/DataStreamContext.tsx`
  - Consumers expecting methods not present:
    - `frontend/src/hooks/useWebSocketStream.tsx` (expects `unregisterStream`, `updateStreamStatus`, `recordMessage`)
    - `frontend/src/components/developer/DataStreamPanel.tsx` (expects fields like `messagesPerSecond`, `errorCount`, `connectedAt`, etc.)
    - `frontend/src/components/developer/StreamManager.tsx` (expects `connectRealStream(streamId, wsUrl, symbolList)` signature; provider currently has `connectRealStream()` with no params)
- **Why it matters**:
  - This is exactly the class of failure you called out: **event/contract shape mismatch** that TypeScript should catch, but doesn’t due to `any`.
- **Notes**:
  - Fixing this correctly likely requires adding missing functions/fields (runtime behavior change). Per instructions, I’m reporting rather than altering runtime behavior.

---

### 4) `any` at contract boundaries (WebSocket + auth claims + stream messages)
- **Severity**: **MEDIUM**
- **Issue**: Many “boundary” surfaces use `any`, preventing detection of mismatched payload shapes.
- **Representative files affected** (not exhaustive):
  - WebSocket plumbing:
    - `frontend/src/services/WebSocketManager.ts` (`MessageHandler = (data: any, ...)`)
    - `frontend/src/hooks/useWebSocketStream.tsx` (`onMessage?: (data: any) => void`, `send(data: any)`)
    - `frontend/src/services/AlpacaWebSocket.ts` (multiple `any` message shapes)
    - `frontend/src/services/MockAlpacaServer.ts` (`messages: any[]`)
  - Auth claim extraction:
    - `frontend/src/contexts/AuthContext.tsx` (`(token.claims as any)?.tenant_id ...`)
  - Dashboard/UI state blobs:
    - `frontend/src/pages/*` (multiple `useState<any>`, `catch (err: any)`, and other `any`)
- **Why it matters**:
  - `any` removes the compiler’s ability to enforce event shapes at the edges where mismatches are most costly.

---

### 5) “Dashboard ingestion” payload shape is unvalidated at the network boundary
- **Severity**: **MEDIUM**
- **Issue**: `eventLogStore` posts `{ logs: payload }` and expects error JSON with `.error`, but uses `(errorData as any)?.error`.
- **Files affected**:
  - `frontend/src/lib/eventLogStore.ts`
- **Why it matters**:
  - If the ingest service responds with a different error shape (string/body), the UI’s error rendering becomes noisy and the mismatch won’t be caught at compile time.
- **Notes**:
  - This is a “contract edge” but currently handled defensively at runtime. Tightening types here is possible without runtime changes, but would ripple through call sites.

---

### 6) Pub/Sub payload references in TypeScript/JavaScript
- **Severity**: **LOW** (as a finding), **UNKNOWN** (if Pub/Sub exists elsewhere)
- **Finding**: I did **not** find Pub/Sub payload handling in TS/JS under:
  - `frontend/`, `apps/`, `functions_js/`, `mcp/`
- **Interpretation**:
  - Pub/Sub handling may be in Python (`backend/`, `functions/`) or infra, outside this TypeScript-focused scan.
  - Per your instruction (“If unsure, report — do not guess”), I’m explicitly not asserting Pub/Sub doesn’t exist repo-wide.

---

## Fixes applied (safe, non-breaking, type-only)

- **Widened `OpsState` union** in `packages/shared-types` to include `"MARKET_CLOSED"` to match the richer ops contract:
  - `packages/shared-types/src/mission-control.ts`
  - This is a **type-only widening** and does **not** change runtime behavior.

---

## Recommended next safe steps (no runtime behavior change)

- **Make `DataStreamContext` strongly typed** (even if you keep runtime identical):
  - This will immediately surface the missing methods/fields as compile-time errors instead of runtime surprises.
  - If you want “no runtime changes”, you can still add types but you’ll likely need to reconcile the mismatches in a follow-up mission that allows runtime-safe no-op implementations.
- **Consolidate Mission Control contracts**:
  - Pick one canonical module (`frontend/shared/ops-api-contract` looks intended as the source of truth) and ensure dashboards consume that, or generate both from one schema.
- **Replace `any` with `unknown` at message boundaries** (WebSocket + ingest):
  - Keep runtime parsing/guards the same, but force explicit narrowing where shape assumptions are made.

