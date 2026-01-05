import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { FileText, TrendingUp, TrendingDown } from "lucide-react";
import { useState, useEffect } from "react";

interface TradeHistoryTableProps {
  symbol: string;
}

interface Trade {
  id: number;
  time: string;
  symbol: string;
  description: string;
  side: "BUY" | "SELL";
  qty: number;
  entryPrice: number;
  exitPrice?: number;
  pnl: number;
  environment: string;
  hasNote: boolean;
  note?: {
    plan: string;
    setup: string;
    risk: string;
    timestamp: string;
  };
}

export const TradeHistoryTable = ({ symbol }: TradeHistoryTableProps) => {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedTrade, setSelectedTrade] = useState<Trade | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  useEffect(() => {
    // Mock data - replace with actual API call
    const mockTrades: Trade[] = [
      {
        id: 1,
        time: "09:35:12",
        symbol: symbol,
        description: `${symbol} 19Dec25 430C`,
        side: "BUY",
        qty: 5,
        entryPrice: 2.45,
        exitPrice: 2.78,
        pnl: 165,
        environment: "Breakout above PDH",
        hasNote: true,
        note: {
          plan: "Watching for breakout above PDH at 433.50. Strong volume coming in with RVOL at 2.3x. RSI showing bullish momentum without being overbought. Plan to enter calls if we break and hold above with stop below ORH.",
          setup: "Bullish breakout setup with volume confirmation",
          risk: "Risk: $122.50 | Target: $195 | R:R: 1:1.6",
          timestamp: "09:33:45",
        },
      },
      {
        id: 2,
        time: "10:42:33",
        symbol: symbol,
        description: `${symbol} 19Dec25 428P`,
        side: "SELL",
        qty: 3,
        entryPrice: 1.85,
        exitPrice: 1.62,
        pnl: 69,
        environment: "Rejection at ORH",
        hasNote: false,
      },
      {
        id: 3,
        time: "11:15:44",
        symbol: symbol,
        description: `${symbol} 19Dec25 432C`,
        side: "BUY",
        qty: 2,
        entryPrice: 3.10,
        pnl: -45,
        environment: "False breakout",
        hasNote: true,
        note: {
          plan: "Attempted to capitalize on price consolidating near highs. Expected continuation but momentum faded. RVOL started dropping below 1.5x which should have been my signal to exit earlier.",
          setup: "Failed continuation play",
          risk: "Risk: $90 | Stop hit at breakeven attempt",
          timestamp: "11:14:20",
        },
      },
    ];

    setTimeout(() => {
      setTrades(mockTrades);
      setLoading(false);
    }, 500);
  }, [symbol]);

  const handleOpenNote = (trade: Trade) => {
    setSelectedTrade(trade);
    setDialogOpen(true);
  };

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Recent Trades - {symbol}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-12 bg-muted animate-pulse rounded" />
            ))}
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Recent Trades - {symbol}</CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/50">
              <TableHead>Time</TableHead>
              <TableHead>Symbol</TableHead>
              <TableHead>Description</TableHead>
              <TableHead>Side</TableHead>
              <TableHead className="text-right">Qty</TableHead>
              <TableHead className="text-right">Entry</TableHead>
              <TableHead className="text-right">Exit</TableHead>
              <TableHead className="text-right">P&L</TableHead>
              <TableHead>Environment</TableHead>
              <TableHead className="text-center">Journal</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {trades.length === 0 ? (
              <TableRow>
                <TableCell colSpan={10} className="text-center text-muted-foreground py-8">
                  No recent trades for {symbol}
                </TableCell>
              </TableRow>
            ) : (
              trades.map((trade, idx) => (
                <TableRow key={trade.id} className={idx % 2 === 0 ? "bg-background" : "bg-muted/20"}>
                  <TableCell className="font-mono text-xs">{trade.time}</TableCell>
                  <TableCell className="font-semibold">{trade.symbol}</TableCell>
                  <TableCell className="text-sm">{trade.description}</TableCell>
                  <TableCell>
                    <Badge variant={trade.side === "BUY" ? "default" : "secondary"}>
                      {trade.side}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">{trade.qty}</TableCell>
                  <TableCell className="text-right font-mono text-sm">${trade.entryPrice.toFixed(2)}</TableCell>
                  <TableCell className="text-right font-mono text-sm">
                    {trade.exitPrice ? `$${trade.exitPrice.toFixed(2)}` : "—"}
                  </TableCell>
                  <TableCell className="text-right font-semibold">
                    <span className={trade.pnl >= 0 ? "text-green-600" : "text-red-600"}>
                      {trade.pnl >= 0 ? "+" : ""}${trade.pnl}
                    </span>
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">{trade.environment}</TableCell>
                  <TableCell className="text-center">
                    {trade.hasNote && (
                      <button 
                        onClick={() => handleOpenNote(trade)}
                        className="text-muted-foreground hover:text-foreground transition-colors"
                      >
                        <FileText className="h-4 w-4" />
                      </button>
                    )}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </CardContent>

      {/* Trade Journal Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-4xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Trade Journal - {selectedTrade?.description}</DialogTitle>
            <DialogDescription>
              {selectedTrade?.time} • {selectedTrade?.environment}
            </DialogDescription>
          </DialogHeader>

          {selectedTrade && (
            <div className="grid grid-cols-2 gap-6 mt-4">
              {/* Left: Plan/Note */}
              <div className="space-y-4">
                <div>
                  <h3 className="text-sm font-semibold mb-2 flex items-center gap-2">
                    <FileText className="h-4 w-4" />
                    Pre-Trade Plan
                  </h3>
                  <div className="bg-muted/30 rounded-lg p-4 space-y-3">
                    <div>
                      <p className="text-xs text-muted-foreground mb-1">Timestamp</p>
                      <p className="text-sm font-mono">{selectedTrade.note?.timestamp}</p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground mb-1">Setup</p>
                      <p className="text-sm">{selectedTrade.note?.setup}</p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground mb-1">Plan</p>
                      <p className="text-sm">{selectedTrade.note?.plan}</p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground mb-1">Risk Management</p>
                      <p className="text-sm font-mono">{selectedTrade.note?.risk}</p>
                    </div>
                  </div>
                </div>
              </div>

              {/* Right: Trade Result */}
              <div className="space-y-4">
                <div>
                  <h3 className="text-sm font-semibold mb-2 flex items-center gap-2">
                    {selectedTrade.pnl >= 0 ? (
                      <TrendingUp className="h-4 w-4 text-green-600" />
                    ) : (
                      <TrendingDown className="h-4 w-4 text-red-600" />
                    )}
                    Trade Result
                  </h3>
                  <div className="bg-muted/30 rounded-lg p-4 space-y-3">
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <p className="text-xs text-muted-foreground mb-1">Side</p>
                        <Badge variant={selectedTrade.side === "BUY" ? "default" : "secondary"}>
                          {selectedTrade.side}
                        </Badge>
                      </div>
                      <div>
                        <p className="text-xs text-muted-foreground mb-1">Quantity</p>
                        <p className="text-sm font-semibold">{selectedTrade.qty}</p>
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <p className="text-xs text-muted-foreground mb-1">Entry Price</p>
                        <p className="text-sm font-mono">${selectedTrade.entryPrice.toFixed(2)}</p>
                      </div>
                      <div>
                        <p className="text-xs text-muted-foreground mb-1">Exit Price</p>
                        <p className="text-sm font-mono">
                          {selectedTrade.exitPrice ? `$${selectedTrade.exitPrice.toFixed(2)}` : "Open"}
                        </p>
                      </div>
                    </div>
                    <div className="pt-3 border-t border-border">
                      <p className="text-xs text-muted-foreground mb-1">P&L</p>
                      <p className={`text-2xl font-bold ${selectedTrade.pnl >= 0 ? "text-green-600" : "text-red-600"}`}>
                        {selectedTrade.pnl >= 0 ? "+" : ""}${selectedTrade.pnl}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground mb-1">Environment</p>
                      <p className="text-sm">{selectedTrade.environment}</p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </Card>
  );
};
