export type {
  DeployReportResponse,
  MissionControlEvent as Event,
  MissionControlEventsResponse,
  MissionControlOpsStatusResponse,
  MissionControlAgentOps,
  OpsState,
  OpsStatus,
  OpsHealthResponse,
  EndpointResult,
} from "@ops-contract";

// Back-compat alias for older UI naming.
export type Agent = import("@ops-contract").MissionControlAgentOps;

