/**
 * BacktestChart Component
 * 
 * Visualizes backtesting results with:
 * - Equity curve vs Buy-and-Hold benchmark
 * - Performance metrics (Sharpe, Drawdown, Win Rate)
 * - Trade history table
 * - Interactive tooltips and zoom
 */

import React, { useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  TooltipProps,
} from "recharts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { TrendingUp, TrendingDown, Activity, DollarSign } from "lucide-react";

interface EquityPoint {
  timestamp: string;
  equity: number;
  cash?: number;
  position_value?: number;
  num_positions?: number;
}

interface BenchmarkPoint {
  timestamp: string;
  equity: number;
}

interface Trade {
  timestamp: string;
  symbol: string;
  side: "buy" | "sell";
  quantity: number;
  price: number;
  type: "entry" | "exit";
  pnl?: number;
}

interface Metrics {
  initial_capital: number;
  final_equity: number;
  total_return: number;
  benchmark_return: number;
  alpha: number;
  sharpe_ratio: number;
  max_drawdown: number;
  win_rate: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  avg_win: number;
  avg_loss: number;
  profit_factor: number;
}

interface BacktestResults {
  metrics: Metrics;
  equity_curve: EquityPoint[];
  benchmark_curve: BenchmarkPoint[];
  trades: Trade[];
  config: {
    symbol: string;
    start_date: string;
    end_date: string;
    initial_capital: number;
    strategy: string;
  };
}

interface BacktestChartProps {
  results: BacktestResults;
}

const CustomTooltip: React.FC<TooltipProps<number, string>> = ({ active, payload, label }) => {
  if (active && payload && payload.length) {
    const date = new Date(label).toLocaleString();
    return (
      <div className="bg-background border border-border p-3 rounded-lg shadow-lg">
        <p className="text-sm font-medium mb-2">{date}</p>
        {payload.map((entry, index) => (
          <p key={index} className="text-sm" style={{ color: entry.color }}>
            {entry.name}: ${entry.value?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </p>
        ))}
      </div>
    );
  }
  return null;
};

const MetricCard: React.FC<{
  title: string;
  value: string | number;
  subtitle?: string;
  icon?: React.ReactNode;
  trend?: "up" | "down" | "neutral";
}> = ({ title, value, subtitle, icon, trend }) => {
  const trendColor = trend === "up" ? "text-green-500" : trend === "down" ? "text-red-500" : "text-muted-foreground";
  
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium">{title}</CardTitle>
        {icon && <div className={trendColor}>{icon}</div>}
      </CardHeader>
      <CardContent>
        <div className={`text-2xl font-bold ${trendColor}`}>{value}</div>
        {subtitle && <p className="text-xs text-muted-foreground mt-1">{subtitle}</p>}
      </CardContent>
    </Card>
  );
};

