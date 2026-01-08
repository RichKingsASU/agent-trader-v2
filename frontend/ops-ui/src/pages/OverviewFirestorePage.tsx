import * as React from "react";
import { Link } from "react-router-dom";
import { collection, limit, onSnapshot, orderBy, query, type DocumentData } from "firebase/firestore";
import { db } from "@/firebase";
import { ErrorBanner } from "@/components/ErrorBanner";
import { StatusBadge } from "@/components/StatusBadge";
import { formatAgeMs, formatIso } from "@/utils/time";
import { getString, normalizeStatus, toDateMaybe } from "@/firestore/normalize";

type Row = { id: string; data: DocumentData };

function isOpenAlert(doc: DocumentData): boolean {
  const raw = doc.status ?? doc.state ?? doc.open;
  if (typeof raw === "boolean") return raw;
  return normalizeStatus(raw) === "OPEN";
}

function serviceHeartbeatAt(d: DocumentData): Date | null {
  return (
    toDateMaybe(d.heartbeat_at) ||
    toDateMaybe(d.last_heartbeat_at) ||
    toDateMaybe(d.heartbeatAt) ||
    toDateMaybe(d.heartbeat?.ts) ||
    toDateMaybe(d.heartbeat?.at) ||
    null
  );
}

function serviceLastError(d: DocumentData): string | null {
  return (
    getString(d, ["last_error", "message"]) ||
    getString(d, ["lastError", "message"]) ||
    (typeof d.last_error === "string" ? d.last_error : null) ||
    (typeof d.lastError === "string" ? d.lastError : null) ||
    null
  );
}

function serviceVersion(d: DocumentData): string | null {
  return (
    getString(d, ["version"]) ||
    getString(d, ["build", "version"]) ||
    getString(d, ["build", "git_sha"]) ||
    getString(d, ["build", "gitSha"]) ||
    getString(d, ["git_sha"]) ||
    getString(d, ["gitSha"]) ||
    null
  );
}

