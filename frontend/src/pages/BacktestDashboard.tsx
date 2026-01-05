import { useState } from "react";
import { DashboardHeader } from "@/components/DashboardHeader";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Separator } from "@/components/ui/separator";
import { Badge } from "@/components/ui/badge";
import { 
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  BarChart, Bar, Cell
} from "recharts";
import { Activity, TrendingUp, TrendingDown, DollarSign, Target, Zap, AlertCircle, CheckCircle2 } from "lucide-react";
import { toast } from "sonner";
import { getFunctions, httpsCallable } from "firebase/functions";

interface BacktestConfig {
  strategy: string;
  symbol: string;
  lookback_days: number;
  start_capital: number;
  slippage_bps: number;
  regime?: string;
  strategy_config?: Record<string, any>;
}

interface BacktestMetrics {
  total_return_pct: number;
  annualized_return_pct: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  max_drawdown_pct: number;
  volatility_annualized_pct: number;
  win_rate_pct: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  avg_win: number;
  avg_loss: number;
  profit_factor: number;
  final_equity: number;
  net_profit: number;
}

interface EquityPoint {
  timestamp: string;
  equity: number;
}

interface BacktestResults {
  success: boolean;
  backtest_id: string;
  strategy: string;
  metrics: BacktestMetrics;
  results: {
    equity_curve: EquityPoint[];
    trades: any[];
    final_equity: number;
  };
}

