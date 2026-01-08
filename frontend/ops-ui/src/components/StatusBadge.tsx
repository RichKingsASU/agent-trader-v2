import * as React from "react";
import { normalizeStatus } from "@/firestore/normalize";

function clsForStatus(status: string): string {
  const s = normalizeStatus(status);
  if (s === "OK" || s === "HEALTHY" || s === "RUNNING") return "ok";
  if (s === "DEGRADED" || s === "WARN" || s === "WARNING") return "degraded";
  if (s === "HALTED" || s === "STOPPED") return "halted";
  if (s === "OFFLINE" || s === "DOWN" || s === "ERROR") return "offline";
  return "unknown";
}

export function StatusBadge({ status }: { status: string }) {
  const s = normalizeStatus(status);
  return <span className={`badge ${clsForStatus(s)}`}>{s}</span>;
}

