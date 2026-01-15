import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { getFunctions, httpsCallable } from "firebase/functions";
import { getFirestore, addDoc, updateDoc, deleteDoc, onSnapshot, serverTimestamp } from "firebase/firestore";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Separator } from "@/components/ui/separator";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { ArrowLeft, Loader2, PieChart as PieChartIcon, Plus, Trash2, RefreshCw, AlertCircle, TrendingUp, TrendingDown } from "lucide-react";
import { toast } from "sonner";
import { ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";
import { PieChart, Pie, Cell, Legend, ResponsiveContainer } from "recharts";
import { userSettingsCollection, userSettingsDoc } from "@/lib/tenancy/firestore";

interface Allocation {
  id: string;
  symbol: string;
  target_percent: number;
  enabled: boolean;
  created_at?: any;
  updated_at?: any;
}

interface DriftAnalysis {
  symbol: string;
  target_percent: number;
  actual_percent: number;
  drift_percent: number;
  needs_rebalance: boolean;
  action?: string;
}

interface RebalanceResult {
  needs_rebalance: boolean;
  drift_analysis: DriftAnalysis[];
  trades_executed: any[];
  portfolio_value?: number;
  message: string;
}

// Color palette for the pie chart
const COLORS = [
  "hsl(var(--chart-1))",
  "hsl(var(--chart-2))",
  "hsl(var(--chart-3))",
  "hsl(var(--chart-4))",
  "hsl(var(--chart-5))",
];

export default function Allocation() {
  const navigate = useNavigate();
  const { user, tenantId, loading: authLoading } = useAuth();
  const [allocations, setAllocations] = useState<Allocation[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [rebalancing, setRebalancing] = useState(false);
  const [showAddDialog, setShowAddDialog] = useState(false);
  const [newSymbol, setNewSymbol] = useState("");
  const [newTargetPercent, setNewTargetPercent] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [rebalanceResult, setRebalanceResult] = useState<RebalanceResult | null>(null);

  // Redirect if not logged in
  useEffect(() => {
    if (!authLoading && !user) {
      navigate("/auth");
    }
  }, [user, authLoading, navigate]);

  // Load allocations from Firestore
  useEffect(() => {
    if (!user) return;

    const db = getFirestore();
    const allocationsRef = userSettingsCollection(db, user.uid, "allocation");

    const unsubscribe = onSnapshot(
      allocationsRef,
      (snapshot) => {
        const items: Allocation[] = [];
        snapshot.forEach((doc) => {
          items.push({ id: doc.id, ...doc.data() } as Allocation);
        });
        setAllocations(items);
        setLoading(false);
      },
      (err) => {
        console.error("Error loading allocations:", err);
        setError(err.message);
        setLoading(false);
      }
    );

    return () => unsubscribe();
  }, [user]);

  const handleAddAllocation = async () => {
    if (!user || !newSymbol || !newTargetPercent) {
      setError("Please fill in all fields");
      return;
    }

    const targetPercent = parseFloat(newTargetPercent);
    if (isNaN(targetPercent) || targetPercent <= 0 || targetPercent > 100) {
      setError("Target percent must be between 0 and 100");
      return;
    }

    // Check if symbol already exists
    if (allocations.some(a => a.symbol.toUpperCase() === newSymbol.toUpperCase())) {
      setError("Symbol already exists");
      return;
    }

    setSaving(true);
    setError(null);

    try {
      const db = getFirestore();
      const allocationsRef = userSettingsCollection(db, user.uid, "allocation");
      
      await addDoc(allocationsRef, {
        symbol: newSymbol.toUpperCase(),
        target_percent: targetPercent,
        enabled: true,
        created_at: serverTimestamp(),
        updated_at: serverTimestamp(),
      });

      toast.success(`Added ${newSymbol.toUpperCase()} to portfolio allocation`);
      setNewSymbol("");
      setNewTargetPercent("");
      setShowAddDialog(false);
    } catch (err: any) {
      setError(err.message || "Failed to add allocation");
      toast.error("Failed to add allocation");
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteAllocation = async (id: string, symbol: string) => {
    if (!user) return;

    try {
      const db = getFirestore();
      const allocationRef = userSettingsDoc(db, user.uid, "allocation", id);
      await deleteDoc(allocationRef);
      toast.success(`Removed ${symbol} from portfolio allocation`);
    } catch (err: any) {
      toast.error("Failed to delete allocation");
      console.error(err);
    }
  };

  const handleCheckRebalance = async () => {
    if (!user) return;

    setRebalancing(true);
    setError(null);

    try {
      const functions = getFunctions();
      const checkRebalance = httpsCallable(functions, "check_rebalance_drift");
      const result = await checkRebalance({});
      const data = result.data as RebalanceResult;
      
      setRebalanceResult(data);
      
      if (data.trades_executed && data.trades_executed.length > 0) {
        toast.success(`Rebalancing executed: ${data.trades_executed.length} trades placed`);
      } else if (data.needs_rebalance) {
        toast.info("Portfolio needs rebalancing, but no trades were executed");
      } else {
        toast.info("Portfolio is balanced - no action needed");
      }
    } catch (err: any) {
      setError(err.message || "Failed to check rebalancing");
      toast.error("Failed to check rebalancing");
      console.error(err);
    } finally {
      setRebalancing(false);
    }
  };

  const totalTargetPercent = allocations
    .filter(a => a.enabled)
    .reduce((sum, a) => sum + a.target_percent, 0);

  const isValidTotal = Math.abs(totalTargetPercent - 100) <= 1; // 1% tolerance

  // Prepare data for pie charts
  const targetChartData = allocations
    .filter(a => a.enabled)
    .map(a => ({
      name: a.symbol,
      value: a.target_percent,
      percent: a.target_percent,
    }));

  const actualChartData = rebalanceResult?.drift_analysis
    ? rebalanceResult.drift_analysis.map(d => ({
        name: d.symbol,
        value: d.actual_percent,
        percent: d.actual_percent,
      }))
    : [];

  if (authLoading || loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (!user) return null;

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-7xl mx-auto p-6">
        <Button
          variant="ghost"
          onClick={() => navigate(-1)}
          className="mb-6 -ml-2"
        >
          <ArrowLeft className="h-4 w-4 mr-2" />
          Back
        </Button>

        <div className="space-y-6">
          {/* Header */}
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-3xl font-bold flex items-center gap-2">
                <PieChartIcon className="h-8 w-8" />
                Portfolio Allocation
              </h1>
              <p className="text-muted-foreground mt-1">
                Define target allocations and rebalance your portfolio automatically
              </p>
            </div>
            <Button onClick={handleCheckRebalance} disabled={rebalancing || allocations.length === 0}>
              {rebalancing ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                  Checking...
                </>
              ) : (
                <>
                  <RefreshCw className="h-4 w-4 mr-2" />
                  Check & Rebalance
                </>
              )}
            </Button>
          </div>

          {error && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          {/* Target Allocation Warning */}
          {!isValidTotal && allocations.length > 0 && (
            <Alert>
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>
                Warning: Target allocations sum to {totalTargetPercent.toFixed(1)}%. 
                They should total approximately 100%.
              </AlertDescription>
            </Alert>
          )}

          {/* Charts Section */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Target Allocation Chart */}
            <Card>
              <CardHeader>
                <CardTitle>Target Allocation</CardTitle>
                <CardDescription>
                  Your desired portfolio distribution
                </CardDescription>
              </CardHeader>
              <CardContent>
                {targetChartData.length > 0 ? (
                  <div className="h-[300px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie
                          data={targetChartData}
                          cx="50%"
                          cy="50%"
                          labelLine={false}
                          label={({ name, percent }) => `${name}: ${percent.toFixed(1)}%`}
                          outerRadius={80}
                          fill="#8884d8"
                          dataKey="value"
                        >
                          {targetChartData.map((entry, index) => (
                            <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                          ))}
                        </Pie>
                        <ChartTooltip content={<ChartTooltipContent />} />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <div className="h-[300px] flex items-center justify-center text-muted-foreground">
                    No allocations configured
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Actual Allocation Chart */}
            <Card>
              <CardHeader>
                <CardTitle>Actual Allocation</CardTitle>
                <CardDescription>
                  Your current portfolio distribution
                </CardDescription>
              </CardHeader>
              <CardContent>
                {actualChartData.length > 0 ? (
                  <div className="h-[300px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie
                          data={actualChartData}
                          cx="50%"
                          cy="50%"
                          labelLine={false}
                          label={({ name, percent }) => `${name}: ${percent.toFixed(1)}%`}
                          outerRadius={80}
                          fill="#8884d8"
                          dataKey="value"
                        >
                          {actualChartData.map((entry, index) => (
                            <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                          ))}
                        </Pie>
                        <ChartTooltip content={<ChartTooltipContent />} />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <div className="h-[300px] flex items-center justify-center text-muted-foreground">
                    Run rebalance check to see actual allocation
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Drift Analysis */}
          {rebalanceResult && rebalanceResult.drift_analysis.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Drift Analysis</CardTitle>
                <CardDescription>
                  Comparison of target vs actual allocations
                  {rebalanceResult.portfolio_value && (
                    <span className="ml-2 text-foreground font-semibold">
                      (Portfolio Value: ${rebalanceResult.portfolio_value.toLocaleString()})
                    </span>
                  )}
                </CardDescription>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Symbol</TableHead>
                      <TableHead className="text-right">Target %</TableHead>
                      <TableHead className="text-right">Actual %</TableHead>
                      <TableHead className="text-right">Drift</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Action</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {rebalanceResult.drift_analysis.map((item) => (
                      <TableRow key={item.symbol}>
                        <TableCell className="font-medium">{item.symbol}</TableCell>
                        <TableCell className="text-right">{item.target_percent.toFixed(1)}%</TableCell>
                        <TableCell className="text-right">{item.actual_percent.toFixed(1)}%</TableCell>
                        <TableCell className={`text-right ${Math.abs(item.drift_percent) > 5 ? 'text-red-500 font-bold' : ''}`}>
                          {item.drift_percent > 0 ? '+' : ''}{item.drift_percent.toFixed(1)}%
                        </TableCell>
                        <TableCell>
                          {item.needs_rebalance ? (
                            <span className="text-red-500 font-semibold flex items-center gap-1">
                              <AlertCircle className="h-4 w-4" />
                              Needs Rebalance
                            </span>
                          ) : (
                            <span className="text-green-500">Balanced</span>
                          )}
                        </TableCell>
                        <TableCell>
                          {item.action === 'buy' && (
                            <span className="text-green-500 font-semibold flex items-center gap-1">
                              <TrendingUp className="h-4 w-4" />
                              Buy
                            </span>
                          )}
                          {item.action === 'sell' && (
                            <span className="text-red-500 font-semibold flex items-center gap-1">
                              <TrendingDown className="h-4 w-4" />
                              Sell
                            </span>
                          )}
                          {!item.action && <span className="text-muted-foreground">-</span>}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}

          {/* Trades Executed */}
          {rebalanceResult && rebalanceResult.trades_executed.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Trades Executed</CardTitle>
                <CardDescription>
                  Rebalancing trades that were placed
                </CardDescription>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Symbol</TableHead>
                      <TableHead>Side</TableHead>
                      <TableHead className="text-right">Quantity</TableHead>
                      <TableHead>Order ID</TableHead>
                      <TableHead>Status</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {rebalanceResult.trades_executed.map((trade, idx) => (
                      <TableRow key={idx}>
                        <TableCell className="font-medium">{trade.symbol}</TableCell>
                        <TableCell>
                          <span className={trade.side === 'buy' ? 'text-green-500' : 'text-red-500'}>
                            {trade.side?.toUpperCase()}
                          </span>
                        </TableCell>
                        <TableCell className="text-right">{trade.qty}</TableCell>
                        <TableCell className="font-mono text-xs">{trade.order_id || 'N/A'}</TableCell>
                        <TableCell>{trade.status || trade.error || 'Unknown'}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}

          {/* Target Allocations Table */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0">
              <div>
                <CardTitle>Target Allocations</CardTitle>
                <CardDescription>
                  Manage your target portfolio allocations
                </CardDescription>
              </div>
              <Dialog open={showAddDialog} onOpenChange={setShowAddDialog}>
                <DialogTrigger asChild>
                  <Button>
                    <Plus className="h-4 w-4 mr-2" />
                    Add Allocation
                  </Button>
                </DialogTrigger>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>Add Target Allocation</DialogTitle>
                    <DialogDescription>
                      Add a new ticker to your target portfolio allocation
                    </DialogDescription>
                  </DialogHeader>
                  <div className="space-y-4">
                    <div className="space-y-2">
                      <Label htmlFor="symbol">Symbol</Label>
                      <Input
                        id="symbol"
                        value={newSymbol}
                        onChange={(e) => setNewSymbol(e.target.value.toUpperCase())}
                        placeholder="e.g., SPY"
                        maxLength={10}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="targetPercent">Target Percent (%)</Label>
                      <Input
                        id="targetPercent"
                        type="number"
                        value={newTargetPercent}
                        onChange={(e) => setNewTargetPercent(e.target.value)}
                        placeholder="e.g., 40"
                        min="0"
                        max="100"
                        step="0.1"
                      />
                    </div>
                    <Button onClick={handleAddAllocation} disabled={saving} className="w-full">
                      {saving ? (
                        <>
                          <Loader2 className="h-4 w-4 animate-spin mr-2" />
                          Adding...
                        </>
                      ) : (
                        "Add Allocation"
                      )}
                    </Button>
                  </div>
                </DialogContent>
              </Dialog>
            </CardHeader>
            <CardContent>
              {allocations.length > 0 ? (
                <>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Symbol</TableHead>
                        <TableHead className="text-right">Target %</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead className="text-right">Actions</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {allocations.map((allocation) => (
                        <TableRow key={allocation.id}>
                          <TableCell className="font-medium">{allocation.symbol}</TableCell>
                          <TableCell className="text-right">{allocation.target_percent.toFixed(1)}%</TableCell>
                          <TableCell>
                            {allocation.enabled ? (
                              <span className="text-green-500">Active</span>
                            ) : (
                              <span className="text-muted-foreground">Inactive</span>
                            )}
                          </TableCell>
                          <TableCell className="text-right">
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => handleDeleteAllocation(allocation.id, allocation.symbol)}
                            >
                              <Trash2 className="h-4 w-4 text-red-500" />
                            </Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                  <Separator className="my-4" />
                  <div className="flex justify-between items-center">
                    <span className="font-semibold">Total:</span>
                    <span className={`font-bold text-lg ${isValidTotal ? 'text-green-500' : 'text-red-500'}`}>
                      {totalTargetPercent.toFixed(1)}%
                    </span>
                  </div>
                </>
              ) : (
                <div className="text-center py-8 text-muted-foreground">
                  No allocations configured. Click "Add Allocation" to get started.
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
