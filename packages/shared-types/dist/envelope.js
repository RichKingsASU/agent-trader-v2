/**
 * Minimal runtime validator for EventEnvelope.
 *
 * NOTE: This file is intentionally committed because Python contract tests
 * validate the envelope JSON shape against the TS runtime validator.
 */
function isPlainObject(x) {
  return !!x && typeof x === "object" && !Array.isArray(x);
}

function isNonEmptyString(x) {
  return typeof x === "string" && x.trim().length > 0;
}

function isEventEnvelope(obj) {
  if (!isPlainObject(obj)) return false;
  if (obj.schemaVersion !== 1) return false;
  if (!isNonEmptyString(obj.event_type)) return false;
  if (!isNonEmptyString(obj.agent_name)) return false;
  if (!isNonEmptyString(obj.git_sha)) return false;
  if (!isNonEmptyString(obj.ts)) return false;
  if (!isNonEmptyString(obj.trace_id)) return false;
  if (!isPlainObject(obj.payload)) return false;
  return true;
}

module.exports = {
  isEventEnvelope,
};

