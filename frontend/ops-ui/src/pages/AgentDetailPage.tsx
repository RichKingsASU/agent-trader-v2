import * as React from "react";
import { Link, useParams } from "react-router-dom";
import { missionControlApi } from "@/api/client";
import type { Agent, AgentDetailResponse, Event, MissionControlEventsResponse } from "@/api/types";
import { ErrorBanner } from "@/components/ErrorBanner";
import { JsonBlock } from "@/components/JsonBlock";
import { usePolling } from "@/hooks/usePolling";
import { agentCriticality, agentKind, agentLastPollAt, agentName, agentOpsState } from "@/utils/agents";
import { formatIso, parseTimestamp } from "@/utils/time";

function unpackEvents(payload: MissionControlEventsResponse): Event[] {
  return Array.isArray(payload) ? payload : payload.events || [];
}

function getEventTs(e: Event): Date | null {
  return parseTimestamp(e.ts) || parseTimestamp(e.timestamp) || null;
}

function eventAgentName(e: Event): string | null {
  const a = e.agent || e.agent_name;
  return a ? String(a) : null;
}

export function AgentDetailPage() {
  const params = useParams();
  const name = params.name ? decodeURIComponent(params.name) : "";

  const agentLoader = React.useCallback(async () => {
    if (!name) return { ok: true, data: null } as const;
    const res = await missionControlApi.getAgent(name);
    return res.ok ? ({ ok: true, data: res.data } as const) : ({ ok: false, error: res.error } as const);
  }, [name]);

  const eventsLoader = React.useCallback(async () => {
    const res = await missionControlApi.listRecentEvents();
    return res.ok ? ({ ok: true, data: unpackEvents(res.data) } as const) : ({ ok: false, error: res.error } as const);
  }, []);

  const agentPoll = usePolling<AgentDetailResponse | null>(agentLoader, 10_000);
  const eventsPoll = usePolling(eventsLoader, 10_000);

  const anyError = agentPoll.error || eventsPoll.error;
  const lastRefreshed = agentPoll.lastRefreshed || eventsPoll.lastRefreshed;

  const agent = agentPoll.data?.agent || null;
  const recentForAgent = (eventsPoll.data || [])
    .filter((e) => eventAgentName(e) === (agent ? agentName(agent) : name))
    .slice(0, 50);

  const st = agent ? agentOpsState(agent) : "UNKNOWN";
  const lastPollAt = agent ? agentLastPollAt(agent) : null;

  return (
    <div className="grid">
      <div style={{ gridColumn: "span 12" }}>
        <div style={{ marginBottom: 8 }}>
          <Link to="/">← Overview</Link>
        </div>
        {anyError ? <ErrorBanner message={anyError} /> : null}
        <div className="meta" style={{ marginTop: 8 }}>
          Last refreshed: <span className="mono">{formatIso(lastRefreshed)}</span>
        </div>
      </div>

      <div className="card" style={{ gridColumn: "span 12" }}>
        <h2>Agent</h2>
        {!name ? (
          <div className="muted">Missing agent name.</div>
        ) : !agent ? (
          <div className="muted">{agentPoll.isLoading ? "Loading…" : `Agent not found: ${name}`}</div>
        ) : (
          <table className="table">
            <tbody>
              <tr>
                <th style={{ width: 220 }}>Name</th>
                <td className="mono">{agentName(agent)}</td>
              </tr>
              <tr>
                <th>Kind</th>
                <td className="mono">{agentKind(agent)}</td>
              </tr>
              <tr>
                <th>Criticality</th>
                <td className="mono">{agentCriticality(agent)}</td>
              </tr>
              <tr>
                <th>State</th>
                <td className="mono">{st}</td>
              </tr>
              <tr>
                <th>Service DNS</th>
                <td className="mono">{agent.service_dns ? String(agent.service_dns) : "—"}</td>
              </tr>
              <tr>
                <th>Last poll</th>
                <td className="mono">{formatIso(lastPollAt)}</td>
              </tr>
              <tr>
                <th>Expected endpoints</th>
                <td className="mono">{Array.isArray(agent.expected_endpoints) ? agent.expected_endpoints.join(", ") : "—"}</td>
              </tr>
              <tr>
                <th>Healthz</th>
                <td className="mono">
                  {agent.healthz ? (agent.healthz.ok ? "ok" : `fail (${agent.healthz.error || "unknown"})`) : "—"}
                </td>
              </tr>
              <tr>
                <th>/ops/status</th>
                <td className="mono">
                  {agent.ops_status ? (agent.ops_status.ok ? "ok" : `fail (${agent.ops_status.error || "unknown"})`) : "—"}
                </td>
              </tr>
            </tbody>
          </table>
        )}
      </div>

      <div className="card" style={{ gridColumn: "span 12" }}>
        <h2>Raw /ops/status (redacted)</h2>
        <div className="muted" style={{ marginBottom: 10 }}>
          Sensitive keys (token/secret/api_key/password) are redacted client-side.
        </div>
        {agent ? <JsonBlock value={agent.raw_ops_status ?? agent} /> : <div />}
      </div>

      <div className="card" style={{ gridColumn: "span 12" }}>
        <h2>Recent poll outcomes (last 50)</h2>
        <table className="table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Type</th>
              <th>Outcome</th>
              <th>Summary</th>
            </tr>
          </thead>
          <tbody>
            {recentForAgent.length === 0 ? (
              <tr>
                <td colSpan={4} className="muted">
                  {eventsPoll.isLoading ? "Loading…" : "No recent events for this agent."}
                </td>
              </tr>
            ) : (
              recentForAgent.map((e, idx) => {
                const ts = getEventTs(e);
                const type = e.type || e.kind || "—";
                const outcome = e.outcome || e.level || "—";
                const summary = e.summary || e.message || "—";
                return (
                  <tr key={e.id || `${idx}`}>
                    <td className="mono">{ts ? ts.toISOString() : "—"}</td>
                    <td className="mono">{String(type)}</td>
                    <td className="mono">{String(outcome)}</td>
                    <td className="muted">{String(summary)}</td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

