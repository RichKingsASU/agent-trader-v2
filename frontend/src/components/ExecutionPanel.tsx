import { useState, useEffect, useMemo } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  TrendingUp,
  TrendingDown,
  AlertTriangle,
  CheckCircle2,
  ArrowRight,
  DollarSign,
  Percent,
  Target,
  Shield,
} from "lucide-react";
import { useTradeExecutor, ExecuteTradeRequest } from "@/hooks/useTradeExecutor";
import { formatUsd2 } from "@/lib/utils";

interface ExecutionPanelProps {
  /**
   * AI recommendation data
   */
  aiRecommendation?: {
    action: "BUY" | "SELL" | "HOLD";
    symbol: string;
    target_allocation: number; // 0.0 to 1.0
    confidence: number;
    reasoning: string;
  };
  
  /**
   * Current account data
   */
  accountData?: {
    buying_power: string;
    equity: string;
    cash: string;
  };

  /**
   * Current market price for the symbol
   */
  currentPrice?: number;

  /**
   * Callback when trade is successfully executed
   */
  onExecutionSuccess?: (response: any) => void;
}

/**
 * ExecutionPanel - Phase 4: The Trade Executor (OMS)
 * 
 * Displays AI recommendation vs actual order size with confirmation workflow.
 * 
 * Features:
 * - Shows AI recommendation side-by-side with actual order
 * - Allows user to override allocation percentage
 * - Market vs Limit order selection
 * - Marketable limit orders (0.5% slippage protection)
 * - Confirmation dialog before execution
 * - Real-time feedback on execution status
 */
