import * as React from "react";
import { SignalBadge } from "@/components/SignalBadge";
import { useOpsSignals } from "@/state/OpsSignalsContext";
import { deriveFreshnessHealth, formatDurationMs } from "@/state/opsSignalsModel";

function modeLabel(mode: string) {
  return mode.replace(/_/g, " ");
}

export function OpsSignalsPanel() {
  const { state, dispatch } = useOpsSignals();
  const nowMs = Date.now();
  const freshness = deriveFreshnessHealth(nowMs, state.freshness.lastDataAtUtc, state.freshness.thresholds);
  const bannerHealth = freshness.health === "STALE" ? "STALE" : freshness.health === "WARNING" ? "WARNING" : "OK";

  return (
    <>
      {bannerHealth !== "OK" ? (
        <div className={`banner ${bannerHealth === "STALE" ? "danger" : "warn"}`} style={{ gridColumn: "span 12" }}>
          <div style={{ display: "flex", gap: 10, alignItems: "center", justifyContent: "space-between", flexWrap: "wrap" }}>
            <div>
              <div style={{ fontWeight: 600 }}>Stale data warning</div>
              <div className="meta">
                Latest data age: <span className="mono">{formatDurationMs(freshness.ageMs)}</span> (thresholds: warn{" "}
                <span className="mono">{formatDurationMs(state.freshness.thresholds.warnAfterMs)}</span>, stale{" "}
                <span className="mono">{formatDurationMs(state.freshness.thresholds.staleAfterMs)}</span>)
              </div>
            </div>
            <div className="meta">
              TODO(wiring): use “last market tick / last bar / last ingest event” from backend.
            </div>
          </div>
        </div>
      ) : null}

      <div className="card" style={{ gridColumn: "span 4" }}>
        <h2>Global kill-switch</h2>
        <div className="status-row" style={{ marginBottom: 8 }}>
          <span className="status-pill">
            <SignalBadge health={state.killSwitch.mode === "KILL_ACTIVE" ? "STALE" : state.killSwitch.mode === "NORMAL" ? "OK" : "UNKNOWN"}>
              {modeLabel(state.killSwitch.mode)}
            </SignalBadge>
            <span className="meta">source: <span className="mono">{String(state.killSwitch.source)}</span></span>
          </span>
        </div>
        <div className="meta">
          Last change: <span className="mono">{state.killSwitch.lastChangedAtUtc || "—"}</span>
          {state.killSwitch.changedBy ? (
            <>
              {" "}by <span className="mono">{state.killSwitch.changedBy}</span>
            </>
          ) : null}
        </div>
        <div className="meta" style={{ marginTop: 6 }}>
          Reason: <span className="mono">{state.killSwitch.reason || "—"}</span>
        </div>
        <div style={{ marginTop: 10, display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button className="btn danger" disabled title="SAFE: UI-only (no backend wiring)">
            Engage kill-switch
          </button>
          <button className="btn" disabled title="SAFE: UI-only (no backend wiring)">
            Disengage
          </button>
          <button
            className="btn subtle"
            onClick={() =>
              dispatch({
                type: "LOCAL_SET_KILL_SWITCH_MODE",
                mode: state.killSwitch.mode === "KILL_ACTIVE" ? "NORMAL" : "KILL_ACTIVE",
                reason: "Local simulation toggle (UI-only)",
              })
            }
            title="Dev-only: toggles local UI state"
          >
            Simulate toggle (local)
          </button>
        </div>
        <div className="meta" style={{ marginTop: 10 }}>
          TODO(wiring): read/write from a single source of truth (e.g., Firestore “killswitch”, K8s ConfigMap, or Mission Control).
        </div>
      </div>

      <div className="card" style={{ gridColumn: "span 4" }}>
        <h2>Ingest</h2>
        <div className="status-row" style={{ marginBottom: 8 }}>
          <span className="status-pill">
            <SignalBadge health={state.ingest.mode === "PAUSED" ? "WARNING" : state.ingest.mode === "ACTIVE" ? "OK" : "UNKNOWN"}>
              {modeLabel(state.ingest.mode)}
            </SignalBadge>
            <span className="meta">source: <span className="mono">{String(state.ingest.source)}</span></span>
          </span>
        </div>
        <div className="meta">
          Since: <span className="mono">{state.ingest.sinceUtc || "—"}</span>
        </div>
        <div className="meta" style={{ marginTop: 6 }}>
          Reason: <span className="mono">{state.ingest.reason || "—"}</span>
        </div>
        <div style={{ marginTop: 10, display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button className="btn" disabled title="SAFE: UI-only (no backend wiring)">
            Pause ingest
          </button>
          <button className="btn" disabled title="SAFE: UI-only (no backend wiring)">
            Resume ingest
          </button>
          <button
            className="btn subtle"
            onClick={() =>
              dispatch({
                type: "LOCAL_SET_INGEST_MODE",
                mode: state.ingest.mode === "PAUSED" ? "ACTIVE" : "PAUSED",
                reason: "Local simulation toggle (UI-only)",
              })
            }
            title="Dev-only: toggles local UI state"
          >
            Simulate toggle (local)
          </button>
        </div>
        <div className="meta" style={{ marginTop: 10 }}>
          TODO(wiring): control ingest via a dedicated endpoint + auth; include “pause reason” and “who paused” fields.
        </div>
      </div>

      <div className="card" style={{ gridColumn: "span 4" }}>
        <h2>Data freshness</h2>
        <div className="status-row" style={{ marginBottom: 8 }}>
          <span className="status-pill">
            <SignalBadge health={freshness.health}>
              {freshness.health}
            </SignalBadge>
            <span className="meta">source: <span className="mono">{String(state.freshness.source)}</span></span>
          </span>
        </div>
        <div className="meta">
          Last data at (UTC): <span className="mono">{state.freshness.lastDataAtUtc || "—"}</span>
        </div>
        <div className="meta" style={{ marginTop: 6 }}>
          Age: <span className="mono">{formatDurationMs(freshness.ageMs)}</span>
        </div>
        <div className="meta" style={{ marginTop: 6 }}>
          Thresholds: warn <span className="mono">{formatDurationMs(state.freshness.thresholds.warnAfterMs)}</span>, stale{" "}
          <span className="mono">{formatDurationMs(state.freshness.thresholds.staleAfterMs)}</span>
        </div>
        <div style={{ marginTop: 10, display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button
            className="btn subtle"
            onClick={() => dispatch({ type: "LOCAL_SET_LAST_DATA_AT", lastDataAtUtc: new Date().toISOString() })}
            title="Dev-only: sets lastDataAtUtc=now (UI-only)"
          >
            Simulate fresh now
          </button>
          <button
            className="btn subtle"
            onClick={() => dispatch({ type: "LOCAL_SET_LAST_DATA_AT", lastDataAtUtc: new Date(Date.now() - 10 * 60_000).toISOString() })}
            title="Dev-only: sets lastDataAtUtc=10m ago (UI-only)"
          >
            Simulate stale
          </button>
        </div>
        <div className="meta" style={{ marginTop: 10 }}>
          TODO(wiring): decide what “fresh” means (ticks vs bars vs options chain) and surface per-feed breakdown.
        </div>
      </div>
    </>
  );
}

