import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Clock, Sun, Moon, Columns2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTheme } from "@/contexts/ThemeContext";
import { LayoutControls } from "@/components/LayoutControls";
import { SidebarToggle } from "@/layouts/MainLayout";
import { useLiveQuotes } from "@/hooks/useLiveQuotes";
import { useLiveAccount } from "@/hooks/useLiveAccount";
import { SystemStatusBadge } from "@/components/SystemStatusBadge";
import { SyncHealthStatus } from "@/components/SyncHealthStatus";
import { Skeleton } from "@/components/ui/skeleton";
import { formatUsd2 } from "@/lib/utils";
import { PanicButton } from "@/components/PanicButton";
import { ShadowToggle } from "@/components/ShadowToggle";

interface DashboardHeaderProps {
  currentSymbol: string;
  onSymbolChange: (symbol: string) => void;
  environment: "production" | "sandbox";
  equity?: number;
  dayPnl?: number;
  dayPnlPct?: number;
  splitMode?: boolean;
  onSplitModeToggle?: () => void;
  secondSymbol?: string;
  onSecondSymbolChange?: (symbol: string) => void;
}

const SYMBOLS = ["SPY", "QQQ", "IWM", "AAPL", "TSLA", "NVDA", "MSFT", "AMD"];

export const DashboardHeader = ({
  currentSymbol,
  onSymbolChange,
  environment,
  equity,
  dayPnl,
  dayPnlPct,
  splitMode = false,
  onSplitModeToggle,
  secondSymbol = "QQQ",
  onSecondSymbolChange,
}: DashboardHeaderProps) => {
  const { theme, toggleTheme } = useTheme();
  const [timeToClose, setTimeToClose] = useState("");
  const [marketStatus, setMarketStatus] = useState<"open" | "closed">("open");
  const { status: ingestStatus, heartbeatAt } = useLiveQuotes({ subscribeQuotes: false });
  const {
    equity: cachedEquity,
    updatedAt: accountUpdatedAt,
    loading: accountLoading,
    hasCache: hasAccountCache,
  } = useLiveAccount();
  const ingestTitle = heartbeatAt
    ? `Market ingest heartbeat: ${heartbeatAt.toLocaleString()}`
    : "Market ingest heartbeat: none";
  const usd2 = useMemo(
    () =>
      new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }),
    [],
  );

  const effectiveEquity = typeof equity === "number" && Number.isFinite(equity) && equity !== 0 ? equity : cachedEquity;
  const effectiveDayPnl = typeof dayPnl === "number" && Number.isFinite(dayPnl) ? dayPnl : 0;
  const effectiveDayPnlPct = typeof dayPnlPct === "number" && Number.isFinite(dayPnlPct) ? dayPnlPct : 0;

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      const marketClose = new Date(now);
      marketClose.setHours(16, 0, 0, 0);

      if (now > marketClose) {
        setMarketStatus("closed");
        const nextOpen = new Date(now);
        nextOpen.setDate(nextOpen.getDate() + 1);
        nextOpen.setHours(9, 30, 0, 0);
        const diff = nextOpen.getTime() - now.getTime();
        const hours = Math.floor(diff / (1000 * 60 * 60));
        const mins = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
        const secs = Math.floor((diff % (1000 * 60)) / 1000);
        setTimeToClose(`Next Open in ${hours}:${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`);
      } else {
        setMarketStatus("open");
        const diff = marketClose.getTime() - now.getTime();
        const hours = Math.floor(diff / (1000 * 60 * 60));
        const mins = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
        const secs = Math.floor((diff % (1000 * 60)) / 1000);
        setTimeToClose(`${hours}:${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")} to Close`);
      }
    };

    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, []);

  return (
    <header className="sticky top-0 z-50 w-full border-b border-white/10 backdrop-blur-md bg-card/80 shadow-lg">
      <div className="flex h-16 items-center justify-between px-6 gap-8">
        {/* Left Section: Sidebar Toggle + Title + Environment Badge */}
        <div className="flex items-center gap-3 min-w-fit">
          <SidebarToggle />
          <h1 className="text-lg font-bold tracking-tight ui-label">Pro Day Trading Dashboard</h1>
          <Badge
            className={
              environment === "production"
                ? "bg-production text-production-foreground border-0 px-3 py-1 text-xs font-semibold shadow-lg shadow-production/20"
                : "bg-sandbox text-sandbox-foreground border-0 px-3 py-1 text-xs font-semibold shadow-lg shadow-sandbox/20"
            }
          >
            {environment.toUpperCase()}
          </Badge>
          
          {/* Theme Toggle */}
          <Button
            variant="ghost"
            size="icon"
            onClick={toggleTheme}
            className="ml-2 h-9 w-9 rounded-full border border-white/10 hover:bg-accent/10"
            title={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
          >
            {theme === "dark" ? (
              <Sun className="h-4 w-4 text-yellow-500" />
            ) : (
              <Moon className="h-4 w-4 text-blue-600" />
            )}
          </Button>
        </div>

        {/* Center Section: Symbol Selector(s) + Split Mode Toggle */}
        <div className="flex items-center justify-center flex-1 gap-3">
          {/* Split Mode Toggle */}
          {onSplitModeToggle && (
            <Button
              variant={splitMode ? "default" : "outline"}
              size="icon"
              onClick={onSplitModeToggle}
              className="h-10 w-10 shrink-0"
              title="Toggle split-screen mode"
            >
              <Columns2 className="h-4 w-4" />
            </Button>
          )}
          
          {/* Primary Symbol Selector */}
          <Select value={currentSymbol} onValueChange={onSymbolChange}>
            <SelectTrigger className="w-40 h-10 border-2 border-border hover:border-primary/50 transition-colors font-semibold text-base bg-card">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-popover border-border z-[100]">
              {SYMBOLS.map((symbol) => (
                <SelectItem 
                  key={symbol} 
                  value={symbol}
                  className="font-medium hover:bg-accent/50 cursor-pointer"
                >
                  {symbol}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          
          {/* Second Symbol Selector (Split Mode) */}
          {splitMode && onSecondSymbolChange && (
            <>
              <span className="text-muted-foreground font-bold">vs</span>
              <Select value={secondSymbol} onValueChange={onSecondSymbolChange}>
                <SelectTrigger className="w-40 h-10 border-2 border-border hover:border-primary/50 transition-colors font-semibold text-base bg-card">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-popover border-border z-[100]">
                  {SYMBOLS.map((symbol) => (
                    <SelectItem 
                      key={symbol} 
                      value={symbol}
                      className="font-medium hover:bg-accent/50 cursor-pointer"
                    >
                      {symbol}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </>
          )}
        </div>

        {/* Right Section: Shadow Toggle + Panic Button + Layout Controls + Account Summary + Market Time */}
        <div className="flex items-center gap-4 min-w-fit">
          {/* Shadow Mode Toggle */}
          <ShadowToggle />
          
          {/* Emergency Kill-Switch */}
          <PanicButton variant="compact" />
          
          {/* Layout Controls */}
          <LayoutControls />
          
          <div className="h-8 w-px bg-white/10" />
          
          <div className="text-right">
            <div className="text-xs text-muted-foreground font-medium uppercase tracking-wide ui-label">Equity</div>
            <div className="number-mono text-base font-bold text-foreground">
              {accountLoading && !hasAccountCache ? <Skeleton className="h-5 w-20 ml-auto" /> : formatUsd2(effectiveEquity)}
            </div>
          </div>
          
          <div className="h-8 w-px bg-white/10" />
          
          <div className="text-right">
            <div className="text-xs text-muted-foreground font-medium uppercase tracking-wide ui-label">Day P/L</div>
            <div className={`number-mono text-xl font-extrabold ${effectiveDayPnl >= 0 ? "bull-text" : "bear-text"}`}>
              {effectiveDayPnl >= 0 ? "+" : "-"}
              {formatUsd2(Math.abs(effectiveDayPnl))}
              <span className="ml-1.5 text-base font-bold">
                ({effectiveDayPnlPct >= 0 ? "+" : ""}
                {effectiveDayPnlPct.toFixed(2)}%)
              </span>
            </div>
          </div>
          
          <div className="h-8 w-px bg-white/10" />
          
          <div className="flex flex-col gap-1">
            <SyncHealthStatus updatedAt={accountUpdatedAt} loading={accountLoading} />
            <SystemStatusBadge status={ingestStatus} title={ingestTitle} className="text-xs font-semibold px-2.5 py-1 ui-label" />
            <Badge
              variant={marketStatus === "open" ? "default" : "secondary"}
              className={`text-xs font-semibold px-2.5 py-1 ui-label ${
                marketStatus === "open" 
                  ? "bg-bull/20 text-bull border border-bull/30" 
                  : "bg-muted text-muted-foreground border border-white/10"
              }`}
            >
              {marketStatus === "open" ? "● MARKET OPEN" : "○ MARKET CLOSED"}
            </Badge>
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground ui-label">
              <Clock className="h-3.5 w-3.5" />
              <span className="number-mono font-medium">{timeToClose}</span>
            </div>
          </div>
        </div>
      </div>
    </header>
  );
};
