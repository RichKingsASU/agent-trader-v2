import type { OpsState } from "@/api/types";

export function Badge({ state, children }: { state: OpsState; children: string }) {
  const cls =
    state === "OK"
      ? "ok"
      : state === "DEGRADED"
        ? "degraded"
        : state === "HALTED"
          ? "halted"
          : state === "MARKET_CLOSED"
            ? "market_closed"
          : state === "OFFLINE"
            ? "offline"
            : "unknown";
  return <span className={`badge ${cls}`}>{children}</span>;
}

