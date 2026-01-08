import type { PubSubEvent } from "./pubsub";
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
export type MissionControlAgentsResponse = Agent[] | {
    agents: Agent[];
};
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
export type MissionControlEventsResponse = Event[] | {
    events: Event[];
};
export type DeployReportResponse = string | {
    deploy_report_md?: string;
    markdown?: string;
    content?: string;
    report_md?: string;
    [k: string]: unknown;
};
/**
 * Mission Control / system events.
 *
 * The existing `Event` type in this file represents a log/event record shape
 * used by Mission Control APIs. To support Pub/Sub usage, we define explicit
 * event envelope schemas below (additive exports; no breaking changes).
 *
 * Versioning guidance:
 * - Adding optional fields to payload or envelope is safe.
 * - Adding required fields, removing fields, or changing field meaning/units
 *   requires a new schema version (publish a new `...EventV2` etc.).
 * - Keep older schema types exported to avoid breaking downstream consumers.
 */
/**
 * Payload: Mission Control "event record" (v1).
 * We reuse the existing `Event` type as the payload contract.
 */
export type MissionControlEventPayloadV1 = Event;
/**
 * Payload: Mission Control "agent state snapshot" (v1).
 * We reuse the existing `Agent` type as the payload contract.
 */
export type MissionControlAgentPayloadV1 = Agent;
/**
 * Pub/Sub event schemas (v1).
 *
 * `eventType` naming:
 * - "mission_control.event": log/event record emitted by the system
 * - "mission_control.agent": agent snapshot/state update
 */
export type MissionControlEventV1 = PubSubEvent<"mission_control.event", 1, MissionControlEventPayloadV1>;
export type MissionControlAgentV1 = PubSubEvent<"mission_control.agent", 1, MissionControlAgentPayloadV1>;
export type MissionControlPubSubEventV1 = MissionControlEventV1 | MissionControlAgentV1;
//# sourceMappingURL=mission-control.d.ts.map