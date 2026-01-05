import { useState, useEffect } from "react";
import { getFirestore, query, orderBy, limit, onSnapshot, Timestamp } from "firebase/firestore";
import { format } from "date-fns";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { useAuth } from "@/contexts/AuthContext";
import { tenantCollection } from "@/lib/tenancy/firestore";

interface Trade {
  id: string;
  timestamp: Timestamp;
  root_symbol: string;
  side: 'buy' | 'sell';
  strike: number;
  option_type: 'call' | 'put';
  expiry: Timestamp;
  price: number;
  delta: number | null;
}

export function RecentTradesTable() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);
  const [isConnected, setIsConnected] = useState(false);
  const { tenantId } = useAuth();

  useEffect(() => {
    const db = getFirestore();
    if (!tenantId) return;
    const tradesCollection = tenantCollection(db, tenantId, "trades");
    const tradesQuery = query(tradesCollection, orderBy("timestamp", "desc"), limit(50));

    const unsubscribe = onSnapshot(tradesQuery, (snapshot) => {
      const newTrades = snapshot.docs.map(doc => ({
        id: doc.id,
        ...doc.data()
      } as Trade));
      
      setTrades(newTrades);
      setLoading(false);
      setIsConnected(true); // Assume connection if we get data
    }, (error) => {
      console.error("Error fetching trades:", error);
      setLoading(false);
      setIsConnected(false);
    });

    return () => unsubscribe();
  }, [tenantId]);

  const formatTime = (timestamp: Timestamp) => {
    return format(timestamp.toDate(), "HH:mm:ss");
  };

  const formatExpiry = (expiry: Timestamp) => {
    return format(expiry.toDate(), "MM/dd");
  };

  const formatContract = (trade: Trade) => {
    return `${trade.strike} ${trade.option_type.toUpperCase()} Exp ${formatExpiry(trade.expiry)}`;
  };

  const formatPrice = (price: number) => {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
    }).format(price);
  };

  if (loading) {
    return (
      <div className="bg-slate-900 rounded-lg border border-slate-800 p-6">
        <div className="animate-pulse space-y-3">
          <div className="h-4 bg-slate-800 rounded w-1/4"></div>
          <div className="h-10 bg-slate-800 rounded"></div>
          <div className="h-10 bg-slate-800 rounded"></div>
          <div className="h-10 bg-slate-800 rounded"></div>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-slate-900 rounded-lg border border-slate-800">
      <div className="flex items-center justify-between p-4 border-b border-slate-800">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-semibold text-slate-100">Recent Trades</h2>
          <div className="flex items-center gap-1.5">
            <span
              className={`h-2 w-2 rounded-full ${
                isConnected ? "bg-emerald-500 animate-pulse" : "bg-slate-600"
              }`}
            />
            <span className="text-xs text-slate-500">
              {isConnected ? "Live" : "Connecting..."}
            </span>
          </div>
        </div>
      </div>

      <Table>
        <TableHeader>
          <TableRow className="border-slate-800 hover:bg-transparent">
            <TableHead className="text-slate-400">Time</TableHead>
            <TableHead className="text-slate-400">Ticker</TableHead>
            <TableHead className="text-slate-400">Strategy</TableHead>
            <TableHead className="text-slate-400">Contract</TableHead>
            <TableHead className="text-slate-400 text-right">Premium</TableHead>
            <TableHead className="text-slate-400 text-right">Greeks</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {trades.length === 0 ? (
            <TableRow>
              <TableCell colSpan={6} className="text-center text-slate-500 py-8">
                No trades found
              </TableCell>
            </TableRow>
          ) : (
            trades.map((trade) => (
              <TableRow key={trade.id} className="border-slate-800 hover:bg-slate-800/50">
                <TableCell className="font-mono text-slate-300">
                  {formatTime(trade.timestamp)}
                </TableCell>
                <TableCell>
                  <Badge variant="outline" className="border-slate-700 text-slate-200">
                    {trade.root_symbol}
                  </Badge>
                </TableCell>
                <TableCell>
                  <span
                    className={`font-medium ${
                      trade.side.toUpperCase() === "BUY"
                        ? "text-emerald-400"
                        : "text-red-400"
                    }`}
                  >
                    {trade.side.toUpperCase()}
                  </span>
                </TableCell>
                <TableCell className="text-slate-300">
                  {formatContract(trade)}
                </TableCell>
                <TableCell className="text-right font-mono text-slate-300">
                  {formatPrice(trade.price)}
                </TableCell>
                <TableCell className="text-right font-mono text-slate-400">
                  {trade.delta !== null ? `Δ ${trade.delta.toFixed(3)}` : "—"}
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  );
}
