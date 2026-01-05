import React, { useState } from 'react';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Loader2, AlertCircle, CheckCircle2, TrendingDown, TrendingUp } from 'lucide-react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Area,
  AreaChart,
  BarChart,
  Bar,
  Cell,
} from 'recharts';

interface StressTestResult {
  success: boolean;
  passes_stress_test: boolean;
  var_95: number;
  var_99: number;
  cvar_95: number;
  survival_rate: number;
  mean_sharpe: number;
  worst_drawdown: number;
  mean_return: number;
  failure_reasons: string[];
  report: {
    status: string;
    interpretation: string;
    risk_summary: Record<string, any>;
    performance_summary: Record<string, any>;
    final_equity_percentiles: Record<string, number>;
  };
  timestamp: string;
}

interface PathData {
  path_id: string;
  is_black_swan: boolean;
  final_equity: number;
  total_return: number;
  max_drawdown: number;
  sharpe_ratio: number;
  equity_curve_sample: number[];
}

const StressTest: React.FC = () => {
  const [isRunning, setIsRunning] = useState(false);
  const [results, setResults] = useState<StressTestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Configuration state
  const [strategyName, setStrategyName] = useState('sector_rotation');
  const [numSimulations, setNumSimulations] = useState(1000);
  const [numDays, setNumDays] = useState(252);
  const [blackSwanProb, setBlackSwanProb] = useState(0.10);

  const runStressTest = async () => {
    setIsRunning(true);
    setError(null);
    setResults(null);

    try {
      // Get tenant ID from local storage or context
      const tenantId = localStorage.getItem('tenantId') || 'demo-tenant';

      const response = await fetch(
        `/api/analytics/stress-test?tenant_id=${tenantId}`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            strategy_name: strategyName,
            strategy_config: {},
            num_simulations: numSimulations,
            num_days: numDays,
            black_swan_probability: blackSwanProb,
            save_to_firestore: true,
          }),
        }
      );

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || 'Stress test failed');
      }

      const data = await response.json();
      setResults(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error occurred');
    } finally {
      setIsRunning(false);
    }
  };

  // Prepare data for charts
  const getEquityDistributionData = () => {
    if (!results?.report?.final_equity_percentiles) return [];

    const percentiles = results.report.final_equity_percentiles;
    return [
      { percentile: 'p1', value: percentiles.p1, label: '1%' },
      { percentile: 'p5', value: percentiles.p5, label: '5%' },
      { percentile: 'p25', value: percentiles.p25, label: '25%' },
      { percentile: 'p50', value: percentiles.p50, label: '50% (Median)' },
      { percentile: 'p75', value: percentiles.p75, label: '75%' },
      { percentile: 'p95', value: percentiles.p95, label: '95%' },
      { percentile: 'p99', value: percentiles.p99, label: '99%' },
    ];
  };

  const getRiskMetricsData = () => {
    if (!results) return [];

    return [
      {
        metric: 'VaR (95%)',
        value: results.var_95 * 100,
        threshold: 15,
        pass: results.var_95 <= 0.15,
      },
      {
        metric: 'Max Drawdown',
        value: results.worst_drawdown * 100,
        threshold: 25,
        pass: results.worst_drawdown <= 0.25,
      },
      {
        metric: 'Survival Rate',
        value: results.survival_rate * 100,
        threshold: 99,
        pass: results.survival_rate >= 0.99,
      },
    ];
  };

  const formatPercent = (value: number) => `${(value * 100).toFixed(2)}%`;
  const formatCurrency = (value: number) => `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  return (
    <div className="container mx-auto p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Monte Carlo Stress Test</h1>
          <p className="text-muted-foreground mt-2">
            Simulate 1,000+ market scenarios to validate strategy robustness before live trading
          </p>
        </div>
      </div>

      {/* Configuration Panel */}
      <Card>
        <CardHeader>
          <CardTitle>Test Configuration</CardTitle>
          <CardDescription>
            Configure simulation parameters and run stress test
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="space-y-2">
              <Label htmlFor="strategy">Strategy</Label>
              <Select value={strategyName} onValueChange={setStrategyName}>
                <SelectTrigger id="strategy">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="sector_rotation">Sector Rotation</SelectItem>
                  <SelectItem value="gamma_scalper">Gamma Scalper</SelectItem>
                  <SelectItem value="example_strategy">Example Strategy</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="simulations">Simulations</Label>
              <Input
                id="simulations"
                type="number"
                value={numSimulations}
                onChange={(e) => setNumSimulations(parseInt(e.target.value))}
                min={100}
                max={10000}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="days">Trading Days</Label>
              <Input
                id="days"
                type="number"
                value={numDays}
                onChange={(e) => setNumDays(parseInt(e.target.value))}
                min={21}
                max={1260}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="blackswan">Black Swan %</Label>
              <Input
                id="blackswan"
                type="number"
                value={blackSwanProb * 100}
                onChange={(e) => setBlackSwanProb(parseFloat(e.target.value) / 100)}
                min={0}
                max={50}
                step={1}
              />
            </div>
          </div>

          <Button
            onClick={runStressTest}
            disabled={isRunning}
            className="w-full md:w-auto"
          >
            {isRunning ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Running {numSimulations} Simulations...
              </>
            ) : (
              'Run Stress Test'
            )}
          </Button>
        </CardContent>
      </Card>

      {/* Error Alert */}
      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* Results */}
      {results && (
        <>
          {/* Pass/Fail Summary */}
          <Card className={results.passes_stress_test ? 'border-green-500' : 'border-red-500'}>
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle className="flex items-center gap-2">
                  {results.passes_stress_test ? (
                    <>
                      <CheckCircle2 className="h-6 w-6 text-green-600" />
                      <span className="text-green-600">STRESS TEST PASSED</span>
                    </>
                  ) : (
                    <>
                      <AlertCircle className="h-6 w-6 text-red-600" />
                      <span className="text-red-600">STRESS TEST FAILED</span>
                    </>
                  )}
                </CardTitle>
                <Badge variant={results.passes_stress_test ? 'default' : 'destructive'}>
                  {results.report.status}
                </Badge>
              </div>
              <CardDescription className="mt-4">
                {results.report.interpretation}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {results.failure_reasons.length > 0 && (
                <Alert variant="destructive">
                  <AlertTitle>Failure Reasons</AlertTitle>
                  <AlertDescription>
                    <ul className="list-disc list-inside space-y-1 mt-2">
                      {results.failure_reasons.map((reason, idx) => (
                        <li key={idx}>{reason}</li>
                      ))}
                    </ul>
                  </AlertDescription>
                </Alert>
              )}
            </CardContent>
          </Card>

          {/* Risk Metrics Cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <Card>
              <CardHeader className="pb-2">
                <CardDescription>Value at Risk (95%)</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold text-red-600">
                  {formatPercent(results.var_95)}
                </div>
                <p className="text-xs text-muted-foreground mt-1">
                  Max loss in worst 5% of scenarios
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardDescription>Expected Shortfall</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold text-red-600">
                  {formatPercent(results.cvar_95)}
                </div>
                <p className="text-xs text-muted-foreground mt-1">
                  Average loss in tail scenarios
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardDescription>Sharpe Ratio</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold text-blue-600">
                  {results.mean_sharpe.toFixed(2)}
                </div>
                <p className="text-xs text-muted-foreground mt-1">
                  Risk-adjusted return
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardDescription>Survival Rate</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold text-green-600">
                  {formatPercent(results.survival_rate)}
                </div>
                <p className="text-xs text-muted-foreground mt-1">
                  Paths without liquidation
                </p>
              </CardContent>
            </Card>
          </div>

          {/* Risk Metrics Bar Chart */}
          <Card>
            <CardHeader>
              <CardTitle>Risk Metrics vs. Thresholds</CardTitle>
              <CardDescription>
                Green bars indicate passing criteria, red bars indicate failures
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={getRiskMetricsData()}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="metric" />
                  <YAxis />
                  <Tooltip
                    formatter={(value: number) => `${value.toFixed(2)}%`}
                  />
                  <Bar dataKey="value" name="Actual">
                    {getRiskMetricsData().map((entry, index) => (
                      <Cell
                        key={`cell-${index}`}
                        fill={entry.pass ? '#22c55e' : '#ef4444'}
                      />
                    ))}
                  </Bar>
                  <Bar dataKey="threshold" name="Threshold" fill="#94a3b8" />
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>

          {/* Final Equity Distribution */}
          <Card>
            <CardHeader>
              <CardTitle>Final Equity Distribution</CardTitle>
              <CardDescription>
                Distribution of portfolio values at the end of simulation period
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={getEquityDistributionData()}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="label" />
                  <YAxis tickFormatter={(value) => formatCurrency(value)} />
                  <Tooltip
                    formatter={(value: number) => formatCurrency(value)}
                  />
                  <Bar dataKey="value" fill="#3b82f6" name="Final Equity" />
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>

          {/* Performance Summary */}
          <Card>
            <CardHeader>
              <CardTitle>Performance Summary</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Mean Return</span>
                    <span className="font-semibold text-green-600">
                      {formatPercent(results.mean_return)}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">VaR (99%)</span>
                    <span className="font-semibold text-red-600">
                      {formatPercent(results.var_99)}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Max Drawdown</span>
                    <span className="font-semibold text-red-600">
                      {formatPercent(results.worst_drawdown)}
                    </span>
                  </div>
                </div>

                <div className="space-y-2">
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">
                      {results.report.performance_summary?.mean_return || 'N/A'}
                    </span>
                    <span className="text-xs text-muted-foreground">Mean Return</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">
                      {results.report.performance_summary?.median_return || 'N/A'}
                    </span>
                    <span className="text-xs text-muted-foreground">Median Return</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">
                      {results.report.performance_summary?.return_volatility || 'N/A'}
                    </span>
                    <span className="text-xs text-muted-foreground">Volatility</span>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Detailed Risk Summary Table */}
          <Card>
            <CardHeader>
              <CardTitle>Detailed Risk Assessment</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b">
                      <th className="text-left p-2">Metric</th>
                      <th className="text-left p-2">Value</th>
                      <th className="text-left p-2">Limit</th>
                      <th className="text-left p-2">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {results.report.risk_summary &&
                      Object.entries(results.report.risk_summary).map(([key, data]: [string, any]) => (
                        <tr key={key} className="border-b">
                          <td className="p-2 font-medium">{key.replace(/_/g, ' ').toUpperCase()}</td>
                          <td className="p-2">{data.value || data.mean || 'N/A'}</td>
                          <td className="p-2">{data.limit || '-'}</td>
                          <td className="p-2">
                            {data.pass !== undefined && (
                              <Badge variant={data.pass ? 'default' : 'destructive'}>
                                {data.pass ? '✓ Pass' : '✗ Fail'}
                              </Badge>
                            )}
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
};

export default StressTest;
