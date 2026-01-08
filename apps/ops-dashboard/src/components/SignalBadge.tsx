import type { SignalHealth } from "@/state/opsSignalsModel";

export function SignalBadge({ health, children }: { health: SignalHealth; children: string }) {
  const cls = health === "OK" ? "ok" : health === "WARNING" ? "warn" : health === "STALE" ? "danger" : "unknown";
  return <span className={`badge ${cls}`}>{children}</span>;
}

