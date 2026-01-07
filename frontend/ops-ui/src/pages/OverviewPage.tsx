import * as React from "react";
import { Link } from "react-router-dom";
import { missionControlApi } from "@/api/client";
import type { Agent, Event, MissionControlAgentsResponse, MissionControlEventsResponse, OpsState } from "@/api/types";
import { Badge } from "@/components/Badge";
import { ErrorBanner } from "@/components/ErrorBanner";
import { usePolling } from "@/hooks/usePolling";
import { formatAgeMs, formatIso, parseTimestamp } from "@/utils/time";

function unpackAgents(payload: MissionControlAgentsResponse): Agent[] {
  return Array.isArray(payload) ? payload : payload.agents || [];
}

function unpackEvents(payload: MissionControlEventsResponse): Event[] {
  return Array.isArray(payload) ? payload : payload.events || [];
}

function normalizeState(raw: unknown): OpsState {
  if (typeof raw !== "string") return "UNKNOWN";
  const s = raw.toUpperCase();
  if (s === "OK") return "OK";
  if (s === "DEGRADED") return "DEGRADED";
  if (s === "HALTED") return "HALTED";
  if (s === "OFFLINE") return "OFFLINE";
  return "UNKNOWN";
}

function getAgentState(agent: Agent): OpsState {
  const direct = normalizeState(agent.state);
  if (direct !== "UNKNOWN") return direct;
  const fromOps = (agent.ops_status as Record<string, unknown> | undefined)?.state;
  const fromStatus = (agent as unknown as { status?: Record<string, unknown> }).status?.state;
  return normalizeState(fromOps ?? fromStatus);
}

function getAgentLastUpdated(agent: Agent): Date | null {
  return (
    parseTimestamp(agent.last_updated) ||
    parseTimestamp(agent.heartbeat_ts) ||
    parseTimestamp((agent as unknown as { lastUpdate?: unknown }).lastUpdate) ||
    null
  );
}

function getEventTs(e: Event): Date | null {
  return parseTimestamp(e.ts) || parseTimestamp(e.timestamp) || null;
}

function countStates(agents: Agent[]) {
  const counts: Record<OpsState, number> = { OK: 0, DEGRADED: 0, HALTED: 0, OFFLINE: 0, UNKNOWN: 0 };
  for (const a of agents) counts[getAgentState(a)]++;
  return counts;
}

