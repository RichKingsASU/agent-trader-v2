import * as React from "react";
import type { IngestMode, KillSwitchMode, OpsSignalsState } from "@/state/opsSignalsModel";

type OpsSignalsAction =
  | {
      type: "HYDRATE_FROM_BACKEND";
      // TODO(wiring): replace with strongly-typed payload from backend contract.
      payload: Partial<OpsSignalsState>;
    }
  | { type: "LOCAL_SET_KILL_SWITCH_MODE"; mode: KillSwitchMode; reason?: string }
  | { type: "LOCAL_SET_INGEST_MODE"; mode: IngestMode; reason?: string }
  | { type: "LOCAL_SET_LAST_DATA_AT"; lastDataAtUtc: string | null };

function initialState(): OpsSignalsState {
  const now = Date.now();
  return {
    killSwitch: {
      mode: "NORMAL",
      source: "local_dev",
      lastChangedAtUtc: new Date(now - 15 * 60_000).toISOString(),
      changedBy: "system",
      reason: "UI-only mock state (not wired)",
    },
    ingest: {
      mode: "ACTIVE",
      source: "local_dev",
      sinceUtc: new Date(now - 2 * 60 * 60_000).toISOString(),
      reason: null,
    },
    freshness: {
      source: "local_dev",
      lastDataAtUtc: new Date(now - 70_000).toISOString(),
      thresholds: {
        warnAfterMs: 2 * 60_000,
        staleAfterMs: 6 * 60_000,
      },
    },
  };
}

function reducer(state: OpsSignalsState, action: OpsSignalsAction): OpsSignalsState {
  switch (action.type) {
    case "HYDRATE_FROM_BACKEND": {
      // TODO(wiring): ensure per-field source attribution and monotonic timestamps.
      return {
        ...state,
        ...action.payload,
        killSwitch: { ...state.killSwitch, ...(action.payload.killSwitch || {}) },
        ingest: { ...state.ingest, ...(action.payload.ingest || {}) },
        freshness: { ...state.freshness, ...(action.payload.freshness || {}) },
      };
    }
    case "LOCAL_SET_KILL_SWITCH_MODE": {
      const nowUtc = new Date().toISOString();
      return {
        ...state,
        killSwitch: {
          ...state.killSwitch,
          source: "local_dev",
          mode: action.mode,
          lastChangedAtUtc: nowUtc,
          reason: action.reason ?? state.killSwitch.reason,
          changedBy: "local_user",
        },
      };
    }
    case "LOCAL_SET_INGEST_MODE": {
      const nowUtc = new Date().toISOString();
      return {
        ...state,
        ingest: {
          ...state.ingest,
          source: "local_dev",
          mode: action.mode,
          sinceUtc: nowUtc,
          reason: action.reason ?? state.ingest.reason,
        },
      };
    }
    case "LOCAL_SET_LAST_DATA_AT": {
      return { ...state, freshness: { ...state.freshness, source: "local_dev", lastDataAtUtc: action.lastDataAtUtc } };
    }
    default: {
      const _exhaustive: never = action;
      return state;
    }
  }
}

const OpsSignalsCtx = React.createContext<{ state: OpsSignalsState; dispatch: React.Dispatch<OpsSignalsAction> } | null>(
  null,
);

export function OpsSignalsProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = React.useReducer(reducer, undefined, initialState);
  return <OpsSignalsCtx.Provider value={{ state, dispatch }}>{children}</OpsSignalsCtx.Provider>;
}

export function useOpsSignals() {
  const ctx = React.useContext(OpsSignalsCtx);
  if (!ctx) throw new Error("useOpsSignals must be used within OpsSignalsProvider");
  return ctx;
}

