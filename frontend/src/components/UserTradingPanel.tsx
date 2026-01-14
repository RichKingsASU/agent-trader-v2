import React from "react";
import { useUserTrading } from "@/contexts/UserTradingContext";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { AlertCircle, TrendingUp, TrendingDown, DollarSign } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { ConfidenceSignalPanel } from "@/components/ConfidenceSignalPanel";

/**
 * UserTradingPanel: Multi-Tenant SaaS Dashboard Component
 * 
 * Demonstrates user-specific trading data isolated by Firebase Auth uid.
 * 
 * Features:
 * - Real-time Alpaca account snapshot
 * - User-scoped shadow trade history
 * - Live P&L updates
 * - Data isolation verification
 * 
 * Security:
 * - All data is scoped to users/{uid}/*
 * - Firestore rules enforce uid-based access control
 * - No user can see another user's data
 */
export const UserTradingPanel: React.FC = () => {
  const {
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
  } = useUserTrading();

  // Format currency
  const formatCurrency = (value: string | number | undefined): string => {
    if (value === undefined || value === null) return "$0.00";
    const num = typeof value === "string" ? parseFloat(value) : value;
    if (isNaN(num)) return "$0.00";
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: 2,
    }).format(num);
  };

  // Format percentage
  const formatPercent = (value: string | number | undefined): string => {
    if (value === undefined || value === null) return "0.00%";
    const num = typeof value === "string" ? parseFloat(value) : value;
    if (isNaN(num)) return "0.00%";
    return `${num >= 0 ? "+" : ""}${num.toFixed(2)}%`;
  };

  return (
    <div className="space-y-6 p-6">
      <ConfidenceSignalPanel />

      {/* Account Overview */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <DollarSign className="h-5 w-5" />
            Account Overview
          </CardTitle>
          <CardDescription>
            Your Alpaca account snapshot (isolated by user ID)
          </CardDescription>
        </CardHeader>
        <CardContent>
          {accountLoading ? (
            <div className="space-y-2">
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-4 w-1/2" />
            </div>
          ) : accountError ? (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>Error</AlertTitle>
              <AlertDescription>{accountError.message}</AlertDescription>
            </Alert>
          ) : accountSnapshot ? (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="space-y-1">
                <p className="text-sm text-muted-foreground">Equity</p>
                <p className="text-2xl font-bold">
                  {formatCurrency(accountSnapshot.equity)}
                </p>
              </div>
              <div className="space-y-1">
                <p className="text-sm text-muted-foreground">Buying Power</p>
                <p className="text-2xl font-bold">
                  {formatCurrency(accountSnapshot.buying_power)}
                </p>
              </div>
              <div className="space-y-1">
                <p className="text-sm text-muted-foreground">Cash</p>
                <p className="text-2xl font-bold">
                  {formatCurrency(accountSnapshot.cash)}
                </p>
              </div>
            </div>
          ) : (
            <Alert>
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>No Data</AlertTitle>
              <AlertDescription>
                No account snapshot found. Please sync your Alpaca account.
              </AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>

      {/* Shadow Trades P&L Summary */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            {totalUnrealizedPnL >= 0 ? (
              <TrendingUp className="h-5 w-5 text-green-500" />
            ) : (
              <TrendingDown className="h-5 w-5 text-red-500" />
            )}
            Shadow Trading P&L
          </CardTitle>
          <CardDescription>
            Real-time performance of your shadow trades (paper trading)
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-1">
              <p className="text-sm text-muted-foreground">Open Positions</p>
              <p className="text-2xl font-bold">{openShadowTrades.length}</p>
            </div>
            <div className="space-y-1">
              <p className="text-sm text-muted-foreground">Total Unrealized P&L</p>
              <p
                className={`text-2xl font-bold ${
                  totalUnrealizedPnL >= 0 ? "text-green-500" : "text-red-500"
                }`}
              >
                {formatCurrency(totalUnrealizedPnL)}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Shadow Trades Table */}
      <Card>
        <CardHeader>
          <CardTitle>Shadow Trade History</CardTitle>
          <CardDescription>
            Your shadow trades (users/{"{uid}"}/shadowTradeHistory)
          </CardDescription>
        </CardHeader>
        <CardContent>
          {shadowTradesLoading ? (
            <div className="space-y-2">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          ) : shadowTradesError ? (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>Error</AlertTitle>
              <AlertDescription>{shadowTradesError.message}</AlertDescription>
            </Alert>
          ) : shadowTrades.length === 0 ? (
            <Alert>
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>No Trades</AlertTitle>
              <AlertDescription>
                You haven't executed any shadow trades yet.
              </AlertDescription>
            </Alert>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Symbol</TableHead>
                    <TableHead>Side</TableHead>
                    <TableHead>Quantity</TableHead>
                    <TableHead>Entry Price</TableHead>
                    <TableHead>Current Price</TableHead>
                    <TableHead>P&L</TableHead>
                    <TableHead>P&L %</TableHead>
                    <TableHead>Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {shadowTrades.slice(0, 10).map((trade) => {
                    const pnl = parseFloat(trade.current_pnl || "0");
                    const pnlPercent = parseFloat(trade.pnl_percent || "0");
                    
                    return (
                      <TableRow key={trade.shadow_id || trade.id}>
                        <TableCell className="font-medium">
                          {trade.symbol}
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant={trade.side === "BUY" ? "default" : "secondary"}
                          >
                            {trade.side}
                          </Badge>
                        </TableCell>
                        <TableCell>{trade.quantity}</TableCell>
                        <TableCell>{formatCurrency(trade.entry_price)}</TableCell>
                        <TableCell>{formatCurrency(trade.current_price)}</TableCell>
                        <TableCell
                          className={pnl >= 0 ? "text-green-500" : "text-red-500"}
                        >
                          {formatCurrency(pnl)}
                        </TableCell>
                        <TableCell
                          className={pnlPercent >= 0 ? "text-green-500" : "text-red-500"}
                        >
                          {formatPercent(pnlPercent)}
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant={trade.status === "OPEN" ? "default" : "outline"}
                          >
                            {trade.status}
                          </Badge>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Trading Signals */}
      <Card>
        <CardHeader>
          <CardTitle>Recent Trading Signals</CardTitle>
          <CardDescription>
            AI-generated signals (users/{"{uid}"}/signals)
          </CardDescription>
        </CardHeader>
        <CardContent>
          {signalsLoading ? (
            <div className="space-y-2">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          ) : signalsError ? (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>Error</AlertTitle>
              <AlertDescription>{signalsError.message}</AlertDescription>
            </Alert>
          ) : signals.length === 0 ? (
            <Alert>
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>No Signals</AlertTitle>
              <AlertDescription>
                No trading signals have been generated yet.
              </AlertDescription>
            </Alert>
          ) : (
            <div className="space-y-4">
              {signals.slice(0, 5).map((signal) => (
                <div
                  key={signal.id}
                  className="flex items-center justify-between border-b pb-3 last:border-0"
                >
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <Badge>{signal.action}</Badge>
                      <span className="font-medium">{signal.symbol}</span>
                      {signal.strategy && (
                        <span className="text-xs text-muted-foreground">
                          ({signal.strategy})
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-muted-foreground">
                      {signal.reasoning}
                    </p>
                  </div>
                  <div className="text-right">
                    {signal.confidence && (
                      <p className="text-sm font-medium">
                        {(signal.confidence * 100).toFixed(0)}% confidence
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Data Isolation Verification */}
      <Alert>
        <AlertCircle className="h-4 w-4" />
        <AlertTitle>Multi-Tenant SaaS Architecture</AlertTitle>
        <AlertDescription>
          All data displayed here is isolated by your Firebase Auth UID. No other user
          can access your trading data, and you cannot access theirs. Firestore security
          rules enforce this at the database level.
        </AlertDescription>
      </Alert>
    </div>
  );
};
