/**
 * Pub/Sub event envelope primitives.
 *
 * Design goals:
 * - Stable, explicit envelope for all events (eventType/schemaVersion/producedAt/source/payload)
 * - No runtime behavior: types only
 * - Safe evolution: additive changes are backwards compatible; breaking changes require new version
 *
 * Versioning guidance:
 * - Adding OPTIONAL fields to payload/envelope is safe (non-breaking).
 * - Adding REQUIRED fields is breaking: bump schemaVersion and publish a new event schema type.
 * - Renaming/removing fields is breaking: bump schemaVersion; keep old schema type exported.
 * - Changing field meaning/units is breaking unless strictly equivalent: bump schemaVersion.
 */

/**
 * ISO-8601 timestamp string.
 *
 * Notes:
 * - We intentionally keep this as `string` to avoid imposing a runtime date library.
 * - Producers should emit RFC3339/ISO8601 (e.g. `2026-01-08T12:34:56.789Z`).
 */
export type IsoDateTimeString = string;

/**
 * Where an event was produced from. Requirement: vm / service / agent.
 *
 * `name` should be stable (service name, agent name, or VM identifier).
 * `instanceId` can vary per deployment/replica and is useful for debugging.
 */
export type PubSubSourceKind = "vm" | "service" | "agent";

export type PubSubSource = {
  kind: PubSubSourceKind;
  name: string;
  instanceId?: string;
  /**
   * Freeform additional metadata. Keep this additive-only.
   * (Avoid making consumers depend on it; treat as debug context.)
   */
  meta?: Record<string, unknown>;
};

/**
 * Generic, explicit Pub/Sub event schema envelope.
 *
 * `eventType` should be a stable, dot-delimited identifier (e.g. "market.bar").
 * `schemaVersion` is an integer; bump only on breaking schema changes.
 */
export type PubSubEvent<
  TEventType extends string,
  TSchemaVersion extends number,
  TPayload,
> = {
  eventType: TEventType;
  schemaVersion: TSchemaVersion;
  producedAt: IsoDateTimeString;
  source: PubSubSource;
  payload: TPayload;
};

