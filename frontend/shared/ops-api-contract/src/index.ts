/**
 * AgentTrader v2 — Ops API Contract (read-only)
 *
 * This module is intended to be the single source of truth for the ops-dashboard UI
 * and any other read-only consumers.
 *
 * Constraints:
 * - No execution paths
 * - No mutations
 */

// -----------------------------
// Shared primitives
// -----------------------------

export type IsoUtcTimestamp = string; // e.g. "2026-01-07T12:00:00Z"

export type ServiceKind = "marketdata" | "strategy" | "execution" | "ingest" | "ops";

// Align with `backend/ops/status_contract.py`
export type OpsState = "OK" | "DEGRADED" | "HALTED" | "MARKET_CLOSED" | "OFFLINE" | "UNKNOWN";

// Stable reason codes (contract strings) + forward-compatible extension.
export type OpsReasonCode =
  | "KILL_SWITCH"
  | "MARKET_CLOSED"
  | "MARKETDATA_STALE"
  | "MARKETDATA_MISSING"
  | "EXECUTION_DISABLED"
  | "HEARTBEAT_STALE"
  | "REQUIRED_FIELDS_MISSING"
  | (string & {});

export type EndpointResult = {
  ok: boolean;
  status_code: number | null;
  latency_ms: number | null;
  error: string | null;
};

// -----------------------------
// /ops/status (service-level)
// -----------------------------

export type OpsAgentIdentity = {
  agent_name: string;
  agent_role: string;
  agent_mode: string;
};

export type OpsStatusBlock = {
  state: OpsState;
  summary: string;
  reason_codes: OpsReasonCode[];
  last_updated_utc: IsoUtcTimestamp;
};

export type OpsHeartbeatBlock = {
  last_heartbeat_utc: IsoUtcTimestamp | null;
  age_seconds: number | null;
  ttl_seconds: number;
};

export type OpsMarketdataBlock = {
  last_tick_utc: IsoUtcTimestamp | null;
  last_bar_utc: IsoUtcTimestamp | null;
  stale_threshold_seconds: number;
  is_fresh: boolean | null;
};

export type OpsSafetyBlock = {
  kill_switch: boolean;
  safe_to_run_strategies: boolean;
  /**
   * MUST remain false (contract rule). Any UI should treat `true` as an anomaly.
   */
  safe_to_execute_orders: false;
  gating_reasons: OpsReasonCode[];
};

export type OpsEndpointsBlock = {
  healthz: string | null;
  heartbeat: string | null;
  metrics: string | null;
};

export type OpsStatus = {
  service_name: string;
  service_kind: ServiceKind;
  repo_id: string;
  git_sha: string | null;
  build_id: string | null;

  agent_identity: OpsAgentIdentity;

  status: OpsStatusBlock;
  heartbeat: OpsHeartbeatBlock;

  // Nullable / kind-specific
  marketdata: OpsMarketdataBlock | null;

  safety: OpsSafetyBlock;
  endpoints: OpsEndpointsBlock | null;
};

// -----------------------------
// /ops/health (service-level)
// -----------------------------

export type OpsHealthResponse = {
  status: "ok";
  service: string;
  ts: IsoUtcTimestamp;
};

// -----------------------------
// Mission Control (ops-dashboard facing)
// -----------------------------

export type MissionControlKillSwitch = {
  execution_halted: boolean;
  source: string | null;
};

export type MissionControlAgentOps = {
  agent_name: string;
  kind: Exclude<ServiceKind, "ops">;
  criticality: "critical" | "important" | "optional";
  service_dns: string;
  expected_endpoints: string[];

  online: boolean | null;
  last_poll_at: IsoUtcTimestamp | null;

  endpoints: {
    healthz: EndpointResult | null;
    ops_status: EndpointResult | null;
    heartbeat: EndpointResult | null;
  };

  /**
   * Best-effort: if the downstream agent conforms to `OpsStatus`, this is populated.
   * Otherwise it is null and `ops.state` falls back to a derived state.
   */
  ops_status: OpsStatus | null;

  /**
   * Stable UI-facing state (prefer this over inspecting `raw_ops_status_redacted`).
   */
  ops: {
    state: OpsState;
    summary: string;
    reason_codes: OpsReasonCode[];
    last_updated_utc: IsoUtcTimestamp | null;
  };

  /**
   * Redacted raw payload returned from the downstream agent `/ops/status`.
   * This is intended only for drill-down debugging in the UI.
   */
  raw_ops_status_redacted: unknown | null;

  marketdata_freshness:
    | {
        source: "/heartbeat" | "/healthz";
        ok: boolean | null;
        age_seconds: number | null;
        max_age_seconds: number | null;
        last_tick_epoch_seconds: number | null;
      }
    | null;
};

export type MissionControlOpsStatusResponse = {
  ts: IsoUtcTimestamp;
  kill_switch: MissionControlKillSwitch;
  last_poll_cycle_at: IsoUtcTimestamp | null;
  agents: MissionControlAgentOps[];
};

// -----------------------------
// Mission Control events + deploy report (existing UI surfaces)
// -----------------------------

export type MissionControlEvent = {
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

export type MissionControlEventsResponse = MissionControlEvent[] | { events: MissionControlEvent[] };

export type DeployReportResponse =
  | string
  | {
      deploy_report_md?: string;
      markdown?: string;
      content?: string;
      report_md?: string;
      [k: string]: unknown;
    };