export function OverviewFirestorePage() {
  const [services, setServices] = React.useState<Row[]>([]);
  const [pipelines, setPipelines] = React.useState<Row[]>([]);
  const [alerts, setAlerts] = React.useState<Row[]>([]);
  const [error, setError] = React.useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = React.useState<Date | null>(null);

  React.useEffect(() => {
    if (!db) {
      setError("Firestore is not initialized (missing Firebase config).");
      return;
    }

    const unsubscribers: Array<() => void> = [];

    try {
      const servicesQ = query(collection(db, "ops_services"), orderBy("updated_at", "desc"), limit(50));
      unsubscribers.push(
        onSnapshot(
          servicesQ,
          (snap) => {
            setServices(snap.docs.map((d) => ({ id: d.id, data: d.data() })));
            setLastUpdated(new Date());
          },
          (e) => setError(e instanceof Error ? e.message : String(e)),
        ),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }

    try {
      const pipelinesQ = query(collection(db, "ingest_pipelines"), orderBy("updated_at", "desc"), limit(50));
      unsubscribers.push(
        onSnapshot(
          pipelinesQ,
          (snap) => {
            setPipelines(snap.docs.map((d) => ({ id: d.id, data: d.data() })));
            setLastUpdated(new Date());
          },
          (e) => setError(e instanceof Error ? e.message : String(e)),
        ),
      );
    } catch (e) {
      // Optional; collection may not exist yet.
    }

    try {
      const alertsQ = query(collection(db, "ops_alerts"), orderBy("created_at", "desc"), limit(50));
      unsubscribers.push(
        onSnapshot(
          alertsQ,
          (snap) => {
            setAlerts(snap.docs.map((d) => ({ id: d.id, data: d.data() })));
            setLastUpdated(new Date());
          },
          (e) => setError(e instanceof Error ? e.message : String(e)),
        ),
      );
    } catch (e) {
      // Optional; collection may not exist yet.
    }

    return () => unsubscribers.forEach((u) => u());
  }, []);

  const openAlerts = alerts.filter((a) => isOpenAlert(a.data));

  return (
    <div className="grid">
      <div style={{ gridColumn: "span 12" }}>
        {error ? <ErrorBanner message={error} /> : null}
        <div className="meta" style={{ marginTop: 8 }}>
          Last updated: <span className="mono">{formatIso(lastUpdated)}</span>
        </div>
      </div>

      <div className="card" style={{ gridColumn: "span 12" }}>
        <h2>Ops services</h2>
        <table className="table">
          <thead>
            <tr>
              <th>Service</th>
              <th>Status</th>
              <th className="hide-sm">Version</th>
              <th className="hide-sm">Heartbeat</th>
              <th>Heartbeat age</th>
              <th>Last error</th>
            </tr>
          </thead>
          <tbody>
            {services.length === 0 ? (
              <tr>
                <td colSpan={6} className="muted">
                  No services found in <span className="mono">ops_services</span>.
                </td>
              </tr>
            ) : (
              services.map((s) => {
                const name = getString(s.data, ["name"]) || getString(s.data, ["service_name"]) || s.id;
                const status = normalizeStatus(s.data.status ?? s.data.state ?? "UNKNOWN");
                const hb = serviceHeartbeatAt(s.data);
                const ageMs = hb ? Date.now() - hb.getTime() : null;
                const version = serviceVersion(s.data);
                const lastErr = serviceLastError(s.data);
                return (
                  <tr key={s.id}>
                    <td className="mono">
                      <Link to={`/services/${encodeURIComponent(s.id)}`}>{name}</Link>
                    </td>
                    <td>
                      <StatusBadge status={status} />
                    </td>
                    <td className="hide-sm mono">{version || "—"}</td>
                    <td className="hide-sm mono">{hb ? hb.toISOString() : "—"}</td>
                    <td className="mono">{formatAgeMs(ageMs)}</td>
                    <td className="muted">{lastErr || "—"}</td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      <div className="card" style={{ gridColumn: "span 7" }}>
        <h2>Ingest pipelines</h2>
        <table className="table">
          <thead>
            <tr>
              <th>Pipeline</th>
              <th>Status</th>
              <th>Lag</th>
              <th>Throughput</th>
            </tr>
          </thead>
          <tbody>
            {pipelines.length === 0 ? (
              <tr>
                <td colSpan={4} className="muted">
                  No pipelines found in <span className="mono">ingest_pipelines</span>.
                </td>
              </tr>
            ) : (
              pipelines.map((p) => {
                const name = getString(p.data, ["name"]) || getString(p.data, ["pipeline_name"]) || p.id;
                const status = normalizeStatus(p.data.status ?? p.data.state ?? "UNKNOWN");
                const lag = p.data.lag_seconds ?? p.data.lag_s ?? p.data.lag;
                const tput = p.data.throughput_per_min ?? p.data.throughput ?? p.data.events_per_min;
                return (
                  <tr key={p.id}>
                    <td className="mono">{name}</td>
                    <td>
                      <StatusBadge status={status} />
                    </td>
                    <td className="mono">{typeof lag === "number" ? `${lag.toFixed(0)}s` : lag ? String(lag) : "—"}</td>
                    <td className="mono">{typeof tput === "number" ? `${tput.toFixed(2)}/min` : tput ? String(tput) : "—"}</td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
        <div style={{ marginTop: 10 }}>
          <Link to="/ingest">Open ingest health →</Link>
        </div>
      </div>

      <div className="card" style={{ gridColumn: "span 5" }}>
        <h2>Open alerts</h2>
        <table className="table">
          <thead>
            <tr>
              <th>When</th>
              <th>Severity</th>
              <th>Summary</th>
            </tr>
          </thead>
          <tbody>
            {openAlerts.length === 0 ? (
              <tr>
                <td colSpan={3} className="muted">
                  No open alerts in <span className="mono">ops_alerts</span>.
                </td>
              </tr>
            ) : (
              openAlerts.slice(0, 20).map((a) => {
                const created = toDateMaybe(a.data.created_at) || toDateMaybe(a.data.ts) || toDateMaybe(a.data.createdAt);
                const ageMs = created ? Date.now() - created.getTime() : null;
                const sev = normalizeStatus(a.data.severity ?? a.data.level ?? "—");
                const summary =
                  getString(a.data, ["summary"]) ||
                  getString(a.data, ["message"]) ||
                  getString(a.data, ["title"]) ||
                  a.id;
                return (
                  <tr key={a.id}>
                    <td className="mono">{formatAgeMs(ageMs)}</td>
                    <td className="mono">{sev}</td>
                    <td className="muted">{summary}</td>
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