export const BacktestChart: React.FC<BacktestChartProps> = ({ results }) => {
  const [activeTab, setActiveTab] = useState("overview");

  // Merge equity and benchmark curves for chart
  const chartData = results.equity_curve.map((point, index) => ({
    timestamp: point.timestamp,
    strategy: point.equity,
    benchmark: results.benchmark_curve[index]?.equity || 0,
  }));

  // Format metrics
  const formatPercent = (value: number) => `${(value * 100).toFixed(2)}%`;
  const formatCurrency = (value: number) => `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  const formatNumber = (value: number, decimals: number = 2) => value.toFixed(decimals);

  const { metrics, config } = results;

  // Determine trend
  const returnTrend = metrics.total_return > 0 ? "up" : metrics.total_return < 0 ? "down" : "neutral";
  const alphaTrend = metrics.alpha > 0 ? "up" : metrics.alpha < 0 ? "down" : "neutral";

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-3xl font-bold tracking-tight">Backtest Results</h2>
        <p className="text-muted-foreground mt-2">
          {config.strategy} on {config.symbol} from {config.start_date} to {config.end_date}
        </p>
      </div>

      {/* Key Metrics Grid */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <MetricCard
          title="Total Return"
          value={formatPercent(metrics.total_return)}
          subtitle={`${formatCurrency(metrics.final_equity)} final equity`}
          icon={<TrendingUp className="h-4 w-4" />}
          trend={returnTrend}
        />
        <MetricCard
          title="Alpha"
          value={formatPercent(metrics.alpha)}
          subtitle={`vs ${formatPercent(metrics.benchmark_return)} benchmark`}
          icon={<Activity className="h-4 w-4" />}
          trend={alphaTrend}
        />
        <MetricCard
          title="Sharpe Ratio"
          value={formatNumber(metrics.sharpe_ratio)}
          subtitle="Risk-adjusted return"
          icon={<DollarSign className="h-4 w-4" />}
          trend={metrics.sharpe_ratio > 1 ? "up" : metrics.sharpe_ratio < 0 ? "down" : "neutral"}
        />
        <MetricCard
          title="Max Drawdown"
          value={formatPercent(metrics.max_drawdown)}
          subtitle="Largest peak-to-trough decline"
          icon={<TrendingDown className="h-4 w-4" />}
          trend="down"
        />
      </div>

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
        <TabsList className="grid w-full grid-cols-3">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="trades">Trades</TabsTrigger>
          <TabsTrigger value="metrics">Detailed Metrics</TabsTrigger>
        </TabsList>

        {/* Overview Tab */}
        <TabsContent value="overview" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Equity Curve</CardTitle>
              <CardDescription>
                Strategy performance vs Buy-and-Hold benchmark
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={400}>
                <LineChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                  <XAxis
                    dataKey="timestamp"
                    tickFormatter={(value) => new Date(value).toLocaleDateString()}
                    className="text-xs"
                  />
                  <YAxis
                    tickFormatter={(value) => `$${(value / 1000).toFixed(0)}k`}
                    className="text-xs"
                  />
                  <Tooltip content={<CustomTooltip />} />
                  <Legend />
                  <Line
                    type="monotone"
                    dataKey="strategy"
                    stroke="hsl(var(--primary))"
                    strokeWidth={2}
                    name="Strategy"
                    dot={false}
                  />
                  <Line
                    type="monotone"
                    dataKey="benchmark"
                    stroke="hsl(var(--muted-foreground))"
                    strokeWidth={2}
                    strokeDasharray="5 5"
                    name="Buy & Hold"
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>

          {/* Performance Summary */}
          <div className="grid gap-4 md:grid-cols-3">
            <Card>
              <CardHeader>
                <CardTitle className="text-sm font-medium">Win Rate</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{formatPercent(metrics.win_rate)}</div>
                <p className="text-xs text-muted-foreground mt-1">
                  {metrics.winning_trades} wins / {metrics.total_trades} trades
                </p>
                <div className="mt-2 flex gap-2">
                  <Badge variant="outline" className="text-green-500 border-green-500">
                    {metrics.winning_trades} W
                  </Badge>
                  <Badge variant="outline" className="text-red-500 border-red-500">
                    {metrics.losing_trades} L
                  </Badge>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-sm font-medium">Average Win</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold text-green-500">
                  {formatCurrency(metrics.avg_win)}
                </div>
                <p className="text-xs text-muted-foreground mt-1">
                  Per winning trade
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-sm font-medium">Average Loss</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold text-red-500">
                  {formatCurrency(metrics.avg_loss)}
                </div>
                <p className="text-xs text-muted-foreground mt-1">
                  Per losing trade
                </p>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* Trades Tab */}
        <TabsContent value="trades">
          <Card>
            <CardHeader>
              <CardTitle>Trade History</CardTitle>
              <CardDescription>
                All {results.trades.length} trades executed during the backtest
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b">
                      <th className="text-left p-2">Time</th>
                      <th className="text-left p-2">Symbol</th>
                      <th className="text-left p-2">Side</th>
                      <th className="text-right p-2">Quantity</th>
                      <th className="text-right p-2">Price</th>
                      <th className="text-left p-2">Type</th>
                      <th className="text-right p-2">PnL</th>
                    </tr>
                  </thead>
                  <tbody>
                    {results.trades.map((trade, index) => (
                      <tr key={index} className="border-b hover:bg-muted/50">
                        <td className="p-2">{new Date(trade.timestamp).toLocaleString()}</td>
                        <td className="p-2">{trade.symbol}</td>
                        <td className="p-2">
                          <Badge
                            variant={trade.side === "buy" ? "default" : "secondary"}
                            className={trade.side === "buy" ? "bg-green-500" : "bg-red-500"}
                          >
                            {trade.side.toUpperCase()}
                          </Badge>
                        </td>
                        <td className="text-right p-2">{trade.quantity.toFixed(0)}</td>
                        <td className="text-right p-2">${trade.price.toFixed(2)}</td>
                        <td className="p-2">
                          <Badge variant="outline">{trade.type}</Badge>
                        </td>
                        <td className={`text-right p-2 font-medium ${
                          trade.pnl && trade.pnl > 0 ? "text-green-500" :
                          trade.pnl && trade.pnl < 0 ? "text-red-500" :
                          "text-muted-foreground"
                        }`}>
                          {trade.pnl ? formatCurrency(trade.pnl) : "-"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Detailed Metrics Tab */}
        <TabsContent value="metrics">
          <Card>
            <CardHeader>
              <CardTitle>Detailed Performance Metrics</CardTitle>
              <CardDescription>
                Comprehensive statistical analysis of backtest results
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid gap-6 md:grid-cols-2">
                {/* Returns */}
                <div className="space-y-3">
                  <h3 className="font-semibold text-sm text-muted-foreground">RETURNS</h3>
                  <div className="space-y-2">
                    <div className="flex justify-between">
                      <span className="text-sm">Initial Capital</span>
                      <span className="font-medium">{formatCurrency(metrics.initial_capital)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-sm">Final Equity</span>
                      <span className="font-medium">{formatCurrency(metrics.final_equity)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-sm">Total Return</span>
                      <span className={`font-medium ${returnTrend === "up" ? "text-green-500" : "text-red-500"}`}>
                        {formatPercent(metrics.total_return)}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-sm">Benchmark Return</span>
                      <span className="font-medium">{formatPercent(metrics.benchmark_return)}</span>
                    </div>
                    <div className="flex justify-between pt-2 border-t">
                      <span className="text-sm font-semibold">Alpha</span>
                      <span className={`font-bold ${alphaTrend === "up" ? "text-green-500" : "text-red-500"}`}>
                        {formatPercent(metrics.alpha)}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Risk Metrics */}
                <div className="space-y-3">
                  <h3 className="font-semibold text-sm text-muted-foreground">RISK METRICS</h3>
                  <div className="space-y-2">
                    <div className="flex justify-between">
                      <span className="text-sm">Sharpe Ratio</span>
                      <span className="font-medium">{formatNumber(metrics.sharpe_ratio)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-sm">Max Drawdown</span>
                      <span className="font-medium text-red-500">{formatPercent(metrics.max_drawdown)}</span>
                    </div>
                  </div>
                </div>

                {/* Trade Statistics */}
                <div className="space-y-3">
                  <h3 className="font-semibold text-sm text-muted-foreground">TRADE STATISTICS</h3>
                  <div className="space-y-2">
                    <div className="flex justify-between">
                      <span className="text-sm">Total Trades</span>
                      <span className="font-medium">{metrics.total_trades}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-sm">Winning Trades</span>
                      <span className="font-medium text-green-500">{metrics.winning_trades}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-sm">Losing Trades</span>
                      <span className="font-medium text-red-500">{metrics.losing_trades}</span>
                    </div>
                    <div className="flex justify-between pt-2 border-t">
                      <span className="text-sm font-semibold">Win Rate</span>
                      <span className="font-bold">{formatPercent(metrics.win_rate)}</span>
                    </div>
                  </div>
                </div>

                {/* Win/Loss Analysis */}
                <div className="space-y-3">
                  <h3 className="font-semibold text-sm text-muted-foreground">WIN/LOSS ANALYSIS</h3>
                  <div className="space-y-2">
                    <div className="flex justify-between">
                      <span className="text-sm">Average Win</span>
                      <span className="font-medium text-green-500">{formatCurrency(metrics.avg_win)}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-sm">Average Loss</span>
                      <span className="font-medium text-red-500">{formatCurrency(metrics.avg_loss)}</span>
                    </div>
                    <div className="flex justify-between pt-2 border-t">
                      <span className="text-sm font-semibold">Profit Factor</span>
                      <span className="font-bold">{formatNumber(metrics.profit_factor)}</span>
                    </div>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
};

export default BacktestChart;
