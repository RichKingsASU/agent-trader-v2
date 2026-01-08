import * as React from "react";
import { Link, useParams } from "react-router-dom";
import { doc, onSnapshot, type DocumentData } from "firebase/firestore";
import { db } from "@/firebase";
import { ErrorBanner } from "@/components/ErrorBanner";
import { JsonBlock } from "@/components/JsonBlock";
import { StatusBadge } from "@/components/StatusBadge";
import { formatAgeMs, formatIso } from "@/utils/time";
import { getString, normalizeStatus, toDateMaybe } from "@/firestore/normalize";

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

function serviceLastError(d: DocumentData): { message: string; at: Date | null } | null {
  const msg =
    getString(d, ["last_error", "message"]) ||
    getString(d, ["lastError", "message"]) ||
    (typeof d.last_error === "string" ? d.last_error : null) ||
    (typeof d.lastError === "string" ? d.lastError : null);
  if (!msg) return null;
  const at =
    toDateMaybe(d.last_error?.at) ||
    toDateMaybe(d.last_error?.ts) ||
    toDateMaybe(d.lastError?.at) ||
    toDateMaybe(d.lastError?.ts) ||
    toDateMaybe(d.last_error_at) ||
    toDateMaybe(d.lastErrorAt) ||
    null;
  return { message: msg, at };
}

function extractLogLinks(d: DocumentData): Array<{ label: string; url: string }> {
  const out: Array<{ label: string; url: string }> = [];
  const candidates: Array<[string, unknown]> = [
    ["logs", getString(d, ["links", "logs"]) || getString(d, ["links", "logs_url"]) || d.logs_url || d.log_url],
    ["metrics", getString(d, ["links", "metrics"]) || getString(d, ["links", "grafana"]) || d.grafana_url],
    ["traces", getString(d, ["links", "traces"]) || d.traces_url],
    ["runbook", getString(d, ["links", "runbook"]) || d.runbook_url],
  ];
  for (const [label, val] of candidates) {
    const url = typeof val === "string" ? val : null;
    if (url && url.startsWith("http")) out.push({ label, url });
  }
  // Generic: links object
  if (d.links && typeof d.links === "object") {
    for (const [k, v] of Object.entries(d.links as Record<string, unknown>)) {
      if (typeof v === "string" && v.startsWith("http") && !out.some((x) => x.url === v)) out.push({ label: k, url: v });
    }
  }
  return out;
}

export function ServiceDetailPage() {
  const params = useParams();
  const serviceId = params.serviceId ? decodeURIComponent(params.serviceId) : "";

  const [docData, setDocData] = React.useState<DocumentData | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = React.useState<Date | null>(null);

  React.useEffect(() => {
    if (!db) {
      setError("Firestore is not initialized (missing Firebase config).");
      return;
    }
    if (!serviceId) {
      setError("Missing service id.");
      return;
    }
    const ref = doc(db, "ops_services", serviceId);
    const unsub = onSnapshot(
      ref,
      (snap) => {
        setDocData(snap.exists() ? snap.data() : null);
        setLastUpdated(new Date());
      },
      (e) => setError(e instanceof Error ? e.message : String(e)),
    );
    return () => unsub();
  }, [serviceId]);

  const name = docData ? getString(docData, ["name"]) || getString(docData, ["service_name"]) || serviceId : serviceId;
  const status = docData ? normalizeStatus(docData.status ?? docData.state ?? "UNKNOWN") : "UNKNOWN";
  const hb = docData ? serviceHeartbeatAt(docData) : null;
  const hbAgeMs = hb ? Date.now() - hb.getTime() : null;
  const version = docData ? serviceVersion(docData) : null;
  const lastErr = docData ? serviceLastError(docData) : null;
  const links = docData ? extractLogLinks(docData) : [];

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
        <h2>Service</h2>
        {!serviceId ? (
          <div className="muted">Missing service id.</div>
        ) : !docData ? (
          <div className="muted">
            No document found at <span className="mono">ops_services/{serviceId}</span>.
          </div>
        ) : (
          <table className="table">
            <tbody>
              <tr>
                <th style={{ width: 220 }}>Name</th>
                <td className="mono">{name}</td>
              </tr>
              <tr>
                <th>Status</th>
                <td>
                  <StatusBadge status={status} />
                </td>
              </tr>
              <tr>
                <th>Heartbeat</th>
                <td className="mono">
                  {hb ? hb.toISOString() : "—"} <span className="muted">({formatAgeMs(hbAgeMs)})</span>
                </td>
              </tr>
              <tr>
                <th>Version</th>
                <td className="mono">{version || "—"}</td>
              </tr>
              <tr>
                <th>Last error</th>
                <td className="muted">
                  {lastErr ? (
                    <>
                      <span className="mono">{lastErr.at ? lastErr.at.toISOString() : "—"}</span> — {lastErr.message}
                    </>
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
              <tr>
                <th>Links</th>
                <td>
                  {links.length === 0 ? (
                    <span className="muted">—</span>
                  ) : (
                    <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                      {links.map((l) => (
                        <a key={l.url} href={l.url} target="_blank" rel="noreferrer">
                          {l.label} →
                        </a>
                      ))}
                    </div>
                  )}
                </td>
              </tr>
            </tbody>
          </table>
        )}
      </div>

      <div className="card" style={{ gridColumn: "span 12" }}>
        <h2>Raw document</h2>
        {docData ? <JsonBlock value={docData} /> : <div />}
      </div>
    </div>
  );
}

