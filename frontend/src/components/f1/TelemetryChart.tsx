import { Card } from "@/components/ui/card";
import { TradingViewChart } from "@/components/TradingViewChart";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ArrowUp, ArrowDown, Maximize2, Radio } from "lucide-react";

interface TelemetryChartProps {
  symbol: string;
  currentPrice: number;
  change: number;
  changePct: number;
  openPnL?: number;
  positionSize?: number;
  onOpenConsole?: () => void;
  isLive?: boolean;
}

export const TelemetryChart = ({
  symbol,
  currentPrice,
  change,
  changePct,
  openPnL,
  positionSize,
  onOpenConsole,
  isLive,
}: TelemetryChartProps) => {
  const hasPosition = openPnL !== undefined && positionSize !== undefined && positionSize > 0;
  const isProfitable = (openPnL || 0) >= 0;

  return (
    <Card className="relative h-full bg-card/30 backdrop-blur-sm border-white/10 overflow-hidden">
      {/* HUD Overlay - Top Left */}
      <div className="absolute top-4 left-4 z-10 bg-background/80 backdrop-blur-md rounded-lg border border-white/10 p-3 shadow-lg">
        <div className="flex items-baseline gap-3">
          <span className="text-2xl font-bold number-mono">{symbol}</span>
          <span className="text-xl font-bold number-mono">${currentPrice.toFixed(2)}</span>
          <Badge
            className={`text-sm font-bold number-mono px-2 py-1 rounded ${
              changePct >= 0
                ? "bg-bull/20 text-bull border border-bull/40"
                : "bg-bear/20 text-bear border border-bear/40"
            }`}
          >
            {changePct >= 0 ? <ArrowUp className="h-3 w-3 mr-1 inline" /> : <ArrowDown className="h-3 w-3 mr-1 inline" />}
            {change >= 0 ? "+" : ""}{change.toFixed(2)} ({changePct >= 0 ? "+" : ""}{changePct.toFixed(2)}%)
          </Badge>
          {isLive ? (
            <Badge className="bg-bull/20 text-bull border border-bull/30 text-[10px] px-1.5 py-0.5 animate-pulse">
              <Radio className="h-2.5 w-2.5 mr-1" />
              LIVE
            </Badge>
          ) : (
            <Badge variant="secondary" className="text-[10px] px-1.5 py-0.5 opacity-60">
              DEMO
            </Badge>
          )}
          {onOpenConsole && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={onOpenConsole}
                  className="h-8 w-8 ml-2 hover:bg-primary/20 hover:border-primary/40 border border-white/10"
                >
                  <Maximize2 className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>
                <p className="text-xs">Open Console with Battleground Mode</p>
              </TooltipContent>
            </Tooltip>
          )}
        </div>
      </div>

      {/* Floating P&L Badge - Top Right */}
      {hasPosition && (
        <div className="absolute top-4 right-4 z-10">
          <div
            className={`relative px-6 py-4 rounded-lg border-2 backdrop-blur-md shadow-2xl transition-all ${
              isProfitable
                ? "bg-bull/10 border-bull/50 shadow-bull/20 animate-pulse"
                : "bg-bear/10 border-bear/50 shadow-bear/20 animate-pulse"
            }`}
          >
            <div className="text-xs uppercase tracking-wider font-bold opacity-70 ui-label mb-1">
              Open P&L
            </div>
            <div className={`text-3xl font-extrabold number-mono ${isProfitable ? "text-bull" : "text-bear"}`}>
              {openPnL >= 0 ? "+" : ""}${Math.abs(openPnL).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
            <div className="text-xs opacity-70 number-mono mt-1">
              {positionSize} contracts
            </div>
            {/* Pulsing Ring Effect */}
            <div className={`absolute inset-0 rounded-lg border-2 animate-ping opacity-30 ${
              isProfitable ? "border-bull" : "border-bear"
            }`} />
          </div>
        </div>
      )}

      {/* Chart Container */}
      <div className="h-full">
        <TradingViewChart symbol={symbol} showCard={false} />
      </div>
    </Card>
  );
};
