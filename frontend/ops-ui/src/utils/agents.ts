import type { Agent, OpsState } from "@/api/types";
import { parseTimestamp } from "@/utils/time";

export function agentName(a: Agent): string {
  return String(a.agent_name || a.name || "");
}

export function agentKind(a: Agent): string {
  return a.kind ? String(a.kind) : "—";
}

export function agentCriticality(a: Agent): string {
  return a.criticality ? String(a.criticality) : "—";
}

export function agentLastPollAt(a: Agent): Date | null {
  return parseTimestamp(a.last_poll_at ?? a.last_updated ?? null);
}

export function agentOpsState(a: Agent): OpsState {
  const status = (a.status || a.state || "").toString().toUpperCase();
  const online = status === "ONLINE" || status === "OK";
  const offline = status === "OFFLINE";

  if (offline) return "OFFLINE";

  // If Mission Control can reach the process but key endpoints fail, treat as degraded.
  const healthOk = a.healthz?.ok;
  const opsOk = a.ops_status?.ok;

  if (online && (healthOk === false || opsOk === false)) return "DEGRADED";
  if (online && (healthOk === true || opsOk === true)) return "OK";

  // Fall back to older state-style fields if present.
  if (status === "DEGRADED") return "DEGRADED";
  if (status === "HALTED") return "HALTED";

  return "UNKNOWN";
}

