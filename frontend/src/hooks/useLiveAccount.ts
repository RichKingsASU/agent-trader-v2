import { useEffect, useMemo } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { useAccountStore } from "@/store/useAccountStore";

export interface UseLiveAccountReturn {
  equity: number;
  buying_power: number;
  buyingPower: number; // back-compat alias
  cash: number;
  updatedAt: Date | null;
  hasCache: boolean;
  loading: boolean;
  listenerStatus: "idle" | "connecting" | "connected" | "error";
  listenerError: string | null;
}

export function useLiveAccount(): UseLiveAccountReturn {
  const { tenantId } = useAuth();
  const {
    equity,
    buying_power,
    cash,
    updated_at_ms,
    hasWarmCache,
    hasHydrated,
    listenerStatus,
    listenerError,
    startAccountListener,
    stopAccountListener,
  } = useAccountStore((s) => ({
    equity: s.equity,
    buying_power: s.buying_power,
    cash: s.cash,
    updated_at_ms: s.updated_at_ms,
    hasWarmCache: s.hasWarmCache,
    hasHydrated: s.hasHydrated,
    listenerStatus: s.listenerStatus,
    listenerError: s.listenerError,
    startAccountListener: s.startAccountListener,
    stopAccountListener: s.stopAccountListener,
  }));

  useEffect(() => {
    if (!tenantId) return;
    startAccountListener(tenantId);
    return () => stopAccountListener();
  }, [tenantId, startAccountListener, stopAccountListener]);

  const updatedAt = useMemo(() => (updated_at_ms ? new Date(updated_at_ms) : null), [updated_at_ms]);
  const hasAnyCached = equity !== 0 || buying_power !== 0 || cash !== 0;
  const hasCache = hasWarmCache || hasAnyCached;
  const loading = !hasHydrated && !hasCache && listenerStatus !== "connected";

  return {
    equity,
    buying_power,
    buyingPower: buying_power,
    cash,
    updatedAt,
    hasCache,
    loading,
    listenerStatus,
    listenerError,
  };
}