const BacktestDashboard = () => {
  const [config, setConfig] = useState<BacktestConfig>({
    strategy: "GammaScalper",
    symbol: "SPY",
    lookback_days: 30,
    start_capital: 100000,
    slippage_bps: 1,
    regime: undefined,
    strategy_config: {}
  });
  
  const [results, setResults] = useState<BacktestResults | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleRunBacktest = async () => {
    setLoading(true);
    setError(null);
    
    try {
      const functions = getFunctions();
      const runBacktest = httpsCallable(functions, "run_backtest");
      
      toast.info("Starting backtest...", {
        description: `Testing ${config.strategy} on ${config.symbol} for ${config.lookback_days} days`
      });
      
      const response = await runBacktest({
        strategy: config.strategy,
        config: config.strategy_config,
        backtest_config: {
          symbol: config.symbol,
          lookback_days: config.lookback_days,
          start_capital: config.start_capital,
          slippage_bps: config.slippage_bps,
          regime: config.regime
        }
      });
      
      const data = response.data as BacktestResults;
      setResults(data);
      
      toast.success("Backtest completed!", {
        description: `Return: ${data.metrics.total_return_pct.toFixed(2)}%, Sharpe: ${data.metrics.sharpe_ratio.toFixed(2)}`
      });
      
    } catch (err: any) {
      console.error("Backtest error:", err);
      const errorMsg = err.message || "Failed to run backtest";
      setError(errorMsg);
      toast.error("Backtest failed", {
        description: errorMsg
      });
    } finally {
      setLoading(false);
    }
  };

  // Format equity curve data for chart
  const equityCurveData = results?.results.equity_curve.map((point, index) => ({
    timestamp: new Date(point.timestamp).toLocaleDateString(),
    equity: point.equity,
    benchmarkEquity: config.start_capital, // Flat benchmark line
    index: index
  })) || [];

  // Calculate daily returns for distribution chart
  const returnsDistribution = results?.results.equity_curve.reduce((acc: any[], point, index, arr) => {
    if (index === 0) return acc;
    const prevEquity = arr[index - 1].equity;
    const returnPct = ((point.equity - prevEquity) / prevEquity) * 100;
    acc.push({
      return: returnPct,
      count: 1
    });
    return acc;
  }, []) || [];

  // Bin returns for histogram
  const returnsBins = [-5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5];
  const returnsHistogram = returnsBins.map((bin, index) => {
    const nextBin = returnsBins[index + 1] || 100;
    const count = returnsDistribution.filter(r => r.return >= bin && r.return < nextBin).length;
    return {
      range: `${bin}% to ${nextBin}%`,
      count: count,
      bin: bin
    };
  });

  const MetricCard = ({ 
    title, 
    value, 
    subtitle, 
    icon: Icon, 
    trend 
  }: { 
    title: string; 
    value: string | number; 
    subtitle?: string; 
    icon: any; 
    trend?: "up" | "down" | "neutral";
  }) => (
    <Card className="glass-card">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium">{title}</CardTitle>
        <Icon className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent>
        <div className="flex items-baseline space-x-2">
          <div className="text-2xl font-bold">{value}</div>
          {trend && (
            <div className={`flex items-center text-xs ${
              trend === "up" ? "text-green-500" : 
              trend === "down" ? "text-red-500" : 
              "text-muted-foreground"
            }`}>
              {trend === "up" && <TrendingUp className="h-3 w-3 mr-1" />}
              {trend === "down" && <TrendingDown className="h-3 w-3 mr-1" />}
            </div>
          )}
        </div>
        {subtitle && (
          <p className="text-xs text-muted-foreground mt-1">{subtitle}</p>
        )}
      </CardContent>
    </Card>
  );

  return (
    <div className="min-h-screen bg-background">
      <DashboardHeader
        currentSymbol={config.symbol}
        onSymbolChange={(symbol) => setConfig({ ...config, symbol })}
        environment="backtest"
        equity={results?.metrics.final_equity || config.start_capital}
        dayPnl={results?.metrics.net_profit || 0}
        dayPnlPct={results?.metrics.total_return_pct || 0}
      />

      <div className="p-6 space-y-6">
        {/* Configuration Section */}
        <Card className="glass-card">
          <CardHeader>
            <CardTitle>Backtest Configuration</CardTitle>
            <CardDescription>
              Configure your strategy backtest parameters and run historical simulations
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
              <div className="space-y-2">
                <Label htmlFor="strategy">Strategy</Label>
                <Select
                  value={config.strategy}
                  onValueChange={(value) => setConfig({ ...config, strategy: value })}
                >
                  <SelectTrigger id="strategy">
                    <SelectValue placeholder="Select strategy" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="GammaScalper">Gamma Scalper (0DTE)</SelectItem>
                    <SelectItem value="DeltaMomentumStrategy">Delta Momentum</SelectItem>
                    <SelectItem value="CongressionalAlphaStrategy">Congressional Alpha</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="symbol">Symbol</Label>
                <Input
                  id="symbol"
                  value={config.symbol}
                  onChange={(e) => setConfig({ ...config, symbol: e.target.value.toUpperCase() })}
                  placeholder="SPY"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="lookback_days">Lookback Days</Label>
                <Input
                  id="lookback_days"
                  type="number"
                  value={config.lookback_days}
                  onChange={(e) => setConfig({ ...config, lookback_days: parseInt(e.target.value) })}
                  min={1}
                  max={365}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="start_capital">Starting Capital ($)</Label>
                <Input
                  id="start_capital"
                  type="number"
                  value={config.start_capital}
                  onChange={(e) => setConfig({ ...config, start_capital: parseFloat(e.target.value) })}
                  min={1000}
                  step={1000}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="slippage">Slippage (bps)</Label>
                <Input
                  id="slippage"
                  type="number"
                  value={config.slippage_bps}
                  onChange={(e) => setConfig({ ...config, slippage_bps: parseInt(e.target.value) })}
                  min={0}
                  max={100}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="regime">Market Regime (Optional)</Label>
                <Select
                  value={config.regime || "auto"}
                  onValueChange={(value) => setConfig({ ...config, regime: value === "auto" ? undefined : value })}
                >
                  <SelectTrigger id="regime">
                    <SelectValue placeholder="Auto-detect" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="auto">Auto-detect</SelectItem>
                    <SelectItem value="LONG_GAMMA">Long Gamma (Stabilizing)</SelectItem>
                    <SelectItem value="SHORT_GAMMA">Short Gamma (Volatile)</SelectItem>
                    <SelectItem value="NEUTRAL">Neutral</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            <Separator />

            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2">
                <CheckCircle2 className="h-4 w-4 text-green-500" />
                <span className="text-sm text-muted-foreground">
                  No look-ahead bias • Transaction costs included • Greeks simulation enabled
                </span>
              </div>
              <Button
                onClick={handleRunBacktest}
                disabled={loading}
                size="lg"
                className="bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700"
              >
                {loading ? (
                  <>
                    <Activity className="mr-2 h-4 w-4 animate-spin" />
                    Running Backtest...
                  </>
                ) : (
                  <>
                    <Zap className="mr-2 h-4 w-4" />
                    Run Backtest
                  </>
                )}
              </Button>
            </div>

            {error && (
              <div className="flex items-center space-x-2 text-sm text-red-500 bg-red-500/10 p-3 rounded-md">
                <AlertCircle className="h-4 w-4" />
                <span>{error}</span>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Results Section */}
        {results && (
          <>
            {/* Key Metrics Cards */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
              <MetricCard
                title="Total Return"
                value={`${results.metrics.total_return_pct.toFixed(2)}%`}
                subtitle={`$${results.metrics.net_profit.toFixed(2)} profit`}
                icon={DollarSign}
                trend={results.metrics.total_return_pct > 0 ? "up" : "down"}
              />
              <MetricCard
                title="Sharpe Ratio"
                value={results.metrics.sharpe_ratio.toFixed(2)}
                subtitle="Risk-adjusted return"
                icon={Target}
                trend={results.metrics.sharpe_ratio > 1 ? "up" : results.metrics.sharpe_ratio < 0 ? "down" : "neutral"}
              />
              <MetricCard
                title="Max Drawdown"
                value={`${results.metrics.max_drawdown_pct.toFixed(2)}%`}
                subtitle="Peak-to-trough loss"
                icon={TrendingDown}
                trend="down"
              />
              <MetricCard
                title="Win Rate"
                value={`${results.metrics.win_rate_pct.toFixed(1)}%`}
                subtitle={`${results.metrics.total_trades} trades`}
                icon={Activity}
                trend={results.metrics.win_rate_pct > 50 ? "up" : "down"}
              />
            </div>

            {/* Charts */}
            <Tabs defaultValue="equity" className="w-full">
              <TabsList className="grid w-full grid-cols-3 glass-subtle">
                <TabsTrigger value="equity">Equity Curve</TabsTrigger>
                <TabsTrigger value="metrics">Performance Metrics</TabsTrigger>
                <TabsTrigger value="trades">Trade Analysis</TabsTrigger>
              </TabsList>

              <TabsContent value="equity" className="space-y-4">
                <Card className="glass-card">
                  <CardHeader>
                    <CardTitle>Equity Curve</CardTitle>
                    <CardDescription>
                      Portfolio value over time vs. starting capital benchmark
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <ResponsiveContainer width="100%" height={400}>
                      <LineChart data={equityCurveData}>
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
                        <XAxis 
                          dataKey="timestamp" 
                          stroke="rgba(255,255,255,0.5)"
                          tick={{ fontSize: 12 }}
                          angle={-45}
                          textAnchor="end"
                          height={80}
                        />
                        <YAxis 
                          stroke="rgba(255,255,255,0.5)"
                          tick={{ fontSize: 12 }}
                          tickFormatter={(value) => `$${(value / 1000).toFixed(0)}k`}
                        />
                        <Tooltip
                          contentStyle={{
                            backgroundColor: "rgba(0,0,0,0.8)",
                            border: "1px solid rgba(255,255,255,0.1)",
                            borderRadius: "8px"
                          }}
                          formatter={(value: any) => [`$${value.toFixed(2)}`, "Equity"]}
                        />
                        <Legend />
                        <Line
                          type="monotone"
                          dataKey="benchmarkEquity"
                          stroke="rgba(255,255,255,0.3)"
                          strokeWidth={1}
                          strokeDasharray="5 5"
                          dot={false}
                          name="Starting Capital"
                        />
                        <Line
                          type="monotone"
                          dataKey="equity"
                          stroke="#3b82f6"
                          strokeWidth={2}
                          dot={false}
                          name="Portfolio Equity"
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  </CardContent>
                </Card>
              </TabsContent>

              <TabsContent value="metrics" className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <Card className="glass-card">
                    <CardHeader>
                      <CardTitle>Return Metrics</CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Total Return</span>
                        <Badge variant={results.metrics.total_return_pct > 0 ? "default" : "destructive"}>
                          {results.metrics.total_return_pct.toFixed(2)}%
                        </Badge>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Annualized Return</span>
                        <Badge variant="outline">{results.metrics.annualized_return_pct.toFixed(2)}%</Badge>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Net Profit</span>
                        <span className="font-semibold">${results.metrics.net_profit.toFixed(2)}</span>
                      </div>
                      <Separator />
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Final Equity</span>
                        <span className="font-semibold">${results.metrics.final_equity.toFixed(2)}</span>
                      </div>
                    </CardContent>
                  </Card>

                  <Card className="glass-card">
                    <CardHeader>
                      <CardTitle>Risk Metrics</CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Sharpe Ratio</span>
                        <Badge variant="outline">{results.metrics.sharpe_ratio.toFixed(2)}</Badge>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Sortino Ratio</span>
                        <Badge variant="outline">{results.metrics.sortino_ratio.toFixed(2)}</Badge>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Max Drawdown</span>
                        <Badge variant="destructive">{results.metrics.max_drawdown_pct.toFixed(2)}%</Badge>
                      </div>
                      <Separator />
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Volatility (Annual)</span>
                        <span className="font-semibold">{results.metrics.volatility_annualized_pct.toFixed(2)}%</span>
                      </div>
                    </CardContent>
                  </Card>
                </div>

                <Card className="glass-card">
                  <CardHeader>
                    <CardTitle>Returns Distribution</CardTitle>
                    <CardDescription>Distribution of daily returns</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <ResponsiveContainer width="100%" height={300}>
                      <BarChart data={returnsHistogram}>
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
                        <XAxis 
                          dataKey="range" 
                          stroke="rgba(255,255,255,0.5)"
                          tick={{ fontSize: 10 }}
                          angle={-45}
                          textAnchor="end"
                          height={80}
                        />
                        <YAxis stroke="rgba(255,255,255,0.5)" tick={{ fontSize: 12 }} />
                        <Tooltip
                          contentStyle={{
                            backgroundColor: "rgba(0,0,0,0.8)",
                            border: "1px solid rgba(255,255,255,0.1)",
                            borderRadius: "8px"
                          }}
                        />
                        <Bar dataKey="count" fill="#3b82f6">
                          {returnsHistogram.map((entry, index) => (
                            <Cell key={`cell-${index}`} fill={entry.bin < 0 ? "#ef4444" : "#10b981"} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </CardContent>
                </Card>
              </TabsContent>

              <TabsContent value="trades" className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                  <Card className="glass-card">
                    <CardHeader className="pb-2">
                      <CardTitle className="text-sm font-medium">Total Trades</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <div className="text-2xl font-bold">{results.metrics.total_trades}</div>
                      <p className="text-xs text-muted-foreground">
                        {results.metrics.winning_trades} wins / {results.metrics.losing_trades} losses
                      </p>
                    </CardContent>
                  </Card>

                  <Card className="glass-card">
                    <CardHeader className="pb-2">
                      <CardTitle className="text-sm font-medium">Win Rate</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <div className="text-2xl font-bold">{results.metrics.win_rate_pct.toFixed(1)}%</div>
                      <p className="text-xs text-muted-foreground">
                        {results.metrics.winning_trades} winning trades
                      </p>
                    </CardContent>
                  </Card>

                  <Card className="glass-card">
                    <CardHeader className="pb-2">
                      <CardTitle className="text-sm font-medium">Avg Win / Loss</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <div className="text-2xl font-bold text-green-500">${results.metrics.avg_win.toFixed(2)}</div>
                      <p className="text-xs text-red-500">
                        -${results.metrics.avg_loss.toFixed(2)} avg loss
                      </p>
                    </CardContent>
                  </Card>

                  <Card className="glass-card">
                    <CardHeader className="pb-2">
                      <CardTitle className="text-sm font-medium">Profit Factor</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <div className="text-2xl font-bold">{results.metrics.profit_factor.toFixed(2)}</div>
                      <p className="text-xs text-muted-foreground">
                        Gross profit / loss ratio
                      </p>
                    </CardContent>
                  </Card>
                </div>
              </TabsContent>
            </Tabs>
          </>
        )}

        {/* Empty State */}
        {!results && !loading && (
          <Card className="glass-card">
            <CardContent className="flex flex-col items-center justify-center py-16">
              <Activity className="h-16 w-16 text-muted-foreground mb-4" />
              <h3 className="text-lg font-semibold mb-2">No Backtest Results Yet</h3>
              <p className="text-muted-foreground text-center mb-4">
                Configure your strategy parameters above and click "Run Backtest" to see historical performance
              </p>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
};

export default BacktestDashboard;
