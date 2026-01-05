import { useMemo } from "react";
import { useAccountStore } from "@/store/useAccountStore";

// This interface remains compatible with the AccountPanel component
export interface AlpacaAccount {
  equity: number;
  buying_power: number;
  cash?: number;
  day_pnl_pct?: number; // Corresponds to day_change (may be absent)
  [key: string]: unknown; // Allow other properties from Firestore
}

export const useAgentTrader = () => {
  const { equity, buying_power, cash, hasHydrated, listenerStatus } = useAccountStore((s) => ({
    equity: s.equity,
    buying_power: s.buying_power,
    cash: s.cash,
    hasHydrated: s.hasHydrated,
    listenerStatus: s.listenerStatus,
  }));

  const account = useMemo<AlpacaAccount>(
    () => ({
      equity,
      buying_power,
      cash,
      // day_pnl_pct is not part of the warm-cache snapshot; keep as optional.
    }),
    [equity, buying_power, cash],
  );

  const hasAnyCached = equity !== 0 || buying_power !== 0 || cash !== 0;
  const loading = !hasHydrated && !hasAnyCached && listenerStatus !== "connected";

  // The refresh function is no longer needed with a real-time listener,
  // but we keep it in the return object for API consistency if needed elsewhere.
  const refresh = () => {
    console.log("Account data is now real-time. Manual refresh is not necessary.");
  };

  return { account, loading, refresh };
};
