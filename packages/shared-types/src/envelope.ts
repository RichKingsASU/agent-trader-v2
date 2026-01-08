/**
 * Canonical agent-to-agent message envelope.
 *
 * This matches `backend/messaging/envelope.py` (`EventEnvelope`) 1:1 at the JSON level.
 *
 * Constraints:
 * - snake_case field names (do not change without a coordinated migration)
 * - payload shape is event-specific; envelope fields are stable
 */
export type EventEnvelope<
  TPayload extends Record<string, unknown> = Record<string, unknown>,
> = {
  event_type: string;
  agent_name: string;
  git_sha: string;
  ts: string; // ISO-8601 timestamp (UTC recommended)
  payload: TPayload;
  trace_id: string;
};

/**
 * Canonical EventEnvelope v1 (schemaVersion REQUIRED).
 *
 * Back-compat note:
 * - `EventEnvelope` (without schemaVersion) is legacy and should not be used for new producers.
 */
export interface EventEnvelopeV1<
  TPayload extends Record<string, unknown> = Record<string, unknown>,
> extends EventEnvelope<TPayload> {
  schemaVersion: 1;
}

/**
 * JSON-level runtime validator for the envelope shape.
 *
 * Notes:
 * - This intentionally validates only the envelope surface area, not `payload`.
 * - This is used for cross-language contract testing (Python -> Node -> TS schema).
 */
export function isEventEnvelope(value: unknown): value is EventEnvelope {
  if (value === null || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;

  return (
    typeof v.event_type === "string" &&
    typeof v.agent_name === "string" &&
    typeof v.git_sha === "string" &&
    typeof v.ts === "string" &&
    v.payload !== null &&
    typeof v.payload === "object" &&
    typeof v.trace_id === "string"
  );
}

export function isEventEnvelopeV1(value: unknown): value is EventEnvelopeV1 {
  if (!isEventEnvelope(value)) return false;
  const v = value as Record<string, unknown>;
  return v.schemaVersion === 1;
}

