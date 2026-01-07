export type OpsState = "OK" | "DEGRADED" | "HALTED" | "OFFLINE" | "UNKNOWN";

export type EndpointResult = {
  ok: boolean;
  status_code: number | null;
  latency_ms: number | null;
  error: string | null;
} | null;

export type Agent = {
  // Mission Control (canonical)
  agent_name?: string;
  status?: "ONLINE" | "OFFLINE" | "UNKNOWN" | string;
  last_poll_at?: string | null;
  criticality?: string;
  service_dns?: string;
  expected_endpoints?: string[];
  healthz?: EndpointResult;
  ops_status?: EndpointResult;
  heartbeat?: EndpointResult;
  marketdata_freshness?: Record<string, unknown> | null;
  raw_ops_status?: unknown;

  // Legacy / compatibility
  name?: string;
  kind?: string;
  state?: string;
  summary?: string;
  last_updated?: string | number;
  heartbeat_ts?: string | number;
  build_fingerprint?: string;
  build?: Record<string, unknown>;
  [k: string]: unknown;
};

export type MissionControlAgentsResponse = Agent[] | { agents: Agent[] };

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

export type AgentDetailResponse = { ts?: string; agent: Agent };

export type SafetyResponse = {
  ts?: string;
  kill_switch: { execution_halted: boolean; source?: string | null };
  marketdata: {
    all_critical_fresh: boolean;
    agents: Array<{
      agent_name: string;
      criticality?: string;
      status?: string;
      freshness?: Record<string, unknown> | null;
    }>;
  };
};

