import React, { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { 
  Table, 
  TableBody, 
  TableCell, 
  TableHead, 
  TableHeader, 
  TableRow 
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Loader2, AlertCircle, RefreshCw, ArrowUpDown, TrendingUp, TrendingDown, Clock } from "lucide-react";

interface ExecutionAuditEntry {
  trade_id: string;
  timestamp: string;
  symbol: string;
  side: string;
  quantity: number;
  intended_price: number | null;
  executed_price: number;
  slippage_dollars: number;
  slippage_bps: number;
  slippage_percent: number;
  order_type: string;
  time_to_fill_ms: number | null;
  strategy_id: string;
  status: string;
}

interface ExecutionAuditData {
  executions: ExecutionAuditEntry[];
  total_executions: number;
  avg_slippage_bps: number;
  median_slippage_bps: number;
  worst_slippage_bps: number;
  best_slippage_bps: number;
  total_slippage_cost: number;
  avg_time_to_fill_ms: number;
  timestamp: string;
}

interface ExecutionAuditProps {
  tenantId: string;
}

export const ExecutionAudit: React.FC<ExecutionAuditProps> = ({ tenantId }) => {
  const [data, setData] = useState<ExecutionAuditData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [days, setDays] = useState(7);
  const [symbolFilter, setSymbolFilter] = useState("");
  const [sortField, setSortField] = useState<keyof ExecutionAuditEntry>("timestamp");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("desc");

  useEffect(() => {
    fetchExecutionData();
  }, [tenantId, days, symbolFilter]);

  const fetchExecutionData = async () => {
    try {
      setLoading(true);
      setError(null);
      
      let url = `http://localhost:8001/api/institutional/execution/audit?tenant_id=${tenantId}&days=${days}`;
      if (symbolFilter) {
        url += `&symbol=${symbolFilter}`;
      }
      
      const response = await fetch(url);
      
      if (!response.ok) {
        throw new Error(`Failed to fetch execution audit: ${response.statusText}`);
      }
      
      const result = await response.json();
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch execution audit");
      console.error("Error fetching execution audit:", err);
    } finally {
      setLoading(false);
    }
  };

  const handleSort = (field: keyof ExecutionAuditEntry) => {
    if (sortField === field) {
      setSortDirection(sortDirection === "asc" ? "desc" : "asc");
    } else {
      setSortField(field);
      setSortDirection("desc");
    }
  };

  const sortedExecutions = data?.executions.slice().sort((a, b) => {
    const aValue = a[sortField];
    const bValue = b[sortField];
    
    if (aValue === null || aValue === undefined) return 1;
    if (bValue === null || bValue === undefined) return -1;
    
    if (sortDirection === "asc") {
      return aValue > bValue ? 1 : -1;
    } else {
      return aValue < bValue ? 1 : -1;
    }
  });

  const getSlippageBadge = (slippageBps: number) => {
    if (slippageBps < -10) {
      return <Badge className="bg-emerald-500 hover:bg-emerald-600">Excellent</Badge>;
    } else if (slippageBps < 0) {
      return <Badge className="bg-green-600 hover:bg-green-700">Good</Badge>;
    } else if (slippageBps < 10) {
      return <Badge variant="secondary">Fair</Badge>;
    } else if (slippageBps < 25) {
      return <Badge className="bg-orange-500 hover:bg-orange-600">Poor</Badge>;
    } else {
      return <Badge className="bg-red-500 hover:bg-red-600">Bad</Badge>;
    }
  };

  if (loading && !data) {
    return (
      <Card className="w-full">
        <CardHeader>
          <CardTitle>Execution Audit</CardTitle>
          <CardDescription>Slippage analysis and execution quality metrics</CardDescription>
        </CardHeader>
        <CardContent className="flex items-center justify-center py-8">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card className="w-full">
        <CardHeader>
          <CardTitle>Execution Audit</CardTitle>
          <CardDescription>Slippage analysis and execution quality metrics</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-2 text-destructive">
            <AlertCircle className="h-5 w-5" />
            <span>{error}</span>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (!data) {
    return null;
  }

  return (
    <Card className="w-full">
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-2xl">Execution Audit</CardTitle>
            <CardDescription>
              {data.total_executions} executions analyzed • Updated {new Date(data.timestamp).toLocaleTimeString()}
            </CardDescription>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={fetchExecutionData}
            disabled={loading}
          >
            <RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        </div>
      </CardHeader>
      
      <CardContent className="space-y-6">
        {/* Summary Statistics */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="bg-muted/50 p-4 rounded-lg">
            <div className="text-sm text-muted-foreground">Avg Slippage</div>
            <div className={`text-2xl font-bold ${data.avg_slippage_bps < 0 ? 'text-emerald-500' : 'text-red-500'}`}>
              {data.avg_slippage_bps.toFixed(2)} bps
            </div>
          </div>
          
          <div className="bg-muted/50 p-4 rounded-lg">
            <div className="text-sm text-muted-foreground">Median Slippage</div>
            <div className={`text-2xl font-bold ${data.median_slippage_bps < 0 ? 'text-emerald-500' : 'text-red-500'}`}>
              {data.median_slippage_bps.toFixed(2)} bps
            </div>
          </div>
          
          <div className="bg-muted/50 p-4 rounded-lg">
            <div className="text-sm text-muted-foreground">Total Cost</div>
            <div className={`text-2xl font-bold ${data.total_slippage_cost < 0 ? 'text-emerald-500' : 'text-red-500'}`}>
              ${Math.abs(data.total_slippage_cost).toFixed(2)}
            </div>
          </div>
          
          <div className="bg-muted/50 p-4 rounded-lg">
            <div className="text-sm text-muted-foreground">Avg Fill Time</div>
            <div className="text-2xl font-bold">
              {data.avg_time_to_fill_ms > 0 ? `${data.avg_time_to_fill_ms.toFixed(0)}ms` : 'N/A'}
            </div>
          </div>
        </div>

        {/* Slippage Range */}
        <div className="bg-muted/30 p-4 rounded-lg border border-border">
          <h4 className="font-semibold mb-3">Slippage Range</h4>
          <div className="grid grid-cols-2 gap-4">
            <div className="flex items-center gap-2">
              <TrendingUp className="h-5 w-5 text-emerald-500" />
              <div>
                <div className="text-sm text-muted-foreground">Best</div>
                <div className="text-lg font-bold text-emerald-500">
                  {data.best_slippage_bps.toFixed(2)} bps
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <TrendingDown className="h-5 w-5 text-red-500" />
              <div>
                <div className="text-sm text-muted-foreground">Worst</div>
                <div className="text-lg font-bold text-red-500">
                  {data.worst_slippage_bps.toFixed(2)} bps
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Filters */}
        <div className="flex gap-4">
          <div className="flex-1">
            <label className="text-sm font-medium mb-2 block">Symbol Filter</label>
            <Input
              placeholder="Enter symbol (e.g., AAPL)"
              value={symbolFilter}
              onChange={(e) => setSymbolFilter(e.target.value.toUpperCase())}
            />
          </div>
          <div className="w-40">
            <label className="text-sm font-medium mb-2 block">Time Period</label>
            <Select value={days.toString()} onValueChange={(value) => setDays(parseInt(value))}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="1">Last 24 hours</SelectItem>
                <SelectItem value="7">Last 7 days</SelectItem>
                <SelectItem value="30">Last 30 days</SelectItem>
                <SelectItem value="90">Last 90 days</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        {/* Executions Table */}
        <div className="border rounded-lg">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="cursor-pointer" onClick={() => handleSort("timestamp")}>
                  <div className="flex items-center gap-2">
                    Time <ArrowUpDown className="h-4 w-4" />
                  </div>
                </TableHead>
                <TableHead className="cursor-pointer" onClick={() => handleSort("symbol")}>
                  <div className="flex items-center gap-2">
                    Symbol <ArrowUpDown className="h-4 w-4" />
                  </div>
                </TableHead>
                <TableHead>Side</TableHead>
                <TableHead className="cursor-pointer" onClick={() => handleSort("quantity")}>
                  <div className="flex items-center gap-2">
                    Qty <ArrowUpDown className="h-4 w-4" />
                  </div>
                </TableHead>
                <TableHead>Intended</TableHead>
                <TableHead>Executed</TableHead>
                <TableHead className="cursor-pointer" onClick={() => handleSort("slippage_bps")}>
                  <div className="flex items-center gap-2">
                    Slippage (bps) <ArrowUpDown className="h-4 w-4" />
                  </div>
                </TableHead>
                <TableHead className="cursor-pointer" onClick={() => handleSort("slippage_dollars")}>
                  <div className="flex items-center gap-2">
                    $ Impact <ArrowUpDown className="h-4 w-4" />
                  </div>
                </TableHead>
                <TableHead>Quality</TableHead>
                <TableHead>Order Type</TableHead>
                <TableHead className="cursor-pointer" onClick={() => handleSort("time_to_fill_ms")}>
                  <div className="flex items-center gap-2">
                    <Clock className="h-4 w-4" /> Fill Time
                  </div>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sortedExecutions && sortedExecutions.length > 0 ? (
                sortedExecutions.map((execution) => (
                  <TableRow key={execution.trade_id}>
                    <TableCell className="text-xs">
                      {new Date(execution.timestamp).toLocaleString()}
                    </TableCell>
                    <TableCell className="font-semibold">{execution.symbol}</TableCell>
                    <TableCell>
                      <Badge variant={execution.side === "buy" ? "default" : "destructive"}>
                        {execution.side.toUpperCase()}
                      </Badge>
                    </TableCell>
                    <TableCell>{execution.quantity.toFixed(2)}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {execution.intended_price ? `$${execution.intended_price.toFixed(2)}` : 'Market'}
                    </TableCell>
                    <TableCell className="font-semibold">${execution.executed_price.toFixed(2)}</TableCell>
                    <TableCell className={execution.slippage_bps < 0 ? 'text-emerald-500 font-semibold' : 'text-red-500 font-semibold'}>
                      {execution.slippage_bps.toFixed(2)}
                    </TableCell>
                    <TableCell className={execution.slippage_dollars < 0 ? 'text-emerald-500' : 'text-red-500'}>
                      ${Math.abs(execution.slippage_dollars * execution.quantity).toFixed(2)}
                    </TableCell>
                    <TableCell>
                      {getSlippageBadge(execution.slippage_bps)}
                    </TableCell>
                    <TableCell className="text-xs">{execution.order_type}</TableCell>
                    <TableCell className="text-xs">
                      {execution.time_to_fill_ms ? `${execution.time_to_fill_ms.toFixed(0)}ms` : 'N/A'}
                    </TableCell>
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell colSpan={11} className="text-center text-muted-foreground py-8">
                    No execution data available
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>

        {/* Explanation */}
        <div className="bg-muted/30 p-4 rounded-lg border border-border">
          <h4 className="font-semibold mb-2">Understanding Slippage</h4>
          <div className="text-sm text-muted-foreground space-y-1">
            <p>
              <strong>Slippage</strong> is the difference between the intended price and the actual fill price.
            </p>
            <p>
              • <span className="text-emerald-500">Negative slippage</span> (green) means you got a better price than expected (good!)
            </p>
            <p>
              • <span className="text-red-500">Positive slippage</span> (red) means you paid more (buy) or received less (sell) than expected (bad)
            </p>
            <p>
              • Measured in <strong>basis points (bps)</strong>: 100 bps = 1%
            </p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};
