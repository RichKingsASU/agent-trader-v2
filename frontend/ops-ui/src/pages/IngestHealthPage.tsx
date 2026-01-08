import * as React from "react";
import { Link } from "react-router-dom";
import { collection, limit, onSnapshot, orderBy, query, type DocumentData } from "firebase/firestore";
import { db } from "@/firebase";
import { ErrorBanner } from "@/components/ErrorBanner";
import { StatusBadge } from "@/components/StatusBadge";
import { formatAgeMs, formatIso } from "@/utils/time";
import { getString, normalizeStatus, toDateMaybe } from "@/firestore/normalize";

type Row = { id: string; data: DocumentData };

function pipelineLastEventAt(d: DocumentData): Date | null {
  return (
    toDateMaybe(d.last_event_at) ||
    toDateMaybe(d.lastEventAt) ||
    toDateMaybe(d.last_seen_at) ||
    toDateMaybe(d.lastSeenAt) ||
    toDateMaybe(d.updated_at) ||
    toDateMaybe(d.updatedAt) ||
    null
  );
}

export function IngestHealthPage() {
  const [pipelines, setPipelines] = React.useState<Row[]>([]);
  const [error, setError] = React.useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = React.useState<Date | null>(null);

  React.useEffect(() => {
    if (!db) {
      setError("Firestore is not initialized (missing Firebase config).");
      return;
    }
    const q = query(collection(db, "ingest_pipelines"), orderBy("updated_at", "desc"), limit(200));
    const unsub = onSnapshot(
      q,
      (snap) => {
        setPipelines(snap.docs.map((d) => ({ id: d.id, data: d.data() })));
        setLastUpdated(new Date());
      },
      (e) => setError(e instanceof Error ? e.message : String(e)),
    );
    return () => unsub();
  }, []);

  return (
    <div className="grid">
      <div style={{ gridColumn: "span 12" }}>
        <div style={{ marginBottom: 8 }}>
          <Link to="/">← Overview</Link>
        </div>
        {error ? <ErrorBanner message={error} /> : null}
        <div className="meta" style={{ marginTop: 8 }}>
          Last updated: <span className="mono">{formatIso(lastUpdated)}</span>
        </div>
      </div>

      <div className="card" style={{ gridColumn: "span 12" }}>
        <h2>Ingest health</h2>
        <div className="muted" style={{ marginBottom: 10 }}>
          Read-only view of <span className="mono">ingest_pipelines</span> (realtime).
        </div>
        <table className="table">
          <thead>
            <tr>
              <th>Pipeline</th>
              <th>Status</th>
              <th>Lag</th>
              <th>Throughput</th>
              <th className="hide-sm">Last event</th>
              <th>Last event age</th>
              <th className="hide-sm">Notes</th>
            </tr>
          </thead>
          <tbody>
            {pipelines.length === 0 ? (
              <tr>
                <td colSpan={7} className="muted">
                  No pipelines found.
                </td>
              </tr>
            ) : (
              pipelines
                .slice()
                .sort((a, b) => (getString(a.data, ["name"]) || a.id).localeCompare(getString(b.data, ["name"]) || b.id))
                .map((p) => {
                  const name = getString(p.data, ["name"]) || getString(p.data, ["pipeline_name"]) || p.id;
                  const status = normalizeStatus(p.data.status ?? p.data.state ?? "UNKNOWN");
                  const lag = p.data.lag_seconds ?? p.data.lag_s ?? p.data.lag;
                  const tput = p.data.throughput_per_min ?? p.data.throughput ?? p.data.events_per_min;
                  const last = pipelineLastEventAt(p.data);
                  const ageMs = last ? Date.now() - last.getTime() : null;
                  const notes =
                    getString(p.data, ["note"]) ||
                    getString(p.data, ["notes"]) ||
                    getString(p.data, ["summary"]) ||
                    getString(p.data, ["last_error", "message"]) ||
                    (typeof p.data.last_error === "string" ? p.data.last_error : null);

                  return (
                    <tr key={p.id}>
                      <td className="mono">{name}</td>
                      <td>
                        <StatusBadge status={status} />
                      </td>
                      <td className="mono">{typeof lag === "number" ? `${lag.toFixed(0)}s` : lag ? String(lag) : "—"}</td>
                      <td className="mono">{typeof tput === "number" ? `${tput.toFixed(2)}/min` : tput ? String(tput) : "—"}</td>
                      <td className="hide-sm mono">{last ? last.toISOString() : "—"}</td>
                      <td className="mono">{formatAgeMs(ageMs)}</td>
                      <td className="hide-sm muted">{notes || "—"}</td>
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