export function OverviewPage() {
  const agentsLoader = React.useCallback(async () => {
    const res = await missionControlApi.listAgents();
    return res.ok ? ({ ok: true, data: unpackAgents(res.data) } as const) : ({ ok: false, error: res.error } as const);
  }, []);

  const eventsLoader = React.useCallback(async () => {
    const res = await missionControlApi.listRecentEvents();
    return res.ok ? ({ ok: true, data: unpackEvents(res.data) } as const) : ({ ok: false, error: res.error } as const);
  }, []);

  const deployLoader = React.useCallback(async () => {
    const res = await missionControlApi.getLatestDeployReport();
    return res.ok ? ({ ok: true, data: res.data } as const) : ({ ok: false, error: res.error } as const);
  }, []);

  const agentsPoll = usePolling(agentsLoader, 10_000);
  const eventsPoll = usePolling(eventsLoader, 10_000);
  const deployPoll = usePolling(deployLoader, 10_000);

  const agents = agentsPoll.data || [];
  const events = eventsPoll.data || [];
  const counts = countStates(agents);
  const anyError = agentsPoll.error || eventsPoll.error || deployPoll.error;
  const lastRefreshed = agentsPoll.lastRefreshed || eventsPoll.lastRefreshed || deployPoll.lastRefreshed;

  return (
    <div className="grid">
      <div style={{ gridColumn: "span 12" }}>
        {anyError ? <ErrorBanner message={anyError} /> : null}
        <div className="meta" style={{ marginTop: 8 }}>
          Last refreshed: <span className="mono">{formatIso(lastRefreshed)}</span>
        </div>
      </div>

      <div className="card" style={{ gridColumn: "span 12" }}>
        <h2>System status</h2>
        <div className="status-row">
          <span className="status-pill">
            <Badge state="OK">OK</Badge> <span className="mono">{counts.OK}</span>
          </span>
          <span className="status-pill">
            <Badge state="DEGRADED">DEGRADED</Badge> <span className="mono">{counts.DEGRADED}</span>
          </span>
          <span className="status-pill">
            <Badge state="HALTED">HALTED</Badge> <span className="mono">{counts.HALTED}</span>
            <span className="muted">(often intentional)</span>
          </span>
          <span className="status-pill">
            <Badge state="OFFLINE">OFFLINE</Badge> <span className="mono">{counts.OFFLINE}</span>
          </span>
        </div>
      </div>

      <div className="card" style={{ gridColumn: "span 12" }}>
        <h2>Agents</h2>
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th className="hide-sm">Kind</th>
              <th>State</th>
              <th>Summary</th>
              <th className="hide-sm">Last updated</th>
              <th>Heartbeat age</th>
            </tr>
          </thead>
          <tbody>
            {agents.length === 0 ? (
              <tr>
                <td colSpan={6} className="muted">
                  {agentsPoll.isLoading ? "Loading…" : "No agent data available."}
                </td>
              </tr>
            ) : (
              agents
                .slice()
                .sort((a, b) => String(a.name).localeCompare(String(b.name)))
                .map((a) => {
                  const st = getAgentState(a);
                  const isExpectedOffline = st === "OFFLINE" && String(a.name) === "execution-agent";
                  const shownState = isExpectedOffline ? "OFFLINE (expected)" : st;
                  const last = getAgentLastUpdated(a);
                  const age = last ? Date.now() - last.getTime() : null;
                  return (
                    <tr key={String(a.name)}>
                      <td className="mono">
                        <Link to={`/agents/${encodeURIComponent(String(a.name))}`}>{String(a.name)}</Link>
                      </td>
                      <td className="hide-sm muted">{a.kind ? String(a.kind) : "—"}</td>
                      <td>
                        <Badge state={st}>{shownState}</Badge>
                      </td>
                      <td className="muted">{a.summary ? String(a.summary) : "—"}</td>
                      <td className="hide-sm mono">{formatIso(last)}</td>
                      <td className="mono">{formatAgeMs(age)}</td>
                    </tr>
                  );
                })
            )}
          </tbody>
        </table>
      </div>

      <div className="card" style={{ gridColumn: "span 7" }}>
        <h2>Recent events</h2>
        <table className="table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Agent</th>
              <th>Summary</th>
            </tr>
          </thead>
          <tbody>
            {events.length === 0 ? (
              <tr>
                <td colSpan={3} className="muted">
                  {eventsPoll.isLoading ? "Loading…" : "No recent events available."}
                </td>
              </tr>
            ) : (
              events.slice(0, 10).map((e, idx) => {
                const ts = getEventTs(e);
                const agent = e.agent || e.agent_name || "—";
                const summary = e.summary || e.message || e.type || e.kind || "—";
                return (
                  <tr key={e.id || `${String(agent)}-${idx}`}>
                    <td className="mono">{ts ? ts.toISOString() : "—"}</td>
                    <td className="mono">{String(agent)}</td>
                    <td className="muted">{String(summary)}</td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      <div className="card" style={{ gridColumn: "span 5" }}>
        <h2>Last deploy report</h2>
        <div className="muted" style={{ marginBottom: 8 }}>
          Rendered markdown from Mission Control.
        </div>
        <div className="mono" style={{ whiteSpace: "pre-wrap", fontSize: 12, maxHeight: 240, overflow: "auto" }}>
          {(deployPoll.data || "").trim().slice(0, 800) || (deployPoll.isLoading ? "Loading…" : "No deploy report data.")}
          {(deployPoll.data || "").length > 800 ? "\n\n… (truncated)" : ""}
        </div>
        <div style={{ marginTop: 10 }}>
          <Link to="/reports/deploy">Open deploy report →</Link>
        </div>
      </div>
    </div>
  );
}

