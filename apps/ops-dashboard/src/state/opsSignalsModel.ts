// UI/state model for safety + ingest + freshness signals.
// SAFE: UI-only. Do not wire to backend here.

export type SignalHealth = "OK" | "WARNING" | "STALE" | "UNKNOWN";

// Global kill-switch: when active, execution is expected to stop (or refuse new orders).
export type KillSwitchMode = "NORMAL" | "KILL_ACTIVE" | "UNKNOWN";

// Ingest pipeline: when paused, market data/backfills should stop advancing.
export type IngestMode = "ACTIVE" | "PAUSED" | "UNKNOWN";

export type SignalSource =
  | "unknown"
  | "local_dev"
  // TODO(wiring): add concrete sources, e.g. "mission_control", "firestore", "k8s_configmap", "cloud_run_env".
  | string;

export interface KillSwitchState {
  mode: KillSwitchMode;
  source: SignalSource;
  lastChangedAtUtc: string | null;
  changedBy: string | null;
  reason: string | null;
}

export interface IngestState {
  mode: IngestMode;
  source: SignalSource;
  sinceUtc: string | null;
  reason: string | null;
}

export interface FreshnessConfig {
  // If age exceeds `warnAfterMs`, show a warning.
  warnAfterMs: number;
  // If age exceeds `staleAfterMs`, show a stale/critical warning.
  staleAfterMs: number;
}

export interface DataFreshnessState {
  source: SignalSource;
  // The UI can track multiple clocks (last tick, last bar, last ingest event, etc.).
  // Start with one "primary" timestamp; we can extend later without breaking the model.
  lastDataAtUtc: string | null;
  thresholds: FreshnessConfig;
}

export interface OpsSignalsState {
  killSwitch: KillSwitchState;
  ingest: IngestState;
  freshness: DataFreshnessState;
}

export function parseUtcMs(isoUtc: string | null): number | null {
  if (!isoUtc) return null;
  const ms = Date.parse(isoUtc);
  return Number.isFinite(ms) ? ms : null;
}

export function deriveFreshnessHealth(nowMs: number, lastDataAtUtc: string | null, cfg: FreshnessConfig) {
  const lastMs = parseUtcMs(lastDataAtUtc);
  if (lastMs == null) return { health: "UNKNOWN" as const, ageMs: null as number | null };
  const ageMs = Math.max(0, nowMs - lastMs);
  const health: SignalHealth = ageMs >= cfg.staleAfterMs ? "STALE" : ageMs >= cfg.warnAfterMs ? "WARNING" : "OK";
  return { health, ageMs };
}

export function formatDurationMs(ms: number | null): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms}ms`;
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

