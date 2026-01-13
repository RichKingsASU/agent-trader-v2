import { useEffect, useMemo, useState } from "react";
import { doc, onSnapshot } from "firebase/firestore";
import { db } from "@/firebase";
import { useAuth } from "@/contexts/AuthContext";

export interface AlpacaAccountSnapshot {
  equity: number;
  buying_power: number;
  cash: number;
  updated_at_iso?: string | null;
  status?: string | null;
  raw?: unknown;
}

function coerceNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const s = value.trim();
    if (!s) return null;
    const normalized = s.replaceAll(",", "").replaceAll("$", "");
    const n = Number(normalized);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

/**
 * Subscribes to the warm-cache broker account snapshot written by the backend:
 * `users/{uid}/alpacaAccounts/snapshot`
 */
export function useAlpacaAccountSnapshot() {
  const { user } = useAuth();
  const [snapshot, setSnapshot] = useState<AlpacaAccountSnapshot | null>(null);
  const [loading, setLoading] = useState<boolean>(!!user);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!user?.uid) {
      setSnapshot(null);
      setLoading(false);
      setError(null);
      return;
    }

    setLoading(true);
    setError(null);

    const ref = doc(db, "users", user.uid, "alpacaAccounts", "snapshot");
    const unsub = onSnapshot(
      ref,
      (snap) => {
        if (!snap.exists()) {
          setSnapshot(null);
          setLoading(false);
          return;
        }
        const raw = (snap.data() ?? {}) as Record<string, unknown>;
        setSnapshot({
          equity: coerceNumber(raw.equity) ?? 0,
          buying_power: coerceNumber(raw.buying_power) ?? 0,
          cash: coerceNumber(raw.cash) ?? 0,
          updated_at_iso: typeof raw.updated_at_iso === "string" ? raw.updated_at_iso : null,
          status: typeof raw.status === "string" ? raw.status : null,
          raw: raw.raw,
        });
        setLoading(false);
      },
      (err) => {
        console.error("Failed to subscribe alpacaAccounts/snapshot:", err);
        setSnapshot(null);
        setLoading(false);
        setError(err?.message || "Failed to load account snapshot");
      },
    );

    return () => unsub();
  }, [user?.uid]);

  const updatedAt = useMemo(() => {
    const iso = snapshot?.updated_at_iso;
    if (!iso) return null;
    const t = Date.parse(iso);
    return Number.isFinite(t) ? new Date(t) : null;
  }, [snapshot?.updated_at_iso]);

  return { snapshot, loading, error, updatedAt };
}

