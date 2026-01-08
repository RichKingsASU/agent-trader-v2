/**
 * Changelog:
 * - 2026-01-08: Schema governance — standardize event envelope fields and naming.
 *   - Canonical event fields are camelCase.
 *   - All governed events include: schemaVersion, eventId, producedAt.
 *   - Legacy fields (snake_case + historical keys) remain as optional aliases for compatibility.
 */

export type OpsState = "OK" | "DEGRADED" | "HALTED" | "OFFLINE" | "UNKNOWN";

export type Agent = {
  name: string;
  kind?: string;
  state?: string;
  summary?: string;
  last_updated?: string | number;
  heartbeat_ts?: string | number;
  build_fingerprint?: string;
  build?: Record<string, unknown>;
  ops_status?: unknown;
  [k: string]: unknown;
};

export type MissionControlAgentsResponse = Agent[] | { agents: Agent[] };

/**
 * Versioned envelope required on all governed events.
 */
export type EventEnvelopeV1 = {
  /**
   * Schema version for this event shape.
   *
   * Increment when making backward-incompatible changes to required fields.
   */
  schemaVersion: 1;

  /**
   * Stable unique identifier for the event (UUID recommended).
   */
  eventId: string;

  /**
   * When the event was produced.
   *
   * Recommended: ISO-8601 UTC string. Also accepts epoch milliseconds for compatibility.
   */
  producedAt: string | number;
};

/**
 * Mission Control event payload.
 *
 * Canonical field names are camelCase. Legacy aliases remain optional for compatibility with
 * older producers/consumers.
 */
export type Event = EventEnvelopeV1 & {
  /**
   * Optional agent identifier/name associated with the event.
   */
  agent?: string;

  /**
   * Canonical agent name field (camelCase).
   */
  agentName?: string;

  kind?: string;
  type?: string;
  level?: string;
  message?: string;
  summary?: string;
  outcome?: string;

  /**
   * @deprecated Use eventId.
   */
  id?: string;

  /**
   * @deprecated Use producedAt.
   */
  ts?: string | number;

  /**
   * @deprecated Use producedAt.
   */
  timestamp?: string | number;

  /**
   * @deprecated Use agentName.
   */
  agent_name?: string;

  [k: string]: unknown;
};

export type MissionControlEventsResponse = Event[] | { events: Event[] };

export type DeployReportResponse =
  | string
  | {
      deploy_report_md?: string;
      markdown?: string;
      content?: string;
      report_md?: string;
      [k: string]: unknown;
    };

