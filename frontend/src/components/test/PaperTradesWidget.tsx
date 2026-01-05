import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { FileText, Loader2, AlertCircle } from "lucide-react";
import { getFirestore, query, orderBy, limit, getDocs, Timestamp } from "firebase/firestore";

import { useAuth } from "@/contexts/AuthContext";
import { tenantCollection } from "@/lib/tenancy/firestore";

interface PaperTrade {
  created_at: Timestamp;
  symbol: string;
  side: string;
  qty: number;
  price: number;
  status: string | null;
  source: string | null;
}

const PaperTradesWidget = () => {
  const [trades, setTrades] = useState<PaperTrade[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { tenantId } = useAuth();

  useEffect(() => {
    const fetchTrades = async () => {
      try {
        if (!tenantId) return;
        const db = getFirestore();
        const tradesRef = tenantCollection(db, tenantId, "paper_trades");
        const q = query(tradesRef, orderBy("created_at", "desc"), limit(50));
        const snapshot = await getDocs(q);
        const newTrades = snapshot.docs.map(doc => doc.data() as PaperTrade);
        setTrades(newTrades);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to fetch trades");
      } finally {
        setLoading(false);
      }
    };

    fetchTrades();
  }, [tenantId]);

  const formatTime = (ts: Timestamp) => {
    const date = ts.toDate();
    return `${date.toLocaleDateString()} ${date.toLocaleTimeString()}`;
  };

  const formatPrice = (price: number) => `$${price.toFixed(2)}`;

  const getSideBadgeVariant = (side: string) => {
    return side.toLowerCase() === "buy" ? "default" : "destructive";
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-lg">
            <FileText className="h-5 w-5 text-primary" />
            Recent Paper Trades
          </CardTitle>
          <Badge variant="outline" className="text-xs">
            {trades.length} trades
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="flex items-center justify-center py-8 text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin mr-2" />
            Loading trades...
          </div>
        ) : error ? (
          <div className="flex items-center justify-center py-8 text-destructive">
            <AlertCircle className="h-5 w-5 mr-2" />
            {error}
          </div>
        ) : trades.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground">
            No paper trades yet.
          </div>
        ) : (
          <div className="max-h-80 overflow-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Time</TableHead>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Side</TableHead>
                  <TableHead className="text-right">Qty</TableHead>
                  <TableHead className="text-right">Price</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Source</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {trades.map((trade, idx) => (
                  <TableRow key={`${trade.symbol}-${trade.created_at.seconds}-${idx}`}>
                    <TableCell className="text-muted-foreground text-sm">{formatTime(trade.created_at)}</TableCell>
                    <TableCell className="font-mono font-medium">{trade.symbol}</TableCell>
                    <TableCell>
                      <Badge variant={getSideBadgeVariant(trade.side)} className="uppercase text-xs">
                        {trade.side}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right font-mono">{trade.qty}</TableCell>
                    <TableCell className="text-right font-mono">{formatPrice(trade.price)}</TableCell>
                    <TableCell>
                      <Badge variant="outline" className="text-xs">
                        {trade.status || "—"}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground text-sm">{trade.source || "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
};

export default PaperTradesWidget;
