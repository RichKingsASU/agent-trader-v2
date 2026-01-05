import { useCallback, useEffect, useState } from "react";
import { getDoc } from "firebase/firestore";

import { getFirestoreDb } from "@/lib/lovable/firebaseClient";
import { useAuth } from "@/contexts/AuthContext";
import { tenantDoc } from "@/lib/tenancy/firestore";

export type TrafficLight = "Green" | "Yellow" | "Red" | "Gray";

function getNYLocalParts(d: Date): { weekday: number; hour: number; minute: number } {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(d);

  const weekdayStr = parts.find((p) => p.type === "weekday")?.value ?? "Sun";
  const hourStr = parts.find((p) => p.type === "hour")?.value ?? "00";
  const minuteStr = parts.find((p) => p.type === "minute")?.value ?? "00";

  const weekdayMap: Record<string, number> = {
    Sun: 0,
    Mon: 1,
    Tue: 2,
    Wed: 3,
    Thu: 4,
    Fri: 5,
    Sat: 6,
  };

  return {
    weekday: weekdayMap[weekdayStr] ?? 0,
    hour: Number(hourStr),
    minute: Number(minuteStr),
  };
}

function checkMarketHours(): boolean {
  const now = new Date();
  const ny = getNYLocalParts(now);

  // NYSE: Mon-Fri, 09:30 - 16:00 (America/New_York)
  const isWeekday = ny.weekday >= 1 && ny.weekday <= 5;
  const isAfterOpen = (ny.hour === 9 && ny.minute >= 30) || ny.hour > 9;
  const isBeforeClose = ny.hour < 16;

  return isWeekday && isAfterOpen && isBeforeClose;
}

function parseHeartbeatMs(v: unknown): number | null {
  if (!v) return null;
  // Firestore Timestamp-like
  if (typeof v === "object" && v !== null) {
    const asAny = v as any;
    if (typeof asAny.toDate === "function") {
      const d = asAny.toDate();
      if (d instanceof Date && Number.isFinite(d.getTime())) return d.getTime();
    }
    if (typeof asAny.seconds === "number") return asAny.seconds * 1000;
  }
  if (typeof v === "number" && Number.isFinite(v)) return v < 10_000_000_000 ? v * 1000 : v;
  if (typeof v === "string") {
    const t = Date.parse(v);
    return Number.isFinite(t) ? t : null;
  }
  return null;
}

function mapStatusToTrafficLight(raw: unknown, diffSec: number): TrafficLight {
  const s = typeof raw === "string" ? raw.toLowerCase() : "";
  if (s === "green" || s === "ok" || s === "healthy") return diffSec > 60 ? "Yellow" : "Green";
  if (s === "yellow" || s === "degraded") return diffSec > 300 ? "Red" : "Yellow";
  if (s === "red" || s === "error" || s === "down") return "Red";
  if (s === "gray" || s === "unknown") return "Gray";
  // Fall back on staleness-only rule.
  if (diffSec > 300) return "Red";
  if (diffSec > 60) return "Yellow";
  return "Green";
}

export const useOpsStatus = (serviceId: string) => {
  const [status, setStatus] = useState<TrafficLight>("Gray");
  const [lastSeen, setLastSeen] = useState<string>("Never");
  const { tenantId } = useAuth();

  const updateStatus = useCallback(async () => {
    const isMarketOpen = checkMarketHours();
    const db = getFirestoreDb();

    if (!db) {
      setStatus(isMarketOpen ? "Red" : "Gray");
      return;
    }
    if (!tenantId) return;

    try {
      const snap = await getDoc(tenantDoc(db, tenantId, "ops_heartbeats", serviceId));
      if (!snap.exists()) {
        setStatus(isMarketOpen ? "Red" : "Gray");
        setLastSeen("Never");
        return;
      }

      const data = snap.data() as Record<string, unknown>;
      const lastMs = parseHeartbeatMs(data.last_heartbeat ?? data.lastHeartbeat ?? data.last_seen ?? data.lastSeen);
      const now = Date.now();
      const diffSec = lastMs ? (now - lastMs) / 1000 : Number.POSITIVE_INFINITY;

      setLastSeen(lastMs ? new Date(lastMs).toISOString() : "Unknown");
      setStatus(isMarketOpen ? mapStatusToTrafficLight(data.status, diffSec) : "Gray");
    } catch {
      setStatus(isMarketOpen ? "Red" : "Gray");
    }
  }, [serviceId, tenantId]);

  useEffect(() => {
    updateStatus();
    const interval = setInterval(updateStatus, 15000); // 15s polling
    return () => clearInterval(interval);
  }, [updateStatus]);

  return { status, lastSeen };
};

