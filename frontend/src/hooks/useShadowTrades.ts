import { useState, useEffect } from "react";
import { getFirestore, collection, query, where, onSnapshot, QuerySnapshot, DocumentData } from "firebase/firestore";
import { app } from "@/firebase";
import { useAuth } from "@/contexts/AuthContext";

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

  useEffect(() => {
    if (!user) {
      setTrades([]);
      setLoading(false);
      return;
    }

    const db = getFirestore(app!);
    const shadowTradesRef = collection(db, "shadowTradeHistory");

    // Query OPEN shadow trades for current user
    const q = query(
      shadowTradesRef,
      where("uid", "==", user.uid),
      where("status", "==", "OPEN")
    );

    const unsubscribe = onSnapshot(
      q,
      (snapshot: QuerySnapshot<DocumentData>) => {
        const tradesData: ShadowTrade[] = [];

        snapshot.forEach((doc) => {
          const data = doc.data();
          tradesData.push({
            id: doc.id,
            uid: data.uid,
            symbol: data.symbol,
            side: data.side,
            quantity: data.quantity || "0",
            entry_price: data.entry_price || "0",
            current_price: data.current_price || data.entry_price || "0",
            current_pnl: data.current_pnl || "0.00",
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
  }, [user]);

  // Calculate portfolio summary
  const summary: ShadowPortfolioSummary = {
    totalPnL: 0,
    totalPnLPercent: 0,
    openPositions: trades.length,
    totalValue: 0,
  };

  if (trades.length > 0) {
    let totalPnL = 0;
    let totalCostBasis = 0;

    trades.forEach((trade) => {
      const pnl = parseFloat(trade.current_pnl || "0");
      const entryPrice = parseFloat(trade.entry_price || "0");
      const quantity = parseFloat(trade.quantity || "0");
      const costBasis = entryPrice * quantity;

      totalPnL += pnl;
      totalCostBasis += costBasis;
      summary.totalValue += costBasis + pnl; // Current value of position
    });

    summary.totalPnL = totalPnL;

    // Calculate weighted average P&L percent
    if (totalCostBasis > 0) {
      summary.totalPnLPercent = (totalPnL / totalCostBasis) * 100;
    }
  }

  return {
    trades,
    summary,
    loading,
    error,
  };
};
