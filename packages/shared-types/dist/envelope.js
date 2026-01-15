"use strict";

/**
 * Runtime validator for the canonical EventEnvelope JSON shape.
 *
 * NOTE:
 * This is a minimal, CommonJS build artifact used by Python/Node contract tests.
 * Source of truth: `packages/shared-types/src/envelope.ts`.
 */
function isEventEnvelope(value) {
  if (value === null || typeof value !== "object") return false;
  const v = value;
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

function isEventEnvelopeV1(value) {
  if (!isEventEnvelope(value)) return false;
  const v = value;
  return v.schemaVersion === 1;
}

module.exports = {
  isEventEnvelope,
  isEventEnvelopeV1,
};

