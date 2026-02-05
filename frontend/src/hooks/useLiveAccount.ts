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
  // Select individual items to prevent valid object reference changes from triggering re-renders
  const equity = useAccountStore((s) => s.equity);
  const buying_power = useAccountStore((s) => s.buying_power);
  const cash = useAccountStore((s) => s.cash);
  const updated_at_ms = useAccountStore((s) => s.updated_at_ms);
  const hasWarmCache = useAccountStore((s) => s.hasWarmCache);
  const hasHydrated = useAccountStore((s) => s.hasHydrated);
  const listenerStatus = useAccountStore((s) => s.listenerStatus);
  const listenerError = useAccountStore((s) => s.listenerError);
  const startAccountListener = useAccountStore((s) => s.startAccountListener);
  const stopAccountListener = useAccountStore((s) => s.stopAccountListener);

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

