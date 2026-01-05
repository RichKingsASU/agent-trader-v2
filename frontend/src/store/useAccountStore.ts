import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

const WARM_CACHE_KEY = "alpaca-account-cache";

type ListenerStatus = "idle" | "connecting" | "connected" | "error";

export interface AccountState {
  equity: number;
  buying_power: number;
  cash: number;
  updated_at_ms: number | null;
  hasWarmCache: boolean;

  // Hydration + listener health (helps avoid UI flicker / resets)
  hasHydrated: boolean;
  listenerStatus: ListenerStatus;
  listenerError: string | null;

  setHasHydrated: (v: boolean) => void;
  setListenerState: (next: { status: ListenerStatus; error?: string | null }) => void;
  setAccount: (data: unknown, updatedAtMs?: number | null) => void;

  startAccountListener: (tenantId: string) => void;
  stopAccountListener: () => void;
}

let unsubscribeAccount: Unsubscribe | null = null;
let listeningTenantId: string | null = null;

function coerceNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const s = value.trim();
    if (!s) return null;
    const normalized = s.replaceAll(",", "");
    const n = Number(normalized);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function coerceDateMs(value: unknown): number | null {
  if (!value) return null;
  if (value instanceof Date && Number.isFinite(value.getTime())) return value.getTime();
  if (typeof value === "number" && Number.isFinite(value)) {
    const ms = value < 10_000_000_000 ? value * 1000 : value;
    return Number.isFinite(ms) ? ms : null;
  }
  if (typeof value === "string") {
    const t = Date.parse(value);
    return Number.isFinite(t) ? t : null;
  }
  if (typeof value === "object" && value !== null) {
    const asObj = value as { toDate?: unknown; seconds?: unknown };
    if (typeof asObj.toDate === "function") {
      try {
        const d = (asObj.toDate as () => unknown)();
        return d instanceof Date && Number.isFinite(d.getTime()) ? d.getTime() : null;
      } catch {
        return null;
      }
    }
    if (typeof asObj.seconds === "number") {
      const ms = asObj.seconds * 1000;
      return Number.isFinite(ms) ? ms : null;
    }
  }
  return null;
}

function pickNumber(raw: Record<string, unknown>, ...keys: string[]): number | null {
  for (const k of keys) {
    const v = parseAlpacaNumber(raw[k]);
    if (v !== null) return v;
  }
  return null;
}

function safeReadWarmCache(): Pick<AccountState, "equity" | "buying_power" | "cash" | "updated_at_ms" | "hasWarmCache"> {
  if (typeof window === "undefined") {
    return { equity: 0, buying_power: 0, cash: 0, updated_at_ms: null, hasWarmCache: false };
  }

  try {
    const raw = window.localStorage.getItem(WARM_CACHE_KEY);
    if (!raw) return { equity: 0, buying_power: 0, cash: 0, updated_at_ms: null, hasWarmCache: false };

        if (!isZeroish) {
          lastGood[field] = parsed;
          lastGoodAt[field] = now;
          return parsed;
        }

    const equity = parseAlpacaNumber(state.equity) ?? 0;
    const buying_power = parseAlpacaNumber(state.buying_power) ?? 0;
    const cash = parseAlpacaNumber(state.cash) ?? 0;
    const updated_at_ms = coerceDateMs(state.updated_at_ms ?? state.updated_at ?? state.updatedAt ?? state.syncedAt) ?? null;

    return { equity, buying_power, cash, updated_at_ms, hasWarmCache: true };
  } catch {
    return { equity: 0, buying_power: 0, cash: 0, updated_at_ms: null, hasWarmCache: false };
  }
}

      const stop = () => {
        if (unsubscribeAccount) {
          unsubscribeAccount();
          unsubscribeAccount = null;
        }
        listeningTenantId = null;
        set({ listenerStatus: "idle", listenerError: null });
      };

      return {
        equity: boot.equity,
        buying_power: boot.buying_power,
        cash: boot.cash,
        updated_at_ms: boot.updated_at_ms,
        hasWarmCache: boot.hasWarmCache,

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

          // Do NOT overwrite a cached value with null/undefined.
          set((prev) => ({
            equity: pickNumber(raw, "equity") ?? prev.equity,
            buying_power: pickNumber(raw, "buying_power", "buyingPower") ?? prev.buying_power,
            // Back-compat: some docs store settled_cash/cash_balance/etc.
            cash:
              pickNumber(raw, "cash", "cash_balance", "cashBalance", "settled_cash", "settledCash") ?? prev.cash,
            updated_at_ms:
              coerceDateMs(
                raw.updated_at_ms ??
                  raw.syncedAt ??
                  raw.updated_at ??
                  raw.updatedAt ??
                  raw.updated_at_iso ??
                  raw.updatedAtIso ??
                  (raw.raw && typeof raw.raw === "object"
                    ? (raw.raw as Record<string, unknown>).syncedAt ??
                      (raw.raw as Record<string, unknown>).updated_at ??
                      (raw.raw as Record<string, unknown>).updatedAt ??
                      (raw.raw as Record<string, unknown>).updated_at_iso ??
                      (raw.raw as Record<string, unknown>).updatedAtIso
                    : undefined),
              ) ?? prev.updated_at_ms,
          }));
        },

        startAccountListener: (tenantId: string) => {
          if (!tenantId || typeof tenantId !== "string") return;
          if (unsubscribeAccount && listeningTenantId === tenantId) return;

          stop();
          listeningTenantId = tenantId;
          set({ listenerStatus: "connecting", listenerError: null });

          // Global snapshot produced by backend ingest:
          // listen to `alpacaAccounts/snapshot` (non-tenant-scoped).
          const ref = doc(db, "alpacaAccounts", "snapshot");
          unsubscribeAccount = onSnapshot(
            ref,
            (snap) => {
              if (snap.exists()) {
                get().setAccount(snap.data(), coerceDateMs(snap.updateTime) ?? null);
              }
              set({ listenerStatus: "connected", listenerError: null });
            },
            (err) => {
              console.error("Account snapshot listener error:", err);
              set({
                listenerStatus: "error",
                listenerError: typeof (err as any)?.message === "string" ? (err as any).message : "Listener error",
              });
            },
          );
        },

        stopAccountListener: () => stop(),
      };
    },
    {
      name: WARM_CACHE_KEY,
      version: 2,
      storage: createJSONStorage(() => (typeof window !== "undefined" ? window.localStorage : undefined)),
      partialize: (s) => ({ equity: s.equity, buying_power: s.buying_power, cash: s.cash, updated_at_ms: s.updated_at_ms }),
      onRehydrateStorage: () => (state, err) => {
        if (err) {
          console.error("Failed to rehydrate alpaca account cache:", err);
        }
        state?.setHasHydrated(true);
      },
    },
  ),
);

