import { useMemo, useState, useEffect } from "react";
import { collection, onSnapshot, query, where, QuerySnapshot, DocumentData } from "firebase/firestore";
import { db } from "@/firebase";
import { useAuth } from "@/contexts/AuthContext";
import { useMarketLiveQuotes } from "@/hooks/useMarketLiveQuotes";

export interface ShadowTrade {
  id: string;
  uid: string;
  symbol: string;
  side: "BUY" | "SELL";
  quantity: string;
  entry_price: string;
  current_price?: string;
  current_pnl?: string;
  pnl_percent?: string;
  status: "OPEN" | "CLOSED";
  created_at: any;
  last_updated?: any;
  reasoning?: string;
  allocation?: number;
}

export interface ShadowPortfolioSummary {
  totalPnL: number;
  totalPnLPercent: number;
  openPositions: number;
  totalValue: number;
}

interface UseShadowTradesReturn {
  trades: ShadowTrade[];
  summary: ShadowPortfolioSummary;
  loading: boolean;
  error: string | null;
}

/**
 * Custom hook to fetch and track shadow trades with real-time P&L updates.
 * 
 * Listens to shadowTradeHistory collection for OPEN trades for the current user.
 * Calculates total synthetic equity and P&L in real-time.
 */
export const useShadowTrades = (): UseShadowTradesReturn => {
  const { user } = useAuth();
  const [trades, setTrades] = useState<ShadowTrade[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { quotesBySymbol } = useMarketLiveQuotes({ subscribeQuotes: true, subscribeHeartbeat: false });

  useEffect(() => {
    if (!user) {
      setTrades([]);
      setLoading(false);
      return;
    }

    // User-scoped shadow trades live under: users/{uid}/shadowTradeHistory
    const shadowTradesRef = collection(db, "users", user.uid, "shadowTradeHistory");
    
    // Query OPEN shadow trades for current user
    const q = query(
      shadowTradesRef,
      where("status", "==", "OPEN")
    );

    const unsubscribe = onSnapshot(
      q,
      (snapshot: QuerySnapshot<DocumentData>) => {
        const tradesData: ShadowTrade[] = [];
        
        snapshot.forEach((doc) => {
          const data = doc.data();
          const sym = String(data.symbol || "").toUpperCase();
          const quote = quotesBySymbol[sym];
          const bid = typeof quote?.bid_price === "number" ? quote.bid_price : null;
          const ask = typeof quote?.ask_price === "number" ? quote.ask_price : null;
          const mid = bid !== null && ask !== null && bid > 0 && ask > 0 ? (bid + ask) / 2 : null;
          const mark =
            mid ??
            (typeof quote?.last_trade_price === "number" && quote.last_trade_price > 0 ? quote.last_trade_price : null) ??
            (typeof quote?.price === "number" && quote.price > 0 ? quote.price : null) ??
            null;

          tradesData.push({
            id: doc.id,
            uid: data.uid,
            symbol: sym,
            side: data.side,
            quantity: data.quantity || "0",
            entry_price: data.entry_price || "0",
            current_price: mark !== null ? String(mark) : (data.current_price || data.entry_price || "0"),
            // Prefer recalculated P&L off mark (faster refresh); fallback to stored.
            current_pnl:
              mark !== null
                ? (() => {
                    const qty = Number(data.quantity || 0) || 0;
                    const entry = Number(data.entry_price || 0) || 0;
                    const side = String(data.side || "").toUpperCase();
                    const pnl = side === "SELL" ? (entry - mark) * qty : (mark - entry) * qty;
                    return String(pnl);
                  })()
                : (data.current_pnl || "0.00"),
            pnl_percent: data.pnl_percent || "0.00",
            status: data.status || "OPEN",
            created_at: data.created_at,
            last_updated: data.last_updated,
            reasoning: data.reasoning,
            allocation: data.allocation,
          });
        });

        setTrades(tradesData);
        setLoading(false);
        setError(null);
      },
      (err) => {
        console.error("Error fetching shadow trades:", err);
        setError(err.message || "Failed to fetch shadow trades");
        setLoading(false);
      }
    );

    return () => unsubscribe();
  }, [quotesBySymbol, user]);

  // Calculate portfolio summary
  const summary: ShadowPortfolioSummary = useMemo(() => {
    const out: ShadowPortfolioSummary = {
      totalPnL: 0,
      totalPnLPercent: 0,
      openPositions: trades.length,
      totalValue: 0,
    };

    if (trades.length === 0) return out;

    let totalPnL = 0;
    let totalCostBasis = 0;

    for (const trade of trades) {
      const pnl = parseFloat(trade.current_pnl || "0");
      const entryPrice = parseFloat(trade.entry_price || "0");
      const quantity = parseFloat(trade.quantity || "0");
      const costBasis = entryPrice * quantity;

      totalPnL += Number.isFinite(pnl) ? pnl : 0;
      totalCostBasis += Number.isFinite(costBasis) ? costBasis : 0;
      out.totalValue += (Number.isFinite(costBasis) ? costBasis : 0) + (Number.isFinite(pnl) ? pnl : 0);
    }

    out.totalPnL = totalPnL;
    if (totalCostBasis > 0) out.totalPnLPercent = (totalPnL / totalCostBasis) * 100;
    return out;
  }, [trades]);

  return {
    trades,
    summary,
    loading,
    error,
  };
};
