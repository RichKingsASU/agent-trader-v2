## Disaster recovery & replay strategy

Goal: **rebuild Firestore read models from canonical events** safely, repeatedly, and without double-applying.

This repo’s pattern is: **Pub/Sub is canonical → Firestore is a projection** (materialized “read model”).

---

## 1) Replayable vs non-replayable topics

### Replayable (safe to re-run)

Replayable topics meet all of these:

- **Deterministic projection**: applying the same logical event twice converges to the same state (idempotent) or is explicitly deduped.
- **No external side-effects**: handler only writes projections (Firestore, BigQuery append with deterministic keys, etc.), not “do a thing”.
- **Stable identity**: event has a stable `eventId`/key, or the projection uses deterministic doc IDs + stale guards.

In this repo, the following **materialization-style** streams are replayable by design:

- **`system-events` / ops status** → Firestore `ops_services/*` (transactional dedupe exists; stale guard exists)
- **`market-ticks`** → Firestore `market_ticks/*` (deterministic doc ids + stale guard)
- **`market-bars-1m`** → Firestore `market_bars_1m/*` (deterministic doc ids + stale guard)
- **`trade-signals`** → Firestore `trade_signals/*` (deterministic doc ids + stale guard)

### Non-replayable (must not be re-run blindly)

Non-replayable topics are any stream where consuming it causes **irreversible side effects**, or where idempotency cannot be guaranteed.

Common examples (even if your system later adds them):

- **Order execution / broker calls** (place/cancel/replace orders)
- **Money movement** (transfers, withdrawals)
- **Notifications** (email/SMS/webhooks) unless they have a deterministic idempotency key at the sink
- **“Emit another event”** producers where duplication cascades downstream

Rule of thumb: if the consumer can affect the world outside your database, treat the topic as **non-replayable** unless it has explicit sink-side idempotency.

---

## 2) Replay markers in Firestore (support added)

Replay mode uses **two Firestore bookkeeping collections**:

- **`ops_replay_runs/{runId}`**
  - Presence + lightweight metadata (consumer name, which topics observed, lastUpdatedAt).
- **`ops_replay_markers/{consumer__topic}`**
  - Watermarks:
    - `lastSeen`: last message observed in replay
    - `lastApplied`: last message that actually changed the projection

These are **best-effort markers**: failures to write markers should not fail message processing.

---

## 3) Ignore already-applied events (support added)

When `REPLAY_RUN_ID` is set, the consumer enables a replay-mode idempotency store:

- **`ops_applied_events/{consumer__topic__dedupeKey}`**
  - Created transactionally alongside the projection write.
  - If it already exists, the consumer treats the event as `already_applied_noop`.

Important nuance:

- This only provides “exactly-once” semantics **if `dedupeKey` is stable across replays**.
- Prefer a producer-supplied `eventId`. If missing, the current code falls back to deterministic doc ids (or a tuple-like key for system events).

Operational recommendation:

- Add an `eventId` to all replayable envelopes (producer change) to make replay correctness airtight.
- Configure a Firestore TTL policy on `ops_applied_events.expireAt` if you choose to set/use it (this repo stores the field but does not configure TTL policies).

---

## 4) Safe replay procedure (operator runbook)

### Preconditions

- You can re-read historical events (Pub/Sub seek on a subscription, or republish from an archive).
- You can **pause** normal projection writes while replay runs, or you can replay into **shadow collections**.

### Recommended approach: shadow-write + cutover (safest)

1. **Pick a replay run id**
   - Example: `REPLAY_RUN_ID=2026-01-08_ops_rebuild_01`

2. **Deploy the consumer in replay mode, writing to shadow collections**
   - Set:
     - `REPLAY_RUN_ID=<run id>`
     - `FIRESTORE_COLLECTION_PREFIX=replay_<run id>__`
   - This routes projection writes to:
     - `replay_<run>__ops_services`
     - `replay_<run>__market_ticks`
     - etc.

3. **Create/seek a replay subscription**
   - Create a dedicated subscription (or use seek) that starts at your desired timestamp.
   - Point it at the replay-mode consumer.

4. **Monitor progress**
   - Watch:
     - `ops_replay_markers/{consumer__topic}.lastSeen`
     - `ops_replay_markers/{consumer__topic}.lastApplied`
   - Validate counts and spot-check documents in the shadow collections.

5. **Cut over**
   - Once validated, switch readers (dashboard/UI/services) from the primary collections to the shadow collections, or copy/rename in a controlled maintenance window.

6. **Exit replay mode**
   - Remove `REPLAY_RUN_ID` and `FIRESTORE_COLLECTION_PREFIX` and restore normal subscriptions.

### Faster (riskier): in-place replay

Only do this if your projections are strictly last-write-wins and you can tolerate intermediate inconsistency.

1. Pause normal consumers (or stop the input subscriptions).
2. Run replay with `REPLAY_RUN_ID` (no prefix).
3. Monitor `ops_replay_markers` and validate.
4. Resume normal consumption.

---

## Environment variables (minimal hooks)

In `cloudrun_consumer`:

- **`REPLAY_RUN_ID`**: enables replay mode (markers + replay idempotency store)
- **`FIRESTORE_COLLECTION_PREFIX`**: optional safe replay shadow namespace for projections

