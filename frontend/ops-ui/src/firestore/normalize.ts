import type { DocumentData } from "firebase/firestore";

export function normalizeStatus(raw: unknown): string {
  if (typeof raw !== "string") return "UNKNOWN";
  const s = raw.trim();
  if (!s) return "UNKNOWN";
  return s.toUpperCase();
}

export function toDateMaybe(raw: unknown): Date | null {
  if (!raw) return null;
  if (raw instanceof Date) return raw;
  // Firestore Timestamp
  if (typeof raw === "object" && raw !== null && "toDate" in raw && typeof (raw as { toDate: unknown }).toDate === "function") {
    try {
      return (raw as { toDate: () => Date }).toDate();
    } catch {
      return null;
    }
  }
  if (typeof raw === "number") {
    const d = new Date(raw);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  if (typeof raw === "string") {
    const d = new Date(raw);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  return null;
}

export function getString(obj: DocumentData, path: string[]): string | null {
  let cur: unknown = obj;
  for (const key of path) {
    if (!cur || typeof cur !== "object") return null;
    cur = (cur as Record<string, unknown>)[key];
  }
  return typeof cur === "string" && cur.trim() ? cur : null;
}

