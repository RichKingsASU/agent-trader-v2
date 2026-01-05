import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Activity, AlertCircle, Loader2 } from "lucide-react";
import { useMarketLiveQuotes } from "@/hooks/useMarketLiveQuotes";
import { SystemStatusBadge } from "@/components/SystemStatusBadge";

function formatPrice(price: number | null | undefined) {
  return typeof price === "number" ? `$${price.toFixed(2)}` : "—";
}

function formatTime(d: Date | null | undefined) {
  return d instanceof Date ? d.toLocaleTimeString() : "—";
}

const LiveQuotesWidget = () => {
  const { quotes, loading, error, status, heartbeatAt } = useMarketLiveQuotes();
  const statusTitle = heartbeatAt ? `Last heartbeat: ${heartbeatAt.toLocaleString()}` : "No heartbeat";

  return (
    <Card className="bg-card/50 backdrop-blur-sm border-border/10">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between gap-3">
          <CardTitle className="flex items-center gap-2 text-lg">
            <Activity className="h-5 w-5 text-primary" />
            Live Quotes
          </CardTitle>
          <div className="flex items-center gap-2">
            <SystemStatusBadge status={status} title={statusTitle} />
            <Badge variant="outline" className="text-xs">
              {quotes.length} symbols
            </Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="flex items-center justify-center py-8 text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin mr-2" />
            Loading quotes...
          </div>
        ) : error ? (
          <div className="flex items-center justify-center py-8 text-destructive">
            <AlertCircle className="h-5 w-5 mr-2" />
            {error}
          </div>
        ) : quotes.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground">
            No quotes yet.
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Symbol</TableHead>
                <TableHead className="text-right">Bid</TableHead>
                <TableHead className="text-right">Ask</TableHead>
                <TableHead className="text-right">Last</TableHead>
                <TableHead className="text-right">Updated</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {quotes.map((quote) => (
                <TableRow key={quote.symbol}>
                  <TableCell className="font-mono font-medium">{quote.symbol}</TableCell>
                  <TableCell className="text-right font-mono">{formatPrice(quote.bid_price)}</TableCell>
                  <TableCell className="text-right font-mono">{formatPrice(quote.ask_price)}</TableCell>
                  <TableCell className="text-right font-mono">
                    {formatPrice(quote.last_trade_price ?? quote.price)}
                  </TableCell>
                  <TableCell className="text-right text-muted-foreground text-sm">
                    {formatTime(quote.last_update_ts)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
};

export default LiveQuotesWidget;

