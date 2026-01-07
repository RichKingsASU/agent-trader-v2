import * as React from "react";
import { Bar, BarChart, CartesianGrid, Tooltip, XAxis, YAxis } from "recharts";
import { missionControlApi } from "@/api/client";
import type { Agent, MissionControlAgentsResponse, OpsState } from "@/api/types";
import { ChartContainer } from "@/components/charts/chart";
import { ErrorBanner } from "@/components/ErrorBanner";
import { usePolling } from "@/hooks/usePolling";
import { agentOpsState } from "@/utils/agents";
import { formatIso } from "@/utils/time";

function unpackAgents(payload: MissionControlAgentsResponse): Agent[] {
  return Array.isArray(payload) ? payload : payload.agents || [];
}

function stateCounts(agents: Agent[]): Record<OpsState, number> {
  const out: Record<OpsState, number> = { OK: 0, DEGRADED: 0, HALTED: 0, OFFLINE: 0, UNKNOWN: 0 };
  for (const a of agents) out[agentOpsState(a)]++;
  return out;
}

export function MetricsPage() {
  const agentsLoader = React.useCallback(async () => {
    const res = await missionControlApi.listAgents();
    return res.ok ? ({ ok: true, data: unpackAgents(res.data) } as const) : ({ ok: false, error: res.error } as const);
  }, []);

  const agentsPoll = usePolling<Agent[]>(agentsLoader, 10_000);
  const agents = agentsPoll.data || [];
  const counts = stateCounts(agents);
  const data = [
    { state: "OK", count: counts.OK },
    { state: "DEGRADED", count: counts.DEGRADED },
    { state: "OFFLINE", count: counts.OFFLINE },
    { state: "UNKNOWN", count: counts.UNKNOWN },
  ];

  return (
    <div className="grid">
      <div style={{ gridColumn: "span 12" }}>
        {agentsPoll.error ? <ErrorBanner message={agentsPoll.error} /> : null}
        <div className="meta" style={{ marginTop: 8 }}>
          Last refreshed: <span className="mono">{formatIso(agentsPoll.lastRefreshed)}</span>
        </div>
      </div>

      <div className="card" style={{ gridColumn: "span 12" }}>
        <h2>Agent state distribution</h2>
        <div className="muted" style={{ marginBottom: 10 }}>
          Derived from Mission Control agent summaries (online/offline + endpoint health).
        </div>
        <ChartContainer
          config={{
            count: { label: "Agents", color: "var(--ok)" },
          }}
        >
          <BarChart data={data} margin={{ top: 12, right: 12, left: 0, bottom: 6 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="state" />
            <YAxis allowDecimals={false} />
            <Tooltip />
            <Bar dataKey="count" name="Agents" fill="var(--color-count)" />
          </BarChart>
        </ChartContainer>
      </div>
    </div>
  );
}

