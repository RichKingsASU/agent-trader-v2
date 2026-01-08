/**
 * System event payload (ops-friendly structured log record).
 *
 * Mirrors the JSON emitted by `backend/observability/ops_json_logger.py`.
 * Payload-only: wrap with `EventEnvelope<T>` at the transport boundary.
 */
export type SystemEventPayload = {
  timestamp: string;
  severity: string;
  service: string;

  env: string;
  version: string;
  sha: string;
  git_sha: string; // back-compat alias (kept as field; do not remove yet)
  image_tag: string;
  agent_mode: string;

  request_id: string;
  correlation_id: string;

  event_type: string;
  event: string; // back-compat alias (kept as field; do not remove yet)

  [k: string]: unknown;
};

