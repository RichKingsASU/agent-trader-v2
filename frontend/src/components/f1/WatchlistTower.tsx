import { useState, useEffect, useRef } from "react";
import { Card } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { TrendingUp, TrendingDown, Flame, Zap, Radio } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import type { LiveStatus } from "@/hooks/useMarketLiveQuotes";
import { SystemStatusBadge } from "@/components/SystemStatusBadge";

export interface WatchlistItem {
  symbol: string;
  price: number;
  change: number;
  changePct: number;
  volume: number;
  status: "hot" | "trending" | "normal";
  sparklineData: number[];
  isLive?: boolean;
}

// Mock data fallback (used when no items prop provided)
const mockWatchlist: WatchlistItem[] = [
  { symbol: "SPY", price: 432.15, change: 1.23, changePct: 0.29, volume: 85000000, status: "hot", sparklineData: [430, 431, 430.5, 432, 431.8, 432.15] },
  { symbol: "QQQ", price: 368.50, change: -0.85, changePct: -0.23, volume: 45000000, status: "normal", sparklineData: [369, 368.8, 369.2, 368.5, 368.3, 368.5] },
  { symbol: "AAPL", price: 178.23, change: 2.15, changePct: 1.22, volume: 52000000, status: "trending", sparklineData: [176, 177, 177.5, 178, 178.1, 178.23] },
  { symbol: "TSLA", price: 245.67, change: -3.45, changePct: -1.38, volume: 95000000, status: "hot", sparklineData: [249, 247, 246, 245, 246, 245.67] },
  { symbol: "NVDA", price: 495.30, change: 8.75, changePct: 1.80, volume: 78000000, status: "trending", sparklineData: [487, 490, 492, 494, 495, 495.3] },
  { symbol: "AMD", price: 165.80, change: 1.90, changePct: 1.16, volume: 34000000, status: "normal", sparklineData: [164, 165, 164.5, 165.5, 165.7, 165.8] },
  { symbol: "MSFT", price: 412.45, change: -1.20, changePct: -0.29, volume: 28000000, status: "normal", sparklineData: [413, 412.5, 413, 412.8, 412.3, 412.45] },
];

const MiniSparkline = ({ data }: { data: number[] }) => {
  if (data.length < 2) return null;
  
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  
  const points = data.map((value, index) => {
    const x = (index / (data.length - 1)) * 60;
    const y = 20 - ((value - min) / range) * 20;
    return `${x},${y}`;
  }).join(" ");

  const isPositive = data[data.length - 1] >= data[0];
  
  return (
    <svg width="60" height="20" className="opacity-70">
      <polyline
        points={points}
        fill="none"
        stroke={isPositive ? "hsl(var(--bull))" : "hsl(var(--bear))"}
        strokeWidth="1.5"
      />
    </svg>
  );
};

const LoadingSkeleton = () => (
  <div className="p-2 space-y-1">
    {Array.from({ length: 5 }).map((_, i) => (
      <div key={i} className="p-3 rounded-lg bg-background/50 border border-border/5">
        <div className="flex items-center justify-between mb-2">
          <Skeleton className="h-4 w-12" />
          <Skeleton className="h-5 w-14" />
        </div>
        <div className="flex items-center justify-between">
          <Skeleton className="h-5 w-16" />
          <Skeleton className="h-5 w-14" />
        </div>
      </div>
    ))}
  </div>
);

interface WatchlistTowerProps {
  items?: WatchlistItem[];
  loading?: boolean;
  isLive?: boolean;
  feedStatus?: LiveStatus;
  heartbeatAt?: Date | null;
  hasLiveQuotes?: boolean;
  onSymbolClick?: (symbol: string) => void;
  onSymbolDoubleClick?: (symbol: string) => void;
}

// Track price flashes per symbol
type FlashState = Record<string, "up" | "down" | null>;

