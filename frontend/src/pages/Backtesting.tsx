/**
 * Backtesting Page
 * 
 * Allows users to run and visualize strategy backtests
 */

import React, { useState } from "react";
import { BacktestChart } from "@/components/BacktestChart";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Loader2, PlayCircle, Info } from "lucide-react";

interface BacktestConfig {
  strategy: string;
  symbol: string;
  start_date: string;
  end_date: string;
  initial_capital: number;
}

const BacktestingPage: React.FC = () => {
  const [config, setConfig] = useState<BacktestConfig>({
    strategy: "gamma_scalper",
    symbol: "SPY",
    start_date: "",
    end_date: "",
    initial_capital: 100000,
  });
  
  const [results, setResults] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Set default dates (last 30 days)
  React.useEffect(() => {
    const end = new Date();
    const start = new Date();
    start.setDate(start.getDate() - 30);
    
    setConfig((prev) => ({
      ...prev,
      start_date: start.toISOString().split("T")[0],
      end_date: end.toISOString().split("T")[0],
    }));
  }, []);

  const handleRunBacktest = async () => {
    setLoading(true);
    setError(null);
    setResults(null);

    try {
      // Call Cloud Function to run backtest
      const response = await fetch(
        `${import.meta.env.VITE_FUNCTIONS_URL || "http://localhost:5001"}/run_backtest`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify(config),
        }
      );

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();
      setResults(data);
    } catch (err) {
      console.error("Backtest error:", err);
      setError(err instanceof Error ? err.message : "Failed to run backtest");
    } finally {
      setLoading(false);
    }
  };

  const handleConfigChange = (key: keyof BacktestConfig, value: string | number) => {
    setConfig((prev) => ({ ...prev, [key]: value }));
  };

  return (
    <div className="container mx-auto py-6 space-y-6">
      <div>
        <h1 className="text-4xl font-bold tracking-tight">Strategy Backtesting</h1>
        <p className="text-muted-foreground mt-2">
          Test your trading strategies on historical data to evaluate performance before going live
        </p>
      </div>

      {/* Configuration Card */}
      <Card>
        <CardHeader>
          <CardTitle>Backtest Configuration</CardTitle>
          <CardDescription>
            Configure your backtest parameters
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-6 md:grid-cols-2">
            {/* Strategy Selection */}
            <div className="space-y-2">
              <Label htmlFor="strategy">Strategy</Label>
              <Select
                value={config.strategy}
                onValueChange={(value) => handleConfigChange("strategy", value)}
              >
                <SelectTrigger id="strategy">
                  <SelectValue placeholder="Select a strategy" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="gamma_scalper">0DTE Gamma Scalper</SelectItem>
                  <SelectItem value="example_strategy">Example Strategy</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Symbol */}
            <div className="space-y-2">
              <Label htmlFor="symbol">Symbol</Label>
              <Input
                id="symbol"
                value={config.symbol}
                onChange={(e) => handleConfigChange("symbol", e.target.value.toUpperCase())}
                placeholder="SPY"
              />
            </div>

            {/* Start Date */}
            <div className="space-y-2">
              <Label htmlFor="start_date">Start Date</Label>
              <Input
                id="start_date"
                type="date"
                value={config.start_date}
                onChange={(e) => handleConfigChange("start_date", e.target.value)}
              />
            </div>

            {/* End Date */}
            <div className="space-y-2">
              <Label htmlFor="end_date">End Date</Label>
              <Input
                id="end_date"
                type="date"
                value={config.end_date}
                onChange={(e) => handleConfigChange("end_date", e.target.value)}
              />
            </div>

            {/* Initial Capital */}
            <div className="space-y-2">
              <Label htmlFor="initial_capital">Initial Capital ($)</Label>
              <Input
                id="initial_capital"
                type="number"
                value={config.initial_capital}
                onChange={(e) => handleConfigChange("initial_capital", parseFloat(e.target.value))}
                min="1000"
                step="1000"
              />
            </div>
          </div>

          {/* Info Alert */}
          <Alert className="mt-6">
            <Info className="h-4 w-4" />
            <AlertTitle>Data Source</AlertTitle>
            <AlertDescription>
              Backtests use 1-minute historical bars from Alpaca. Ensure you have valid API credentials configured.
            </AlertDescription>
          </Alert>

          {/* Run Button */}
          <div className="mt-6">
            <Button
              onClick={handleRunBacktest}
              disabled={loading}
              size="lg"
              className="w-full md:w-auto"
            >
              {loading ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Running Backtest...
                </>
              ) : (
                <>
                  <PlayCircle className="mr-2 h-4 w-4" />
                  Run Backtest
                </>
              )}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Error Display */}
      {error && (
        <Alert variant="destructive">
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* Results Display */}
      {results && <BacktestChart results={results} />}

      {/* Instructions */}
      {!results && !loading && (
        <Card>
          <CardHeader>
            <CardTitle>Getting Started</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <h3 className="font-semibold mb-2">1. Select a Strategy</h3>
              <p className="text-sm text-muted-foreground">
                Choose from available trading strategies. Each strategy has its own logic and risk profile.
              </p>
            </div>
            <div>
              <h3 className="font-semibold mb-2">2. Configure Parameters</h3>
              <p className="text-sm text-muted-foreground">
                Set the symbol, date range, and initial capital. Longer periods provide more reliable statistics.
              </p>
            </div>
            <div>
              <h3 className="font-semibold mb-2">3. Run and Analyze</h3>
              <p className="text-sm text-muted-foreground">
                Click "Run Backtest" to simulate the strategy. Review the equity curve, metrics, and trade history.
              </p>
            </div>
            <div>
              <h3 className="font-semibold mb-2">4. Interpret Results</h3>
              <p className="text-sm text-muted-foreground">
                Key metrics to evaluate:
              </p>
              <ul className="list-disc list-inside text-sm text-muted-foreground ml-4 mt-2 space-y-1">
                <li><strong>Sharpe Ratio:</strong> Risk-adjusted return ({">"} 1.0 is good)</li>
                <li><strong>Max Drawdown:</strong> Largest peak-to-trough decline (lower is better)</li>
                <li><strong>Win Rate:</strong> Percentage of profitable trades</li>
                <li><strong>Alpha:</strong> Excess return vs buy-and-hold benchmark</li>
              </ul>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
};

export default BacktestingPage;
