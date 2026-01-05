import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { BarChart3, Loader2, AlertCircle } from "lucide-react";
import { getFirestore, query, orderBy, limit, getDocs, Timestamp } from "firebase/firestore";

import { useAuth } from "@/contexts/AuthContext";
import { tenantCollection } from "@/lib/tenancy/firestore";

interface MarketBar {
  symbol: string;
  ts: Timestamp;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

const MarketDataWidget = () => {
  const [bars, setBars] = useState<MarketBar[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { tenantId } = useAuth();

  useEffect(() => {
    const fetchBars = async () => {
      try {
        if (!tenantId) return;
        const db = getFirestore();
        const barsRef = tenantCollection(db, tenantId, "market_data_1m");
        const q = query(barsRef, orderBy("ts", "desc"), limit(200));
        const snapshot = await getDocs(q);
        const newBars = snapshot.docs.map(doc => doc.data() as MarketBar);
        setBars(newBars);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to fetch market data");
      } finally {
        setLoading(false);
      }
    };

    fetchBars();
  }, [tenantId]);

  const formatPrice = (price: number) => `$${price.toFixed(2)}`;
  const formatVolume = (vol: number) => vol.toLocaleString();
  const formatTime = (ts: Timestamp) => {
    const date = ts.toDate();
    return `${date.toLocaleDateString()} ${date.toLocaleTimeString()}`;
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-lg">
            <BarChart3 className="h-5 w-5 text-primary" />
            Recent 1-Minute Bars
          </CardTitle>
          <Badge variant="outline" className="text-xs">
            {bars.length} rows
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="flex items-center justify-center py-8 text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin mr-2" />
            Loading market data...
          </div>
        ) : error ? (
          <div className="flex items-center justify-center py-8 text-destructive">
            <AlertCircle className="h-5 w-5 mr-2" />
            {error}
          </div>
        ) : bars.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground">
            No market data yet.
          </div>
        ) : (
          <div className="max-h-96 overflow-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Timestamp</TableHead>
                  <TableHead className="text-right">Open</TableHead>
                  <TableHead className="text-right">High</TableHead>
                  <TableHead className="text-right">Low</TableHead>
                  <TableHead className="text-right">Close</TableHead>
                  <TableHead className="text-right">Volume</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {bars.map((bar, idx) => (
                  <TableRow key={`${bar.symbol}-${bar.ts.seconds}-${idx}`}>
                    <TableCell className="font-mono font-medium">{bar.symbol}</TableCell>
                    <TableCell className="text-muted-foreground text-sm">{formatTime(bar.ts)}</TableCell>
                    <TableCell className="text-right font-mono">{formatPrice(bar.open)}</TableCell>
                    <TableCell className="text-right font-mono">{formatPrice(bar.high)}</TableCell>
                    <TableCell className="text-right font-mono">{formatPrice(bar.low)}</TableCell>
                    <TableCell className="text-right font-mono">{formatPrice(bar.close)}</TableCell>
                    <TableCell className="text-right font-mono">{formatVolume(bar.volume)}</TableCell>
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

export default MarketDataWidget;