export const WatchlistTower = ({ 
  items,
  loading = false,
  isLive = false,
  feedStatus = "OFFLINE",
  heartbeatAt = null,
  hasLiveQuotes = false,
  onSymbolClick, 
  onSymbolDoubleClick 
}: WatchlistTowerProps) => {
  const displayItems = items && items.length > 0 ? items : mockWatchlist;
  const showingMock = !hasLiveQuotes;
  const statusTitle = heartbeatAt ? `Last heartbeat: ${heartbeatAt.toLocaleString()}` : "No heartbeat";
  
  // Track previous prices and flash states
  const prevPricesRef = useRef<Record<string, number>>({});
  const [flashStates, setFlashStates] = useState<FlashState>({});

  // Detect price changes and trigger flash
  useEffect(() => {
    if (!items || items.length === 0) return;

    const newFlashes: FlashState = {};
    
    items.forEach(item => {
      const prevPrice = prevPricesRef.current[item.symbol];
      if (prevPrice !== undefined && prevPrice !== item.price) {
        newFlashes[item.symbol] = item.price > prevPrice ? "up" : "down";
      }
      prevPricesRef.current[item.symbol] = item.price;
    });

    if (Object.keys(newFlashes).length > 0) {
      setFlashStates(prev => ({ ...prev, ...newFlashes }));
      
      // Clear flashes after animation
      const timeout = setTimeout(() => {
        setFlashStates(prev => {
          const cleared = { ...prev };
          Object.keys(newFlashes).forEach(sym => {
            cleared[sym] = null;
          });
          return cleared;
        });
      }, 600);
      
      return () => clearTimeout(timeout);
    }
  }, [items]);

  return (
    <Card className="h-full bg-card/50 backdrop-blur-sm border-border/10">
      <div className="p-4 border-b border-border/10 flex items-center justify-between">
        <h2 className="text-sm font-bold uppercase tracking-wider ui-label flex items-center gap-2">
          <div className="w-1 h-4 bg-primary rounded-full" />
          Timing Tower
        </h2>
        <div className="flex items-center gap-2">
          <SystemStatusBadge status={feedStatus} title={statusTitle} className="px-1.5 py-0" />
          {loading ? (
            <Badge variant="outline" className="text-[10px] px-1.5 py-0">
              LOADING
            </Badge>
          ) : isLive ? (
            <Badge className="bg-bull/20 text-bull border border-bull/30 text-[10px] px-1.5 py-0 animate-pulse">
              <Radio className="h-2.5 w-2.5 mr-1" />
              LIVE
            </Badge>
          ) : showingMock ? (
            <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
              DEMO
            </Badge>
          ) : null}
        </div>
      </div>
      <ScrollArea className="h-[calc(100vh-12rem)]">
        {loading ? (
          <LoadingSkeleton />
        ) : displayItems.length === 0 ? (
          <div className="p-6 text-center text-sm text-muted-foreground">
            {feedStatus === "OFFLINE"
              ? "Market data is offline."
              : feedStatus === "STALE"
                ? "Market data is stale."
                : "No live quotes yet."}
            <div className="mt-2 text-xs text-muted-foreground/80">
              Start the ingest/stream bridge, then refresh.
            </div>
          </div>
        ) : (
          <div className="p-2 space-y-1">
            {displayItems.map((item) => (
              <Tooltip key={item.symbol}>
                <TooltipTrigger asChild>
                  <div
                    onClick={() => onSymbolClick?.(item.symbol)}
                    onDoubleClick={() => onSymbolDoubleClick?.(item.symbol)}
                    className="group p-3 rounded-lg bg-background/50 border border-border/5 hover:border-primary/30 hover:bg-background/70 transition-all cursor-pointer"
                  >
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-bold number-mono">{item.symbol}</span>
                        {item.status === "hot" && <Flame className="h-3 w-3 text-orange-500" />}
                        {item.status === "trending" && <Zap className="h-3 w-3 text-yellow-500" />}
                      </div>
                      <MiniSparkline data={item.sparklineData} />
                    </div>
                    
                    <div className="flex items-center justify-between">
                      <span 
                        className={`text-base font-bold number-mono transition-colors duration-300 ${
                          flashStates[item.symbol] === "up" 
                            ? "text-bull animate-pulse" 
                            : flashStates[item.symbol] === "down" 
                            ? "text-bear animate-pulse" 
                            : ""
                        }`}
                      >
                        ${item.price.toFixed(2)}
                      </span>
                      <Badge
                        className={`text-xs font-bold number-mono px-2 py-0.5 rounded-full ${
                          item.changePct >= 0
                            ? "bg-bull/20 text-bull border border-bull/30"
                            : "bg-bear/20 text-bear border border-bear/30"
                        }`}
                      >
                        {item.changePct >= 0 ? <TrendingUp className="h-3 w-3 mr-1 inline" /> : <TrendingDown className="h-3 w-3 mr-1 inline" />}
                        {item.changePct >= 0 ? "+" : ""}{item.changePct.toFixed(2)}%
                      </Badge>
                    </div>
                  </div>
                </TooltipTrigger>
                <TooltipContent side="right">
                  <p className="text-xs">Click to select • Double-click for Console</p>
                </TooltipContent>
              </Tooltip>
            ))}
          </div>
        )}
      </ScrollArea>
    </Card>
  );
};
