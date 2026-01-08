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
export type Event = {
    id?: string;
    ts?: string | number;
    timestamp?: string | number;
    agent?: string;
    agent_name?: string;
    kind?: string;
    type?: string;
    level?: string;
    message?: string;
    summary?: string;
    outcome?: string;
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