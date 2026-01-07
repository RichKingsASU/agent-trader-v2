import * as React from "react";
import { missionControlApi } from "@/api/client";
import type { OpsState, SafetyResponse } from "@/api/types";
import { Badge } from "@/components/Badge";
import { ErrorBanner } from "@/components/ErrorBanner";
import { usePolling } from "@/hooks/usePolling";
import { formatIso } from "@/utils/time";

function truthy(v: unknown): boolean {
  return v === true || String(v).toLowerCase() === "true" || String(v) === "1";
}

export function SafetyPage() {
  const loader = React.useCallback(async () => {
    const res = await missionControlApi.getSafety();
    return res.ok ? ({ ok: true, data: res.data } as const) : ({ ok: false, error: res.error } as const);
  }, []);

  const poll = usePolling<SafetyResponse>(loader, 10_000);
  const anyError = poll.error;

  const kill = poll.data?.kill_switch;
  const md = poll.data?.marketdata;

  return (
    <div className="grid">
      <div style={{ gridColumn: "span 12" }}>
        {anyError ? <ErrorBanner message={anyError} /> : null}
        <div className="meta" style={{ marginTop: 8 }}>
          Last refreshed: <span className="mono">{formatIso(poll.lastRefreshed)}</span>
        </div>
      </div>

      <div className="card" style={{ gridColumn: "span 12" }}>
        <h2>Safety posture</h2>
        <table className="table">
          <tbody>
            <tr>
              <th style={{ width: 240 }}>Kill switch (execution halted)</th>
              <td className="mono">
                <Badge state={truthy(kill?.execution_halted) ? "HALTED" : "OK"}>
                  {truthy(kill?.execution_halted) ? "HALTED" : "OK"}
                </Badge>{" "}
                <span className="muted">{kill?.source ? `(${kill.source})` : ""}</span>
              </td>
            </tr>
            <tr>
              <th>Marketdata (all critical fresh)</th>
              <td className="mono">
                <Badge state={md?.all_critical_fresh ? "OK" : "DEGRADED"}>{md?.all_critical_fresh ? "OK" : "DEGRADED"}</Badge>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div className="card" style={{ gridColumn: "span 12" }}>
        <h2>Marketdata agents</h2>
        <table className="table">
          <thead>
            <tr>
              <th>Agent</th>
              <th className="hide-sm">Criticality</th>
              <th>Status</th>
              <th>Freshness</th>
            </tr>
          </thead>
          <tbody>
            {(md?.agents || []).length === 0 ? (
              <tr>
                <td colSpan={4} className="muted">
                  {poll.isLoading ? "Loading…" : "No marketdata agent entries."}
                </td>
              </tr>
            ) : (
              (md?.agents || []).map((a) => {
                const online = String(a.status || "").toUpperCase() === "ONLINE";
                const ok = truthy((a.freshness || {}).ok);
                const badgeState: OpsState = !online ? "OFFLINE" : ok ? "OK" : "DEGRADED";
                const summary =
                  (a.freshness || {}).summary ||
                  (a.freshness || {}).reason ||
                  (a.freshness || {}).reason_code ||
                  (a.freshness || {}).error ||
                  "—";
                return (
                  <tr key={a.agent_name}>
                    <td className="mono">{a.agent_name}</td>
                    <td className="hide-sm muted">{a.criticality || "—"}</td>
                    <td>
                      <Badge state={badgeState}>{online ? "ONLINE" : "OFFLINE"}</Badge>
                    </td>
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

