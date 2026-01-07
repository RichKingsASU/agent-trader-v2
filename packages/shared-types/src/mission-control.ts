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

