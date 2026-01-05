import { useState, useEffect, useMemo } from 'react';
import { useMarketLiveQuotes } from './useMarketLiveQuotes';
import { getFirestore, query, where, orderBy, limit, getDocs } from 'firebase/firestore';

import { useAuth } from '@/contexts/AuthContext';
import { tenantCollection } from '@/lib/tenancy/firestore';

export interface WatchlistItem {
  symbol: string;
  price: number;
  change: number;
  changePct: number;
  volume: number;
  status: "hot" | "trending" | "normal";
  sparklineData: number[];
  isLive?: boolean;
}

// Mock data fallback
const mockWatchlist: WatchlistItem[] = [
  { symbol: "SPY", price: 432.15, change: 1.23, changePct: 0.29, volume: 85000000, status: "hot", sparklineData: [430, 431, 430.5, 432, 431.8, 432.15] },
  { symbol: "QQQ", price: 368.50, change: -0.85, changePct: -0.23, volume: 45000000, status: "normal", sparklineData: [369, 368.8, 369.2, 368.5, 368.3, 368.5] },
  { symbol: "AAPL", price: 178.23, change: 2.15, changePct: 1.22, volume: 52000000, status: "trending", sparklineData: [176, 177, 177.5, 178, 178.1, 178.23] },
  { symbol: "TSLA", price: 245.67, change: -3.45, changePct: -1.38, volume: 95000000, status: "hot", sparklineData: [249, 247, 246, 245, 246, 245.67] },
  { symbol: "NVDA", price: 495.30, change: 8.75, changePct: 1.80, volume: 78000000, status: "trending", sparklineData: [487, 490, 492, 494, 495, 495.3] },
  { symbol: "AMD", price: 165.80, change: 1.90, changePct: 1.16, volume: 34000000, status: "normal", sparklineData: [164, 165, 164.5, 165.5, 165.7, 165.8] },
  { symbol: "MSFT", price: 412.45, change: -1.20, changePct: -0.29, volume: 28000000, status: "normal", sparklineData: [413, 412.5, 413, 412.8, 412.3, 412.45] },
];

interface SparklineData {
  [symbol: string]: number[];
}

export function useLiveWatchlist() {
  const {
    quotes,
    quotesBySymbol,
    loading: quotesLoading,
    error,
    status,
    heartbeatAt,
    isLive: ingestIsLive,
  } = useMarketLiveQuotes();
  const [sparklines, setSparklines] = useState<SparklineData>({});
  const [sparklinesLoading, setSparklinesLoading] = useState(false);
  const { tenantId } = useAuth();

  // Fetch sparkline data from market_data_1m for symbols in quotes
  useEffect(() => {
    const fetchSparklines = async () => {
      if (!tenantId || quotes.length === 0) return;
      
      setSparklinesLoading(true);
      try {
        const db = getFirestore();
        const symbols = quotes.map(q => q.symbol);
        
        // Fetch last 6 bars per symbol
        const marketDataRef = tenantCollection(db, tenantId, 'market_data_1m');
        const q = query(marketDataRef, where('symbol', 'in', symbols), orderBy('ts', 'desc'), limit(symbols.length * 6));
        const snapshot = await getDocs(q);

        const data = snapshot.docs ? snapshot.docs.map(doc => doc.data()) : [];

        // Group by symbol and take last 6 closes
        const grouped: SparklineData = {};
        symbols.forEach(sym => {
          const symbolBars = data
            .filter(d => d.symbol === sym)
            .slice(0, 6)
            .reverse() || [];
          grouped[sym] = symbolBars.map(b => b.close);
        });

        setSparklines(grouped);
      } catch (err) {
        console.error('Error fetching sparklines:', err);
      } finally {
        setSparklinesLoading(false);
      }
    };

    fetchSparklines();
    
    // Refresh sparklines every 60 seconds
    const interval = setInterval(fetchSparklines, 60000);
    return () => clearInterval(interval);
  }, [quotes, tenantId]);

  // Build watchlist items from live quotes
  const watchlist = useMemo((): WatchlistItem[] => {
    if (!tenantId) return mockWatchlist;
    if (quotes.length === 0) return [];

    return quotes.map(quote => {
      const sparklineData = sparklines[quote.symbol] || [];
      const openPrice = sparklineData.length > 0 ? sparklineData[0] : quote.last_trade_price || 0;
      const currentPrice = quote.last_trade_price || quote.bid_price || 0;
      const change = currentPrice - openPrice;
      const changePct = openPrice > 0 ? (change / openPrice) * 100 : 0;

      // Determine status based on change percentage
      let status: "hot" | "trending" | "normal" = "normal";
      if (Math.abs(changePct) >= 2) status = "hot";
      else if (Math.abs(changePct) >= 1) status = "trending";

      return {
        symbol: quote.symbol,
        price: currentPrice,
        change,
        changePct,
        volume: 0, // Not available in live_quotes
        status,
        sparklineData: sparklineData.length > 0 ? sparklineData : [currentPrice],
        isLive: ingestIsLive,
      };
    });
  }, [quotes, sparklines, ingestIsLive, tenantId]);

  const hasLiveQuotes = quotes.length > 0;
  const isLive = ingestIsLive && hasLiveQuotes;
  const loading = quotesLoading || sparklinesLoading;

  return { watchlist, loading, isLive, status, heartbeatAt, hasLiveQuotes, error, quotesBySymbol };
}
