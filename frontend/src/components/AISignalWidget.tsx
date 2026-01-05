import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Brain, TrendingUp, TrendingDown, Minus, Sparkles, RefreshCw } from "lucide-react";
import { useAISignals } from "@/hooks/useAISignals";
import { formatUsd2 } from "@/lib/utils";

/**
 * AISignalWidget - Phase 2: Signal Intelligence Dashboard Component
 * 
 * Displays AI-generated trading recommendations from Vertex AI Gemini.
 * Shows action (BUY/SELL/HOLD), confidence, reasoning, and target allocation.
 */
export const AISignalWidget = () => {
  const { signal, loading, error, generateSignal } = useAISignals();

  const getActionColor = (action?: string) => {
    switch (action) {
      case "BUY":
        return "bull-text";
      case "SELL":
        return "bear-text";
      case "HOLD":
        return "text-amber-500";
      default:
        return "text-muted-foreground";
    }
  };

  const getActionIcon = (action?: string) => {
    switch (action) {
      case "BUY":
        return <TrendingUp className="h-5 w-5" />;
      case "SELL":
        return <TrendingDown className="h-5 w-5" />;
      case "HOLD":
        return <Minus className="h-5 w-5" />;
      default:
        return <Brain className="h-5 w-5" />;
    }
  };

  const getActionBgGradient = (action?: string) => {
    switch (action) {
      case "BUY":
        return "from-green-500/5 to-green-500/10 border-green-500/20";
      case "SELL":
        return "from-red-500/5 to-red-500/10 border-red-500/20";
      case "HOLD":
        return "from-amber-500/5 to-amber-500/10 border-amber-500/20";
      default:
        return "from-primary/5 to-primary/10 border-primary/20";
    }
  };

  const formatConfidence = (confidence: number): string => {
    return `${(confidence * 100).toFixed(0)}%`;
  };

  const formatAllocation = (allocation: number): string => {
    return `${(allocation * 100).toFixed(0)}%`;
  };

  return (
    <Card className={`p-4 border-2 bg-gradient-to-br ${getActionBgGradient(signal?.action)}`}>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Brain className="h-4 w-4 text-primary" />
          <h3 className="text-xs font-bold text-primary uppercase tracking-wider ui-label">
            AI Trading Signal
          </h3>
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={generateSignal}
          disabled={loading}
          className="h-7 px-2 text-xs"
        >
          <RefreshCw className={`h-3 w-3 mr-1 ${loading ? "animate-spin" : ""}`} />
          {loading ? "Generating..." : "Generate Fresh Signal"}
        </Button>
      </div>

      {/* Error State */}
      {error && (
        <div className="bg-destructive/10 border border-destructive/30 rounded-md p-3 mb-3">
          <p className="text-xs text-destructive font-medium">{error}</p>
        </div>
      )}

      {/* Loading State */}
      {loading && !signal && (
        <div className="space-y-3">
          <div className="animate-pulse space-y-3">
            <div className="h-16 bg-muted rounded"></div>
            <div className="h-20 bg-muted rounded"></div>
          </div>
        </div>
      )}

      {/* Signal Display */}
      {signal && !loading && (
        <div className="space-y-4">
          {/* Action Badge */}
          <div className="flex items-center justify-center gap-3 bg-background/60 border border-white/10 rounded-lg p-4">
            <div className={getActionColor(signal.action)}>
              {getActionIcon(signal.action)}
            </div>
            <div className="text-center">
              <div className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1 font-medium ui-label">
                AI STRATEGY
              </div>
              <Badge
                variant="outline"
                className={`${getActionColor(signal.action)} text-lg font-bold px-4 py-1 border-2`}
              >
                {signal.action}
              </Badge>
              <div className="text-xs text-muted-foreground mt-1 ui-label">
                Confidence: {formatConfidence(signal.confidence)}
              </div>
            </div>
          </div>

          {/* Metrics */}
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-background/60 border border-white/10 rounded-md p-3">
              <div className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1 font-medium ui-label">
                Confidence
              </div>
              <div className="number-mono text-lg font-bold text-foreground">
                {formatConfidence(signal.confidence)}
              </div>
              <div className="w-full bg-muted rounded-full h-1.5 mt-2">
                <div
                  className={`h-1.5 rounded-full transition-all ${
                    signal.confidence >= 0.7
                      ? "bg-green-500"
                      : signal.confidence >= 0.5
                      ? "bg-amber-500"
                      : "bg-red-500"
                  }`}
                  style={{ width: formatConfidence(signal.confidence) }}
                ></div>
              </div>
            </div>

            <div className="bg-background/60 border border-white/10 rounded-md p-3">
              <div className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1 font-medium ui-label">
                Target Allocation
              </div>
              <div className="number-mono text-lg font-bold text-foreground">
                {formatAllocation(signal.target_allocation)}
              </div>
              <div className="text-[10px] text-muted-foreground mt-1">
                of portfolio
              </div>
            </div>
          </div>

          {/* AI Reasoning Block */}
          <div className="bg-background/60 border border-white/10 rounded-lg p-4">
            <div className="flex items-center gap-2 mb-2">
              <Sparkles className="h-3.5 w-3.5 text-primary" />
              <h4 className="text-xs font-bold text-primary uppercase tracking-wider ui-label">
                AI Analysis
              </h4>
            </div>
            <p className="text-xs text-foreground leading-relaxed">
              {signal.reasoning}
            </p>
          </div>

          {/* Account Context (if available) */}
          {signal.account_snapshot && (
            <div className="border-t border-white/10 pt-3">
              <div className="text-[9px] text-muted-foreground uppercase tracking-wide mb-2 font-medium ui-label">
                Based on Account:
              </div>
              <div className="grid grid-cols-3 gap-2 text-[10px]">
                <div>
                  <span className="text-muted-foreground">Equity: </span>
                  <span className="number-mono font-semibold">
                    {formatUsd2(parseFloat(signal.account_snapshot.equity))}
                  </span>
                </div>
                <div>
                  <span className="text-muted-foreground">Buying Power: </span>
                  <span className="number-mono font-semibold">
                    {formatUsd2(parseFloat(signal.account_snapshot.buying_power))}
                  </span>
                </div>
                <div>
                  <span className="text-muted-foreground">Cash: </span>
                  <span className="number-mono font-semibold">
                    {formatUsd2(parseFloat(signal.account_snapshot.cash))}
                  </span>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Empty State */}
      {!signal && !loading && !error && (
        <div className="text-center py-8">
          <Brain className="h-12 w-12 text-muted-foreground/30 mx-auto mb-3" />
          <p className="text-sm text-muted-foreground mb-2">No signal generated yet</p>
          <p className="text-xs text-muted-foreground/70">
            Click "Request Signal" to get an AI recommendation
          </p>
        </div>
      )}
    </Card>
  );
};
