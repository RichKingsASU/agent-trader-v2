import * as React from "react";
import { Link, useParams } from "react-router-dom";
import { missionControlApi } from "@/api/client";
import type { Agent, Event, MissionControlEventsResponse } from "@/api/types";
import { ErrorBanner } from "@/components/ErrorBanner";
import { JsonBlock } from "@/components/JsonBlock";
import { usePolling } from "@/hooks/usePolling";
import { formatIso, parseTimestamp } from "@/utils/time";

function unpackEvents(payload: MissionControlEventsResponse): Event[] {
  return Array.isArray(payload) ? payload : payload.events || [];
}

function getAgentBuildFingerprint(agent: Agent): string {
  const ops = agent.ops_status;
  return ops?.git_sha || ops?.build_id || "—";
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

  const agentsLoader = React.useCallback(async () => {
    const res = await missionControlApi.getOpsStatus();
    return res.ok
      ? ({ ok: true, data: res.data.agents } as const)
      : ({ ok: false, error: res.error } as const);
  }, []);

  const eventsLoader = React.useCallback(async () => {
    const res = await missionControlApi.listRecentEvents();
    return res.ok ? ({ ok: true, data: unpackEvents(res.data) } as const) : ({ ok: false, error: res.error } as const);
  }, []);

  const agentsPoll = usePolling(agentsLoader, 10_000);
  const eventsPoll = usePolling(eventsLoader, 10_000);

  const anyError = agentsPoll.error || eventsPoll.error;
  const lastRefreshed = agentsPoll.lastRefreshed || eventsPoll.lastRefreshed;

  const agent = (agentsPoll.data || []).find((a) => String(a.agent_name) === name) || null;
  const recentForAgent = (eventsPoll.data || [])
    .filter((e) => eventAgentName(e) === name)
    .slice(0, 50);

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
          <div className="muted">{agentsPoll.isLoading ? "Loading…" : `Agent not found: ${name}`}</div>
        ) : (
          <table className="table">
            <tbody>
              <tr>
                <th style={{ width: 220 }}>Name</th>
                <td className="mono">{String(agent.agent_name)}</td>
              </tr>
              <tr>
                <th>Kind</th>
                <td className="mono">{agent.kind ? String(agent.kind) : "—"}</td>
              </tr>
              <tr>
                <th>Build fingerprint</th>
                <td className="mono">{getAgentBuildFingerprint(agent)}</td>
              </tr>
            </tbody>
          </table>
        )}
      </div>

      <div className="card" style={{ gridColumn: "span 12" }}>
        <h2>Ops status (redacted)</h2>
        <div className="muted" style={{ marginBottom: 10 }}>
          Sensitive keys (token/secret/api_key/password) are redacted client-side.
        </div>
        {agent ? <JsonBlock value={agent.raw_ops_status_redacted ?? agent.ops_status ?? agent} /> : <div />}
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

