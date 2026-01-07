import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

type ListenerStatus = "idle" | "connecting" | "connected" | "error";

export interface AccountState {
  equity: number;
  buying_power: number;
  cash: number;
  updated_at_ms: number | null;
  hasWarmCache: boolean;

  hasHydrated: boolean;
  listenerStatus: ListenerStatus;
  listenerError: string | null;

  setHasHydrated: (v: boolean) => void;
  setListenerState: (next: { status: ListenerStatus; error?: string | null }) => void;
  setAccount: (data: unknown, updatedAtMs?: number | null) => void;

  /**
   * Placeholder for a future real-time listener (e.g., Firestore).
   * For now, it just marks the listener as connected in a read-only way.
   */
  startAccountListener: (tenantId: string) => void;
  stopAccountListener: () => void;
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

function pickNumber(raw: Record<string, unknown>, ...keys: string[]): number | null {
  for (const k of keys) {
    const n = coerceNumber(raw[k]);
    if (n !== null) return n;
  }
  return null;
}

export const useAccountStore = create<AccountState>()(
  persist(
    (set, get) => ({
      equity: 0,
      buying_power: 0,
      cash: 0,
      updated_at_ms: null,
      hasWarmCache: false,

      hasHydrated: false,
      listenerStatus: "idle",
      listenerError: null,

      setHasHydrated: (v) => set({ hasHydrated: v }),
      setListenerState: (next) =>
        set({
          listenerStatus: next.status,
          listenerError: typeof next.error === "string" ? next.error : next.error ?? null,
        }),

      setAccount: (data: unknown, updatedAtMs?: number | null) => {
        const raw = (data && typeof data === "object" ? (data as Record<string, unknown>) : {}) as Record<
          string,
          unknown
        >;

        set((prev) => ({
          equity: pickNumber(raw, "equity") ?? prev.equity,
          buying_power: pickNumber(raw, "buying_power", "buyingPower") ?? prev.buying_power,
          cash: pickNumber(raw, "cash", "cash_balance", "cashBalance", "settled_cash", "settledCash") ?? prev.cash,
          updated_at_ms: typeof updatedAtMs === "number" && Number.isFinite(updatedAtMs) ? updatedAtMs : prev.updated_at_ms,
          hasWarmCache: true,
        }));
      },

      startAccountListener: (tenantId: string) => {
        if (!tenantId || typeof tenantId !== "string") return;
        // No-op listener for now: mark connected to avoid “loading” flicker.
        get().setListenerState({ status: "connected", error: null });
      },

      stopAccountListener: () => {
        set({ listenerStatus: "idle", listenerError: null });
      },
    }),
    {
      name: "alpaca-account-cache",
      version: 1,
      storage: createJSONStorage(() => (typeof window !== "undefined" ? window.localStorage : undefined)),
      partialize: (s) => ({
        equity: s.equity,
        buying_power: s.buying_power,
        cash: s.cash,
        updated_at_ms: s.updated_at_ms,
        hasWarmCache: s.hasWarmCache,
      }),
      onRehydrateStorage: () => (state, err) => {
        if (err) console.error("Failed to rehydrate account cache:", err);
        state?.setHasHydrated(true);
      },
    },
  ),
);

