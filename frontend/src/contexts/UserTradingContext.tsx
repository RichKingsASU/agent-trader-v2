import React, { createContext, useContext, useEffect, useState } from "react";
import { doc, collection, onSnapshot, query, orderBy, limit } from "firebase/firestore";
import { db } from "../firebase";
import { useAuth } from "./AuthContext";

/**
 * UserTradingContext: Multi-Tenant SaaS Context for User-Specific Trading Data
 * 
 * This context provides real-time access to user-scoped Firestore data:
 * - Alpaca account snapshot: users/{uid}/alpaca/snapshot
 * - Shadow trade history: users/{uid}/shadowTradeHistory
 * - Trading signals: users/{uid}/signals
 * 
 * Architecture:
 * - Data is isolated by Firebase Auth uid
 * - Real-time listeners via Firestore onSnapshot
 * - Automatically unsubscribes on unmount or user change
 */

export interface AlpacaSnapshot {
  equity?: string;
  buying_power?: string;
  cash?: string;
  status?: string;
  updated_at?: any;
  updated_at_iso?: string;
  raw?: any;
  [key: string]: any;
}

export interface ShadowTrade {
  shadow_id?: string;
  uid: string;
  symbol: string;
  side: string;
  quantity: string;
  entry_price: string;
  current_price?: string;
  current_pnl?: string;
  pnl_percent?: string;
  status: "OPEN" | "CLOSED";
  created_at: any;
  last_updated?: any;
  reasoning?: string;
  metadata?: any;
  [key: string]: any;
}

export interface TradingSignal {
  id?: string;
  action: string;
  symbol: string;
  confidence?: number;
  reasoning: string;
  allocation?: number;
  timestamp: any;
  strategy?: string;
  [key: string]: any;
}

interface UserTradingContextType {
  // Alpaca account snapshot
  accountSnapshot: AlpacaSnapshot | null;
  accountLoading: boolean;
  accountError: Error | null;
  
  // Shadow trades
  shadowTrades: ShadowTrade[];
  shadowTradesLoading: boolean;
  shadowTradesError: Error | null;
  
  // Trading signals
  signals: TradingSignal[];
  signalsLoading: boolean;
  signalsError: Error | null;
  
  // Derived data
  openShadowTrades: ShadowTrade[];
  totalUnrealizedPnL: number;
}

const UserTradingContext = createContext<UserTradingContextType | undefined>(undefined);

export const UserTradingProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { user } = useAuth();
  
  // Alpaca account snapshot state
  const [accountSnapshot, setAccountSnapshot] = useState<AlpacaSnapshot | null>(null);
  const [accountLoading, setAccountLoading] = useState(true);
  const [accountError, setAccountError] = useState<Error | null>(null);
  
  // Shadow trades state
  const [shadowTrades, setShadowTrades] = useState<ShadowTrade[]>([]);
  const [shadowTradesLoading, setShadowTradesLoading] = useState(true);
  const [shadowTradesError, setShadowTradesError] = useState<Error | null>(null);
  
  // Trading signals state
  const [signals, setSignals] = useState<TradingSignal[]>([]);
  const [signalsLoading, setSignalsLoading] = useState(true);
  const [signalsError, setSignalsError] = useState<Error | null>(null);
  
  // Listen to Alpaca account snapshot: users/{uid}/alpaca/snapshot
  useEffect(() => {
    if (!user) {
      setAccountSnapshot(null);
      setAccountLoading(false);
      setAccountError(null);
      return;
    }
    
    setAccountLoading(true);
    setAccountError(null);
    
    // Multi-tenant path: users/{uid}/data/snapshot
    const snapshotRef = doc(db, "users", user.uid, "data", "snapshot");
    
    const unsubscribe = onSnapshot(
      snapshotRef,
      (snapshot) => {
        if (snapshot.exists()) {
          setAccountSnapshot(snapshot.data() as AlpacaSnapshot);
        } else {
          setAccountSnapshot(null);
        }
        setAccountLoading(false);
      },
      (error) => {
        console.error("Error listening to account snapshot:", error);
        setAccountError(error as Error);
        setAccountLoading(false);
      }
    );
    
    return () => unsubscribe();
  }, [user]);
  
  // Listen to shadow trades: users/{uid}/shadowTradeHistory
  useEffect(() => {
    if (!user) {
      setShadowTrades([]);
      setShadowTradesLoading(false);
      setShadowTradesError(null);
      return;
    }
    
    setShadowTradesLoading(true);
    setShadowTradesError(null);
    
    // Multi-tenant path: users/{uid}/shadowTradeHistory
    const tradesRef = collection(db, "users", user.uid, "shadowTradeHistory");
    const tradesQuery = query(tradesRef, orderBy("created_at", "desc"), limit(100));
    
    const unsubscribe = onSnapshot(
      tradesQuery,
      (snapshot) => {
        const trades = snapshot.docs.map((doc) => ({
          id: doc.id,
          ...doc.data(),
        })) as unknown as ShadowTrade[];
        setShadowTrades(trades);
        setShadowTradesLoading(false);
      },
      (error) => {
        console.error("Error listening to shadow trades:", error);
        setShadowTradesError(error as Error);
        setShadowTradesLoading(false);
      }
    );
    
    return () => unsubscribe();
  }, [user]);
  
  // Listen to trading signals: users/{uid}/signals
  useEffect(() => {
    if (!user) {
      setSignals([]);
      setSignalsLoading(false);
      setSignalsError(null);
      return;
    }
    
    setSignalsLoading(true);
    setSignalsError(null);
    
    // Multi-tenant path: users/{uid}/signals
    const signalsRef = collection(db, "users", user.uid, "signals");
    const signalsQuery = query(signalsRef, orderBy("timestamp", "desc"), limit(50));
    
    const unsubscribe = onSnapshot(
      signalsQuery,
      (snapshot) => {
        const signalsData = snapshot.docs.map((doc) => ({
          id: doc.id,
          ...doc.data(),
        })) as TradingSignal[];
        setSignals(signalsData);
        setSignalsLoading(false);
      },
      (error) => {
        console.error("Error listening to signals:", error);
        setSignalsError(error as Error);
        setSignalsLoading(false);
      }
    );
    
    return () => unsubscribe();
  }, [user]);
  
  // Derived data: open shadow trades
  const openShadowTrades = shadowTrades.filter((trade) => trade.status === "OPEN");
  
  // Derived data: total unrealized P&L
  const totalUnrealizedPnL = openShadowTrades.reduce((sum, trade) => {
    const pnl = parseFloat(trade.current_pnl || "0");
    return sum + (isNaN(pnl) ? 0 : pnl);
  }, 0);
  
  return (
    <UserTradingContext.Provider
      value={{
        accountSnapshot,
        accountLoading,
        accountError,
        shadowTrades,
        shadowTradesLoading,
        shadowTradesError,
        signals,
        signalsLoading,
        signalsError,
        openShadowTrades,
        totalUnrealizedPnL,
      }}
    >
      {children}
    </UserTradingContext.Provider>
  );
};

export const useUserTrading = () => {
  const context = useContext(UserTradingContext);
  if (!context) {
    throw new Error("useUserTrading must be used within UserTradingProvider");
  }
  return context;
};
