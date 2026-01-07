import type { PropsWithChildren } from "react";
import { NavLink } from "react-router-dom";
import { missionControlApi } from "@/api/client";

function navClassName({ isActive }: { isActive: boolean }) {
  return isActive ? "mono" : "muted";
}

export function Layout({ children }: PropsWithChildren) {
  const base = missionControlApi.getBaseUrl();
  return (
    <div>
      <div className="topbar">
        <div className="topbar-inner">
          <div>
            <div className="brand">AgentTrader Ops UI</div>
            <div className="meta">Read-only • Mission Control: <span className="mono">{base}</span></div>
          </div>
          <nav className="nav">
            <NavLink to="/" className={navClassName}>
              Overview
            </NavLink>
            <NavLink to="/reports/deploy" className={navClassName}>
              Deploy report
            </NavLink>
          </nav>
        </div>
      </div>
      <div className="container">{children}</div>
    </div>
  );
}

