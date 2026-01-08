import type { PropsWithChildren } from "react";
import { NavLink } from "react-router-dom";
import { app, isFirebaseConfigured } from "@/firebase";

function navClassName({ isActive }: { isActive: boolean }) {
  return isActive ? "mono" : "muted";
}

export function Layout({ children }: PropsWithChildren) {
  const projectId = app?.options?.projectId || window.__OPS_DASHBOARD_CONFIG__?.firebase?.projectId || "—";
  return (
    <div>
      <div className="topbar">
        <div className="topbar-inner">
          <div>
            <div className="brand">Firebase Ops Dashboard</div>
            <div className="meta">
              Read-only • Firestore project: <span className="mono">{projectId}</span>
              {!isFirebaseConfigured ? <span className="muted"> (not configured)</span> : null}
            </div>
          </div>
          <nav className="nav">
            <NavLink to="/" className={navClassName}>
              Overview
            </NavLink>
            <NavLink to="/ingest" className={navClassName}>
              Ingest health
            </NavLink>
          </nav>
        </div>
      </div>
      <div className="container">{children}</div>
    </div>
  );
}

