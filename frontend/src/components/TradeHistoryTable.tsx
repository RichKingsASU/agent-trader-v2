import { useState } from "react";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { ChevronDown, ChevronUp, Filter, StickyNote, TrendingUp, TrendingDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { AIPostGame } from "./AIPostGame";

interface AIAnalysis {
  grade: string;
  feedback: string;
  analyzed_at?: string;
  model?: string;
}

interface Trade {
  id: string;
  timestamp: string;
  symbol: string;
  side: "long" | "short";
  entry_price: number;
  exit_price: number;
  quantity: number;
  pnl_usd: number;
  pnl_pct: number;
  duration_minutes: number;
  environment: "production" | "paper";
  strategy: string;
  notes_count: number;
  linked_note_ids?: string[];
  entry_reason?: string;
  exit_reason?: string;
  max_drawdown_pct?: number;
  max_profit_pct?: number;
  ai_analysis?: AIAnalysis;
}

interface TradeHistoryTableProps {
  trades?: Trade[];
  loading?: boolean;
}

export function TradeHistoryTable({ trades, loading = false }: TradeHistoryTableProps) {
  const [symbolFilter, setSymbolFilter] = useState<string>("all");
  const [envFilter, setEnvFilter] = useState<string>("all");
  const [dateFilter, setDateFilter] = useState<string>("");
  const [expandedTradeId, setExpandedTradeId] = useState<string | null>(null);

  // Mock trades data
  const mockTrades: Trade[] = [
    {
      id: "trade_001",
      timestamp: "2025-01-15T14:32:10Z",
      symbol: "SPY",
      side: "long",
      entry_price: 430.50,
      exit_price: 432.15,
      quantity: 10,
      pnl_usd: 165.00,
      pnl_pct: 0.38,
      duration_minutes: 45,
      environment: "production",
      strategy: "VWAP Bounce",
      notes_count: 2,
      linked_note_ids: ["note_001", "note_002"],
      entry_reason: "Clean bounce off VWAP with volume confirmation",
      exit_reason: "Hit profit target at resistance",
      max_drawdown_pct: -0.12,
      max_profit_pct: 0.45,
      ai_analysis: {
        grade: "A",
        feedback: "Excellent execution. You correctly identified positive GEX regime and bought the dip with discipline. Entry timing at VWAP support was textbook. Consider scaling position size on high-conviction setups like this one.",
        analyzed_at: "2025-01-15T14:33:00Z",
        model: "gemini-1.5-flash",
      },
    },
    {
      id: "trade_002",
      timestamp: "2025-01-15T13:15:20Z",
      symbol: "QQQ",
      side: "short",
      entry_price: 385.20,
      exit_price: 384.10,
      quantity: 15,
      pnl_usd: 165.00,
      pnl_pct: 0.29,
      duration_minutes: 28,
      environment: "production",
      strategy: "Breakdown",
      notes_count: 1,
      linked_note_ids: ["note_003"],
      entry_reason: "Failed to reclaim key level, volume spike",
      exit_reason: "Profit target reached",
      max_drawdown_pct: -0.08,
      max_profit_pct: 0.31,
    },
    {
      id: "trade_003",
      timestamp: "2025-01-15T11:45:30Z",
      symbol: "TSLA",
      side: "long",
      entry_price: 242.80,
      exit_price: 241.50,
      quantity: 20,
      pnl_usd: -260.00,
      pnl_pct: -0.54,
      duration_minutes: 18,
      environment: "production",
      strategy: "Breakout",
      notes_count: 3,
      linked_note_ids: ["note_004", "note_005", "note_006"],
      entry_reason: "Breakout above resistance with volume",
      exit_reason: "Stop loss hit - false breakout",
      max_drawdown_pct: -0.62,
      max_profit_pct: 0.15,
      ai_analysis: {
        grade: "D",
        feedback: "Poor execution. Negative GEX regime (-$800M) creates volatility amplification. In this environment, breakouts often fail as dealers amplify reversals. Next time, verify GEX regime before chasing momentum and tighten stops in high gamma markets.",
        analyzed_at: "2025-01-15T11:46:00Z",
        model: "gemini-1.5-flash",
      },
    },
    {
      id: "trade_004",
      timestamp: "2025-01-15T10:20:15Z",
      symbol: "AAPL",
      side: "long",
      entry_price: 185.50,
      exit_price: 186.85,
      quantity: 25,
      pnl_usd: 337.50,
      pnl_pct: 0.73,
      duration_minutes: 52,
      environment: "production",
      strategy: "Opening Range",
      notes_count: 1,
      linked_note_ids: ["note_007"],
      entry_reason: "Break above opening range high",
      exit_reason: "Time-based exit at lunch",
      max_drawdown_pct: -0.05,
      max_profit_pct: 0.78,
    },
    {
      id: "trade_005",
      timestamp: "2025-01-14T15:45:00Z",
      symbol: "SPY",
      side: "short",
      entry_price: 428.90,
      exit_price: 429.30,
      quantity: 12,
      pnl_usd: -48.00,
      pnl_pct: -0.09,
      duration_minutes: 15,
      environment: "paper",
      strategy: "Mean Reversion",
      notes_count: 0,
      entry_reason: "Overbought RSI at resistance",
      exit_reason: "Stop loss - continued strength",
      max_drawdown_pct: -0.11,
      max_profit_pct: 0.03,
    },
  ];

  const displayTrades = trades || mockTrades;

  // Filter trades
  const filteredTrades = displayTrades.filter((trade) => {
    if (symbolFilter !== "all" && trade.symbol !== symbolFilter) return false;
    if (envFilter !== "all" && trade.environment !== envFilter) return false;
    if (dateFilter && !trade.timestamp.includes(dateFilter)) return false;
    return true;
  });

  // Get unique symbols for filter
  const uniqueSymbols = Array.from(new Set(displayTrades.map((t) => t.symbol)));

  // Calculate summary stats
  const totalPnL = filteredTrades.reduce((sum, t) => sum + t.pnl_usd, 0);
  const winningTrades = filteredTrades.filter((t) => t.pnl_usd > 0).length;
  const totalTrades = filteredTrades.length;
  const winRate = totalTrades > 0 ? (winningTrades / totalTrades) * 100 : 0;

  const toggleTradeExpansion = (tradeId: string) => {
    setExpandedTradeId(expandedTradeId === tradeId ? null : tradeId);
  };

  if (loading) {
    return (
      <Card className="p-6">
        <div className="flex items-center justify-center text-muted-foreground">
          Loading trade history...
        </div>
      </Card>
    );
  }

  return (
    <Card className="p-6 border-white/10">
      {/* Filters Section */}
      <div className="flex flex-wrap items-center gap-3 mb-6">
        <div className="flex items-center gap-2">
          <Filter className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-medium ui-label">Filters:</span>
        </div>
        
        <Select value={symbolFilter} onValueChange={setSymbolFilter}>
          <SelectTrigger className="w-[140px]">
            <SelectValue placeholder="Symbol" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Symbols</SelectItem>
            {uniqueSymbols.map((symbol) => (
              <SelectItem key={symbol} value={symbol}>
                {symbol}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={envFilter} onValueChange={setEnvFilter}>
          <SelectTrigger className="w-[140px]">
            <SelectValue placeholder="Environment" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Environments</SelectItem>
            <SelectItem value="production">Production</SelectItem>
            <SelectItem value="paper">Paper</SelectItem>
          </SelectContent>
        </Select>

        <Input
          type="date"
          value={dateFilter}
          onChange={(e) => setDateFilter(e.target.value)}
          className="w-[180px]"
          placeholder="Filter by date"
        />

        {(symbolFilter !== "all" || envFilter !== "all" || dateFilter) && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setSymbolFilter("all");
              setEnvFilter("all");
              setDateFilter("");
            }}
          >
            Clear Filters
          </Button>
        )}

        {/* Summary Stats */}
        <div className="ml-auto flex items-center gap-4 text-sm">
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground ui-label">Total P/L:</span>
            <span
              className={cn(
                "font-mono font-semibold",
                totalPnL >= 0 ? "bull-text" : "bear-text"
              )}
            >
              ${totalPnL.toFixed(2)}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground ui-label">Win Rate:</span>
            <span className="font-mono font-semibold">{winRate.toFixed(1)}%</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-muted-foreground ui-label">Trades:</span>
            <span className="font-mono font-semibold">{totalTrades}</span>
          </div>
        </div>
      </div>

      {/* Table */}
      {filteredTrades.length === 0 ? (
        <div className="text-center py-8 text-muted-foreground">
          No trades found matching filters
        </div>
      ) : (
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[50px]"></TableHead>
                <TableHead>Time</TableHead>
                <TableHead>Symbol</TableHead>
                <TableHead>Side</TableHead>
                <TableHead>Entry</TableHead>
                <TableHead>Exit</TableHead>
                <TableHead>Qty</TableHead>
                <TableHead>P/L</TableHead>
                <TableHead>Duration</TableHead>
                <TableHead>Strategy</TableHead>
                <TableHead>Env</TableHead>
                <TableHead>Notes</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredTrades.map((trade) => (
                <Collapsible
                  key={trade.id}
                  open={expandedTradeId === trade.id}
                  onOpenChange={() => toggleTradeExpansion(trade.id)}
                  asChild
                >
                  <>
                     <TableRow className="cursor-pointer hover:bg-muted/50">
                      <TableCell>
                        <CollapsibleTrigger asChild>
                          <Button variant="ghost" size="sm" className="h-6 w-6 p-0">
                            {expandedTradeId === trade.id ? (
                              <ChevronUp className="h-4 w-4" />
                            ) : (
                              <ChevronDown className="h-4 w-4" />
                            )}
                          </Button>
                        </CollapsibleTrigger>
                      </TableCell>
                      <TableCell className="text-xs">
                        {new Date(trade.timestamp).toLocaleString("en-US", {
                          month: "short",
                          day: "numeric",
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </TableCell>
                      <TableCell>
                        <span className="font-semibold">{trade.symbol}</span>
                      </TableCell>
                      <TableCell>
                        <Badge
                          className={cn(
                            "uppercase text-xs font-semibold rounded-full px-3 py-1",
                            trade.side === "long" 
                              ? "bg-bull/20 text-bull border-bull/30 hover:bg-bull/30" 
                              : "bg-bear/20 text-bear border-bear/30 hover:bg-bear/30"
                          )}
                        >
                          {trade.side === "long" ? (
                            <TrendingUp className="h-3 w-3 mr-1" />
                          ) : (
                            <TrendingDown className="h-3 w-3 mr-1" />
                          )}
                          {trade.side}
                        </Badge>
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        ${trade.entry_price.toFixed(2)}
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        ${trade.exit_price.toFixed(2)}
                      </TableCell>
                      <TableCell>{trade.quantity}</TableCell>
                      <TableCell>
                        <div className="flex flex-col">
                          <span
                            className={cn(
                              "font-mono font-semibold",
                              trade.pnl_usd >= 0 ? "bull-text" : "bear-text"
                            )}
                          >
                            ${trade.pnl_usd.toFixed(2)}
                          </span>
                          <span
                            className={cn(
                              "text-xs font-mono",
                              trade.pnl_pct >= 0 ? "bull-text/80" : "bear-text/80"
                            )}
                          >
                            ({trade.pnl_pct >= 0 ? "+" : ""}
                            {trade.pnl_pct.toFixed(2)}%)
                          </span>
                        </div>
                      </TableCell>
                      <TableCell className="text-xs">
                        {trade.duration_minutes}m
                      </TableCell>
                      <TableCell className="text-xs">{trade.strategy}</TableCell>
                      <TableCell>
                        <Badge
                          variant={trade.environment === "production" ? "default" : "outline"}
                          className="text-xs"
                        >
                          {trade.environment === "production" ? "PROD" : "PAPER"}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        {trade.notes_count > 0 && (
                          <div className="flex items-center gap-1 text-xs text-muted-foreground">
                            <StickyNote className="h-3 w-3" />
                            <span>{trade.notes_count}</span>
                          </div>
                        )}
                      </TableCell>
                    </TableRow>
                    <CollapsibleContent asChild>
                      <TableRow>
                        <TableCell colSpan={12} className="bg-muted/30 p-4">
                          <div className="space-y-4">
                            {/* AI Analysis - Show at top if available */}
                            {trade.ai_analysis && (
                              <AIPostGame
                                analysis={trade.ai_analysis}
                                pnl={trade.pnl_usd}
                              />
                            )}

                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                              {/* Trade Details */}
                              <div className="space-y-3">
                                <h4 className="text-sm font-semibold">Trade Details</h4>
                                <div className="space-y-2 text-sm">
                                  <div className="flex justify-between">
                                    <span className="text-muted-foreground">Trade ID:</span>
                                    <span className="font-mono">{trade.id}</span>
                                  </div>
                                  <div className="flex justify-between">
                                    <span className="text-muted-foreground">Entry Reason:</span>
                                    <span className="text-right max-w-[250px]">
                                      {trade.entry_reason || "N/A"}
                                    </span>
                                  </div>
                                  <div className="flex justify-between">
                                    <span className="text-muted-foreground">Exit Reason:</span>
                                    <span className="text-right max-w-[250px]">
                                      {trade.exit_reason || "N/A"}
                                    </span>
                                  </div>
                                  <div className="flex justify-between">
                                    <span className="text-muted-foreground">Max Profit:</span>
                                    <span className="text-green-500 font-semibold">
                                      +{trade.max_profit_pct?.toFixed(2)}%
                                    </span>
                                  </div>
                                  <div className="flex justify-between">
                                    <span className="text-muted-foreground">Max Drawdown:</span>
                                    <span className="text-red-500 font-semibold">
                                      {trade.max_drawdown_pct?.toFixed(2)}%
                                    </span>
                                  </div>
                                </div>
                              </div>

                              {/* Journal Notes */}
                              <div className="space-y-3">
                                <h4 className="text-sm font-semibold flex items-center gap-2">
                                  <StickyNote className="h-4 w-4" />
                                  Linked Notes ({trade.notes_count})
                                </h4>
                                {trade.notes_count > 0 ? (
                                  <div className="space-y-2">
                                    {trade.linked_note_ids?.map((noteId) => (
                                      <div
                                        key={noteId}
                                        className="p-2 bg-background rounded border text-xs"
                                      >
                                        <div className="flex justify-between items-start mb-1">
                                          <span className="font-mono text-muted-foreground">
                                            {noteId}
                                          </span>
                                          <Button variant="ghost" size="sm" className="h-6 text-xs">
                                            View
                                          </Button>
                                        </div>
                                        <p className="text-muted-foreground">
                                          Click to view full note details...
                                        </p>
                                      </div>
                                    ))}
                                  </div>
                                ) : (
                                  <p className="text-sm text-muted-foreground">
                                    No notes linked to this trade
                                  </p>
                                )}
                              </div>
                            </div>
                          </div>
                        </TableCell>
                      </TableRow>
                    </CollapsibleContent>
                  </>
                </Collapsible>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </Card>
  );
}