export const ExecutionPanel = ({
  aiRecommendation,
  accountData,
  currentPrice,
  onExecutionSuccess,
}: ExecutionPanelProps) => {
  const { executeOrder, loading, error, lastExecution, clearError } = useTradeExecutor();

  // Order configuration state
  const [orderSide, setOrderSide] = useState<"buy" | "sell">("buy");
  const [orderSymbol, setOrderSymbol] = useState<string>("AAPL");
  const [allocationPct, setAllocationPct] = useState<number>(0.1); // 10% default
  const [orderType, setOrderType] = useState<"market" | "limit">("limit");
  const [showConfirmDialog, setShowConfirmDialog] = useState(false);

  // Sync with AI recommendation when it changes
  useEffect(() => {
    if (aiRecommendation) {
      if (aiRecommendation.action === "BUY") {
        setOrderSide("buy");
      } else if (aiRecommendation.action === "SELL") {
        setOrderSide("sell");
      }
      
      if (aiRecommendation.symbol) {
        setOrderSymbol(aiRecommendation.symbol.toUpperCase());
      }
      
      if (aiRecommendation.target_allocation) {
        setAllocationPct(aiRecommendation.target_allocation);
      }
    }
  }, [aiRecommendation]);

  // Calculate order size
  const calculatedOrderSize = useMemo(() => {
    if (!accountData?.buying_power) return 0;
    
    const buyingPower = parseFloat(accountData.buying_power);
    return buyingPower * allocationPct;
  }, [accountData, allocationPct]);

  // AI recommended order size
  const aiRecommendedSize = useMemo(() => {
    if (!accountData?.buying_power || !aiRecommendation?.target_allocation) return null;
    
    const buyingPower = parseFloat(accountData.buying_power);
    return buyingPower * aiRecommendation.target_allocation;
  }, [accountData, aiRecommendation]);

  // Handle confirmation and execution
  const handleConfirmExecution = async () => {
    setShowConfirmDialog(false);
    clearError();

    const request: ExecuteTradeRequest = {
      symbol: orderSymbol,
      side: orderSide,
      allocation_pct: allocationPct,
      order_type: orderType,
      current_price: currentPrice,
      metadata: {
        ai_recommendation: aiRecommendation ? {
          action: aiRecommendation.action,
          confidence: aiRecommendation.confidence,
          reasoning: aiRecommendation.reasoning,
        } : undefined,
      },
    };

    try {
      const response = await executeOrder(request);
      
      if (onExecutionSuccess) {
        onExecutionSuccess(response);
      }
    } catch (err) {
      // Error is already set by the hook
      console.error("Execution failed:", err);
    }
  };

  const getSideColor = (side: string) => {
    return side.toLowerCase() === "buy" ? "bull-text" : "bear-text";
  };

  const getSideIcon = (side: string) => {
    return side.toLowerCase() === "buy" ? (
      <TrendingUp className="h-4 w-4" />
    ) : (
      <TrendingDown className="h-4 w-4" />
    );
  };

  const isValidOrder = orderSymbol && allocationPct > 0 && allocationPct <= 1;

  return (
    <Card className="p-4 border-2 bg-gradient-to-br from-primary/5 to-primary/10 border-primary/20">
      {/* Header */}
      <div className="flex items-center gap-2 mb-4">
        <Target className="h-4 w-4 text-primary" />
        <h3 className="text-xs font-bold text-primary uppercase tracking-wider ui-label">
          Trade Execution Panel
        </h3>
      </div>

      {/* AI Recommendation vs Actual Order */}
      {aiRecommendation && (
        <div className="grid grid-cols-2 gap-3 mb-4">
          {/* AI Recommendation */}
          <div className="bg-background/60 border border-blue-500/30 rounded-lg p-3">
            <div className="flex items-center gap-1 mb-2">
              <Shield className="h-3 w-3 text-blue-500" />
              <div className="text-[10px] text-blue-500 uppercase tracking-wide font-bold ui-label">
                AI Recommendation
              </div>
            </div>
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <div className={getSideColor(aiRecommendation.action)}>
                  {getSideIcon(aiRecommendation.action)}
                </div>
                <Badge variant="outline" className={`${getSideColor(aiRecommendation.action)} font-bold`}>
                  {aiRecommendation.action}
                </Badge>
              </div>
              <div className="text-xs">
                <span className="text-muted-foreground">Symbol: </span>
                <span className="font-mono font-bold">{aiRecommendation.symbol}</span>
              </div>
              <div className="text-xs">
                <span className="text-muted-foreground">Allocation: </span>
                <span className="number-mono font-bold">{(aiRecommendation.target_allocation * 100).toFixed(0)}%</span>
              </div>
              {aiRecommendedSize !== null && (
                <div className="text-xs">
                  <span className="text-muted-foreground">Size: </span>
                  <span className="number-mono font-bold">{formatUsd2(aiRecommendedSize)}</span>
                </div>
              )}
              <div className="text-xs">
                <span className="text-muted-foreground">Confidence: </span>
                <span className="number-mono font-bold">{(aiRecommendation.confidence * 100).toFixed(0)}%</span>
              </div>
            </div>
          </div>

          {/* Actual Order */}
          <div className="bg-background/60 border border-primary/30 rounded-lg p-3">
            <div className="flex items-center gap-1 mb-2">
              <ArrowRight className="h-3 w-3 text-primary" />
              <div className="text-[10px] text-primary uppercase tracking-wide font-bold ui-label">
                Actual Order
              </div>
            </div>
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <div className={getSideColor(orderSide)}>
                  {getSideIcon(orderSide)}
                </div>
                <Badge variant="outline" className={`${getSideColor(orderSide)} font-bold`}>
                  {orderSide.toUpperCase()}
                </Badge>
              </div>
              <div className="text-xs">
                <span className="text-muted-foreground">Symbol: </span>
                <span className="font-mono font-bold">{orderSymbol}</span>
              </div>
              <div className="text-xs">
                <span className="text-muted-foreground">Allocation: </span>
                <span className="number-mono font-bold">{(allocationPct * 100).toFixed(0)}%</span>
              </div>
              <div className="text-xs">
                <span className="text-muted-foreground">Size: </span>
                <span className="number-mono font-bold text-primary">{formatUsd2(calculatedOrderSize)}</span>
              </div>
              <div className="text-xs">
                <span className="text-muted-foreground">Type: </span>
                <span className="font-bold">{orderType.toUpperCase()}</span>
                {orderType === "limit" && (
                  <span className="text-[10px] text-muted-foreground"> (+0.5% buffer)</span>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Order Configuration */}
      <div className="space-y-3 mb-4">
        <div className="grid grid-cols-2 gap-3">
          {/* Symbol */}
          <div>
            <Label htmlFor="symbol" className="text-xs ui-label">Symbol</Label>
            <Input
              id="symbol"
              value={orderSymbol}
              onChange={(e) => setOrderSymbol(e.target.value.toUpperCase())}
              placeholder="AAPL"
              className="font-mono mt-1"
            />
          </div>

          {/* Side */}
          <div>
            <Label htmlFor="side" className="text-xs ui-label">Side</Label>
            <Select value={orderSide} onValueChange={(val) => setOrderSide(val as "buy" | "sell")}>
              <SelectTrigger id="side" className="mt-1">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="buy">
                  <div className="flex items-center gap-2">
                    <TrendingUp className="h-3 w-3 bull-text" />
                    <span>BUY</span>
                  </div>
                </SelectItem>
                <SelectItem value="sell">
                  <div className="flex items-center gap-2">
                    <TrendingDown className="h-3 w-3 bear-text" />
                    <span>SELL</span>
                  </div>
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          {/* Allocation % */}
          <div>
            <Label htmlFor="allocation" className="text-xs ui-label">Allocation %</Label>
            <div className="flex items-center gap-2 mt-1">
              <Input
                id="allocation"
                type="number"
                min="0"
                max="100"
                step="1"
                value={(allocationPct * 100).toFixed(0)}
                onChange={(e) => setAllocationPct(parseFloat(e.target.value) / 100)}
                className="number-mono"
              />
              <Percent className="h-4 w-4 text-muted-foreground" />
            </div>
          </div>

          {/* Order Type */}
          <div>
            <Label htmlFor="orderType" className="text-xs ui-label">Order Type</Label>
            <Select value={orderType} onValueChange={(val) => setOrderType(val as "market" | "limit")}>
              <SelectTrigger id="orderType" className="mt-1">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="limit">
                  <div className="flex items-center gap-2">
                    <Shield className="h-3 w-3" />
                    <span>LIMIT (Protected)</span>
                  </div>
                </SelectItem>
                <SelectItem value="market">
                  <div className="flex items-center gap-2">
                    <DollarSign className="h-3 w-3" />
                    <span>MARKET</span>
                  </div>
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        {/* Calculated Order Size */}
        <div className="bg-background/60 border border-white/10 rounded-md p-3">
          <div className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1 ui-label">
            Calculated Order Size
          </div>
          <div className="number-mono text-2xl font-bold text-primary">
            {formatUsd2(calculatedOrderSize)}
          </div>
          {accountData && (
            <div className="text-[10px] text-muted-foreground mt-1">
              Available Buying Power: <span className="number-mono">{formatUsd2(parseFloat(accountData.buying_power))}</span>
            </div>
          )}
          {currentPrice && (
            <div className="text-[10px] text-muted-foreground">
              Current Price: <span className="number-mono">{formatUsd2(currentPrice)}</span>
            </div>
          )}
        </div>
      </div>

      {/* Error Display */}
      {error && (
        <Alert variant="destructive" className="mb-4">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription className="text-xs">
            <strong>Execution Failed:</strong> {error.message}
          </AlertDescription>
        </Alert>
      )}

      {/* Success Display */}
      {lastExecution && !loading && (
        <Alert className="mb-4 border-green-500/30 bg-green-500/10">
          <CheckCircle2 className="h-4 w-4 text-green-500" />
          <AlertDescription className="text-xs">
            <strong>Order Submitted:</strong> {lastExecution.message}
            <div className="mt-1 font-mono text-[10px]">
              Order ID: {lastExecution.client_order_id}
            </div>
          </AlertDescription>
        </Alert>
      )}

      {/* Execute Button */}
      <Button
        onClick={() => setShowConfirmDialog(true)}
        disabled={!isValidOrder || loading}
        className="w-full"
        size="lg"
      >
        {loading ? (
          <>
            <div className="animate-spin mr-2 h-4 w-4 border-2 border-background border-t-transparent rounded-full" />
            Executing...
          </>
        ) : (
          <>
            <Target className="mr-2 h-4 w-4" />
            Confirm Execution
          </>
        )}
      </Button>

      {/* Confirmation Dialog */}
      <AlertDialog open={showConfirmDialog} onOpenChange={setShowConfirmDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Confirm Order Execution</AlertDialogTitle>
            <AlertDialogDescription>
              You are about to execute the following order:
              
              <div className="mt-4 space-y-2 text-foreground">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Symbol:</span>
                  <span className="font-mono font-bold">{orderSymbol}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Side:</span>
                  <Badge variant="outline" className={getSideColor(orderSide)}>
                    {orderSide.toUpperCase()}
                  </Badge>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Order Size:</span>
                  <span className="number-mono font-bold">{formatUsd2(calculatedOrderSize)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Allocation:</span>
                  <span className="number-mono">{(allocationPct * 100).toFixed(0)}%</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Order Type:</span>
                  <span className="font-bold">{orderType.toUpperCase()}</span>
                </div>
                {orderType === "limit" && (
                  <div className="text-xs text-muted-foreground mt-2">
                    <Shield className="inline h-3 w-3 mr-1" />
                    Limit order with 0.5% slippage protection
                  </div>
                )}
              </div>

              <div className="mt-4 p-3 bg-amber-500/10 border border-amber-500/30 rounded-md">
                <div className="flex items-start gap-2">
                  <AlertTriangle className="h-4 w-4 text-amber-500 mt-0.5" />
                  <div className="text-xs text-foreground">
                    This will place a real order on your Alpaca account. Make sure you have reviewed all details.
                  </div>
                </div>
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={handleConfirmExecution}>
              Execute Order
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  );
};
